"""
Онбординг флоу — ConversationHandler.

3-step flow:
  Step 1 — Segment: Для кого? (ребёнок → пол + имя + возраст / себя → имя)
  Step 2 — City: В каком городе?
  Step 3 — Done! Завтра пришлю образ.

States:
  0. WELCOME — Касси приветствие
  1. WHO_FOR — для кого (ребёнок / себя)
  2. CHILD_GENDER — девочка / мальчик
  3. CHILD_NAME — имя ребёнка
  4. CHILD_AGE — сколько лет (fuzzy: "3", "3 года", "3г")
  5. SELF_NAME — как тебя зовут (no_kids path)
  6. CITY — город (геолокация / текст + Nominatim)
  7. CITY_SUGGEST — уточнение города
  8. RESUME_CONFIRM — продолжить / начать заново
  9. DONE_BUTTONS — финальные кнопки

  (Legacy states kept for DB compatibility but not used in new flow:)
  10. CHILD_BIRTHDATE — legacy (mapped to CHILD_AGE)
  11. PREGNANT_TRIMESTER — legacy
"""
import re
import structlog
import sentry_sdk
import httpx
from datetime import datetime, date, timedelta
from config import settings

import sqlalchemy as sa
from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from db.base import AsyncWriteSession, AsyncReadSession
from db.models.user import User
from db.crud.children import create_child, get_children
from services.i18n.ru import t

logger = structlog.get_logger()

# ── Состояния ──────────────────────────────────────────────────────────────
(
    WELCOME,
    WHO_FOR,
    CHILD_GENDER,
    CHILD_NAME,
    CHILD_AGE,
    SELF_NAME,
    CITY,
    CITY_SUGGEST,
    RESUME_CONFIRM,
    DONE_BUTTONS,
    CHILD_BIRTHDATE,      # legacy alias → CHILD_AGE
    PREGNANT_TRIMESTER,    # legacy, not used in new flow
) = range(12)

# Backward compat aliases
SEGMENT = WHO_FOR
ALSO_SELF = CHILD_GENDER

_STEP_TO_STATE: dict[str, int] = {
    "segment":              WHO_FOR,
    "child_gender":         CHILD_GENDER,
    "child_name":           CHILD_NAME,
    "child_age":            CHILD_AGE,
    "child_birthdate":      CHILD_AGE,  # legacy mapping
    "self_name":            SELF_NAME,
    "city":                 CITY,
    "pregnant_trimester":   CITY,  # legacy: skip trimester, go to city
}

# Тексты кнопок клавиатуры — не должны сохраняться как город
_CITY_KEYBOARD_LABELS = {
    "📍 Определить автоматически",
    "✏️ Ввести вручную",
    "📍 Отправить геолокацию",
    "Ввести вручную",
}


# ── Прогресс-бар ────────────────────────────────────────────────────────────

def progress_bar(step: int, total: int = 3) -> str:
    filled = "🟪" * step
    empty = "⬜" * (total - step)
    return filled + empty


# ── Fuzzy парсинг возраста ─────────────────────────────────────────────────

def parse_age(text: str):
    """Парсит возраст из разных форматов. Returns int age or None."""
    text = text.strip().lower()

    # "3" или "3 года" / "3 лет" / "3 г" → возраст
    age_match = re.match(r"^(\d{1,2})\s*(год|лет|года|годик|годика|г\.?)?$", text)
    if age_match:
        age = int(age_match.group(1))
        if 0 <= age <= 18:
            return age

    return None


def parse_birthdate(text: str):
    """Парсит дату рождения из разных форматов. Returns date or None.
    Kept for backward compatibility.
    """
    from datetime import date as _date
    text = text.strip().lower()

    # "3" или "3 года" / "3 лет" / "3 г" → возраст
    age_match = re.match(r"^(\d{1,2})\s*(год|лет|года|годик|годика|г\.?)?$", text)
    if age_match:
        age = int(age_match.group(1))
        if 0 <= age <= 18:
            return _date.today() - timedelta(days=age * 365)

    # дд.мм.гггг / дд/мм/гггг / дд-мм-гггг
    date_match = re.match(r"^(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})$", text)
    if date_match:
        d, m, y = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        if y < 100:
            y += 2000
        try:
            return _date(y, m, d)
        except ValueError:
            return None

    return None


# ── Вспомогательные функции ────────────────────────────────────────────────

async def _save_user_fields(user: User, **fields) -> None:
    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(User).where(User.id == user.id).values(**fields)
        )
        await session.commit()
    for k, v in fields.items():
        setattr(user, k, v)


async def _ask_city(update: Update, step_num: int = 2) -> None:
    pb = progress_bar(step_num)
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Определить автоматически", request_location=True)],
            [KeyboardButton("✏️ Ввести вручную")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(
        f"{pb}\n\nВ каком городе живёшь? 🏙",
        reply_markup=keyboard,
    )


async def _reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    city = "Неизвестно"
    timezone = "Europe/Vilnius"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json", "accept-language": "ru"},
                headers={"User-Agent": "FashionBot/1.0"},
            )
            addr = resp.json().get("address", {})
            city = (
                addr.get("city")
                or addr.get("town")
                or addr.get("village")
                or addr.get("county")
                or "Неизвестно"
            )
            logger.debug("geocode.reverse.ok", city=city)
    except Exception as e:
        logger.warning("geocode.reverse.failed", error=str(e))
    try:
        from timezonefinder import TimezoneFinder
        tz = TimezoneFinder().timezone_at(lat=lat, lng=lon)
        if tz:
            timezone = tz
    except Exception as e:
        logger.warning("timezone.lookup.failed", error=str(e))
    return city, timezone


async def _nominatim_search(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 3, "accept-language": "ru"},
                headers={"User-Agent": "FashionBot/1.0"},
            )
            data = resp.json()
            logger.debug("nominatim.search.ok", query=query, count=len(data))
            return [
                {
                    "display_name": r["display_name"],
                    "lat": float(r["lat"]),
                    "lon": float(r["lon"]),
                }
                for r in data
            ]
    except Exception as e:
        logger.warning("nominatim.search.failed", error=str(e))
        return []


def _extract_city_tz(result: dict) -> tuple[str, str]:
    city = result["display_name"].split(",")[0].strip()
    timezone = "Europe/Vilnius"
    try:
        from timezonefinder import TimezoneFinder
        tz = TimezoneFinder().timezone_at(lat=result["lat"], lng=result["lon"])
        if tz:
            timezone = tz
    except Exception as e:
        logger.warning("timezone.lookup.failed", error=str(e))
    return city, timezone


def _short_label(display_name: str) -> str:
    parts = [p.strip() for p in display_name.split(",")]
    return f"{parts[0]}, {parts[-1]}" if len(parts) >= 2 else parts[0]


# ── Entry point ────────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from bot.handlers.menu import get_main_menu
    user = context.user_data.get("db_user")
    if not user:
        return ConversationHandler.END

    if user.onboarding_completed:
        from datetime import datetime as _dt
        _hour = _dt.now().hour
        if _hour < 12:
            greeting = "Доброе утро"
        elif _hour < 18:
            greeting = "Добрый день"
        else:
            greeting = "Добрый вечер"
        _segment = getattr(user, "segment", "no_kids") or "no_kids"
        _child_name = None
        if _segment in ("mom_girl", "mom_boy"):
            async with AsyncReadSession() as _session:
                _children = await get_children(_session, user.id)
            _child_name = _children[0].name if _children else None
        if _child_name:
            _welcome = f"{greeting}, {user.name}! 👋\nРада видеть тебя и {_child_name} ✨\nЧем могу помочь сегодня?"
        else:
            _welcome = f"{greeting}, {user.name}! 👋\nРада видеть тебя снова ✨\nЧем могу помочь сегодня?"
        await update.effective_message.reply_text(_welcome, reply_markup=get_main_menu())
        return ConversationHandler.END

    # Предложить продолжить если есть незавершённый онбординг
    if user.onboarding_step and user.onboarding_step in _STEP_TO_STATE:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Продолжить", callback_data="resume:yes"),
            InlineKeyboardButton("🔄 Начать заново", callback_data="resume:no"),
        ]])
        await update.effective_message.reply_text(
            "Продолжить с места где остановилась?",
            reply_markup=keyboard,
        )
        return RESUME_CONFIRM

    # Новый пользователь → приветствие Касси
    pb = progress_bar(0)
    welcome_text = (
        f"{pb}\n\n"
        "Привет! Я Касси — твой стилист 👗\n"
        "Для кого подбираем?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👶 Для ребёнка", callback_data="who_for:child")],
        [InlineKeyboardButton("👩 Для себя", callback_data="who_for:self")],
    ])
    await update.effective_message.reply_text(welcome_text, reply_markup=keyboard)
    return WHO_FOR


# ── Welcome callback (legacy, redirects to WHO_FOR) ──────────────────────

async def handle_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pb = progress_bar(1)
    await query.message.reply_text(
        f"{pb}\n\n"
        "Привет! Я Касси — твой стилист 👗\n"
        "Для кого подбираем?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👶 Для ребёнка", callback_data="who_for:child")],
            [InlineKeyboardButton("👩 Для себя", callback_data="who_for:self")],
        ]),
    )
    return WHO_FOR


# ── Шаг 1: Кому ────────────────────────────────────────────────────────────

async def handle_who_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    choice = query.data.split(":")[1]  # child / self / both / pregnant

    if choice == "self" or choice == "pregnant":
        segment = "no_kids" if choice == "self" else "pregnant"
        context.user_data["segment"] = segment
        context.user_data["also_self"] = False
        await _save_user_fields(user, segment=segment, onboarding_step="self_name")
        pb = progress_bar(1)
        await query.message.reply_text(
            f"{pb}\n\nКак тебя зовут?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return SELF_NAME

    else:
        # child or both
        context.user_data["also_self"] = (choice == "both")
        await _save_user_fields(user, onboarding_step="child_gender")
        pb = progress_bar(1)
        await query.message.reply_text(
            f"{pb}\n\n",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Девочка 👧", callback_data="child_gender:girl"),
                 InlineKeyboardButton("Мальчик 👦", callback_data="child_gender:boy")],
            ]),
        )
        return CHILD_GENDER


# Backward-compat alias used in resume flow
async def handle_segment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_who_for(update, context)


# ── Шаг 1b: Пол ребёнка ─────────────────────────────────────────────────────

async def handle_child_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    gender = query.data.split(":")[1]  # girl / boy
    context.user_data["child_gender"] = gender
    segment = "mom_girl" if gender == "girl" else "mom_boy"
    context.user_data["segment"] = segment
    user = context.user_data.get("db_user")
    await _save_user_fields(user, segment=segment, onboarding_step="child_name")
    pb = progress_bar(1)
    await query.message.reply_text(
        f"{pb}\n\nКак зовут?",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CHILD_NAME


# Backward-compat alias
async def handle_also_self(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_child_gender(update, context)


# ── Шаг 1c: Имя ребёнка ─────────────────────────────────────────────────

async def handle_child_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Введи имя:")
        return CHILD_NAME

    user = context.user_data.get("db_user")
    context.user_data["child_name"] = name
    await _save_user_fields(user, onboarding_step="child_age")
    pb = progress_bar(1)
    await update.message.reply_text(f"{pb}\n\nСколько лет?")
    return CHILD_AGE


# ── Шаг 1d: Возраст ребёнка (fuzzy) ──────────────────────────────────────

async def handle_child_age(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    age = parse_age(text)
    if age is None:
        await update.message.reply_text(
            "Не поняла 🤔 Напиши возраст цифрой (например, 3)"
        )
        return CHILD_AGE

    # Convert age to approximate birthdate
    birthdate = date.today() - timedelta(days=age * 365)
    context.user_data["child_birthdate"] = birthdate
    context.user_data["child_age"] = age
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="city")
    await _ask_city(update, step_num=2)
    return CITY


# ── Шаг 1e: Имя (для себя / no_kids) ────────────────────────────────────

async def handle_self_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Введи имя:")
        return SELF_NAME

    user = context.user_data.get("db_user")
    await _save_user_fields(user, name=name, onboarding_step="city")
    await _ask_city(update, step_num=2)
    return CITY


# ── Legacy: handle_child_birthdate (old format, kept for resume compat) ──

async def handle_child_birthdate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy handler: accepts both age and date format for backward compat."""
    text = update.message.text.strip()

    # Try age first (new flow)
    age = parse_age(text)
    if age is not None:
        birthdate = date.today() - timedelta(days=age * 365)
        context.user_data["child_birthdate"] = birthdate
        context.user_data["child_age"] = age
        user = context.user_data.get("db_user")
        await _save_user_fields(user, onboarding_step="city")
        await _ask_city(update, step_num=2)
        return CITY

    # Try date format (legacy)
    birthdate = parse_birthdate(text)
    if birthdate is not None:
        context.user_data["child_birthdate"] = birthdate
        age_years = (date.today() - birthdate).days // 365
        context.user_data["child_age"] = age_years
        user = context.user_data.get("db_user")
        await _save_user_fields(user, onboarding_step="city")
        await _ask_city(update, step_num=2)
        return CITY

    await update.message.reply_text(
        "Не поняла 🤔 Напиши возраст цифрой (например, 3)"
    )
    return CHILD_AGE


# ── Legacy: handle_pregnant_trimester ──────────────────────────────────────

async def handle_pregnant_trimester(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Legacy handler: skip trimester, go straight to city."""
    query = update.callback_query
    await query.answer()
    trimester = int(query.data.split(":")[1])
    context.user_data["trimester"] = trimester
    user = context.user_data.get("db_user")
    await _save_user_fields(user, trimester=trimester, onboarding_step="city")
    await _ask_city(update, step_num=2)
    return CITY


# ── Шаг 2: Город ──────────────────────────────────────────────────────────

async def handle_city_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    city, timezone = await _reverse_geocode(loc.latitude, loc.longitude)
    context.user_data["city"] = city
    context.user_data["timezone"] = timezone
    return await _finish_onboarding(update, context)


async def handle_city_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    if text in _CITY_KEYBOARD_LABELS:
        await update.message.reply_text("Введи название города:", reply_markup=ReplyKeyboardRemove())
        return CITY

    if not text:
        await update.message.reply_text("Введи название города:")
        return CITY

    results = await _nominatim_search(text)

    if not results:
        await update.message.reply_text(
            "Город не найден, попробуй ещё раз или напиши по-английски",
            reply_markup=ReplyKeyboardRemove(),
        )
        return CITY

    if len(results) == 1:
        city, timezone = _extract_city_tz(results[0])
        context.user_data["city"] = city
        context.user_data["timezone"] = timezone
        return await _finish_onboarding(update, context)

    context.user_data["city_candidates"] = results
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(_short_label(r["display_name"]), callback_data=f"city_pick:{i}")]
        for i, r in enumerate(results)
    ])
    await update.message.reply_text("Уточни город:", reply_markup=keyboard)
    return CITY_SUGGEST


async def handle_city_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    idx = int(query.data.split(":")[1])
    candidates = context.user_data.get("city_candidates", [])

    if idx >= len(candidates):
        await query.message.reply_text(t("error.generic"))
        return ConversationHandler.END

    city, timezone = _extract_city_tz(candidates[idx])
    context.user_data["city"] = city
    context.user_data["timezone"] = timezone

    await query.message.edit_reply_markup(reply_markup=None)
    return await _finish_onboarding(update, context)


# ── Resume ─────────────────────────────────────────────────────────────────

async def handle_resume_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")

    if query.data == "resume:yes":
        return await _resume_step(update, context, user)

    # Начать заново — сбросить step в БД и в контексте
    for key in ("segment", "child_gender", "child_name", "child_birthdate",
                "child_age", "city", "timezone", "city_candidates",
                "also_self", "pregnant_name", "trimester"):
        context.user_data.pop(key, None)
    await _save_user_fields(user, onboarding_step=None, segment=None)
    # Show welcome again — new Касси format
    pb = progress_bar(0)
    welcome_text = (
        f"{pb}\n\n"
        "Привет! Я Касси — твой стилист 👗\n"
        "Для кого подбираем?"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👶 Для ребёнка", callback_data="who_for:child")],
        [InlineKeyboardButton("👩 Для себя", callback_data="who_for:self")],
    ])
    await query.message.reply_text(welcome_text, reply_markup=keyboard)
    return WHO_FOR


async def _resume_step(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User) -> int:
    step = user.onboarding_step
    segment = context.user_data.get("segment") or user.segment

    if step == "segment":
        pb = progress_bar(1)
        await update.effective_message.reply_text(
            f"{pb}\n\n"
            "Привет! Я Касси — твой стилист 👗\n"
            "Для кого подбираем?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👶 Для ребёнка", callback_data="who_for:child")],
                [InlineKeyboardButton("👩 Для себя", callback_data="who_for:self")],
            ]),
        )
        return WHO_FOR
    if step == "child_gender":
        pb = progress_bar(1)
        await update.effective_message.reply_text(
            f"{pb}\n\n",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Девочка 👧", callback_data="child_gender:girl"),
                 InlineKeyboardButton("Мальчик 👦", callback_data="child_gender:boy")],
            ]),
        )
        return CHILD_GENDER
    if step == "child_name":
        pb = progress_bar(1)
        if segment in ("pregnant", "no_kids"):
            await update.effective_message.reply_text(
                f"{pb}\n\nКак тебя зовут?", reply_markup=ReplyKeyboardRemove()
            )
            return SELF_NAME
        else:
            await update.effective_message.reply_text(
                f"{pb}\n\nКак зовут?", reply_markup=ReplyKeyboardRemove()
            )
            return CHILD_NAME
    if step == "self_name":
        pb = progress_bar(1)
        await update.effective_message.reply_text(
            f"{pb}\n\nКак тебя зовут?", reply_markup=ReplyKeyboardRemove()
        )
        return SELF_NAME
    if step in ("child_age", "child_birthdate"):
        pb = progress_bar(1)
        await update.effective_message.reply_text(
            f"{pb}\n\nСколько лет?", reply_markup=ReplyKeyboardRemove()
        )
        return CHILD_AGE
    if step == "pregnant_trimester":
        # Legacy: skip trimester, go to city
        await _ask_city(update, step_num=2)
        return CITY
    # step == "city"
    await _ask_city(update, step_num=2)
    return CITY


# ── Шаг 3: Финал ─────────────────────────────────────────────────────────

async def _finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from bot.handlers.menu import get_main_menu
    user = context.user_data.get("db_user")
    if not user:
        return ConversationHandler.END

    segment = context.user_data.get("segment") or (user.segment or "no_kids")
    city = context.user_data.get("city", "")
    timezone = context.user_data.get("timezone", "Europe/Vilnius")

    # Проверка обязательных полей для ребёнка
    if segment in ("mom_girl", "mom_boy"):
        required = ["child_name", "child_birthdate"]
        missing = [k for k in required if not context.user_data.get(k)]
        if missing:
            logger.error("onboarding.missing_fields", missing=missing, user_id=str(user.id))
            await update.effective_message.reply_text(
                "Что-то пошло не так. Начни заново: /start"
            )
            return ConversationHandler.END

    try:
        # Determine display name
        if segment in ("mom_girl", "mom_boy"):
            display_name = context.user_data.get("child_name", "")
        else:
            display_name = user.name or ""

        update_values = dict(
            city=city,
            timezone=timezone,
            onboarding_step=None,
            onboarding_completed=True,
        )

        # Save trimester for pregnant (legacy)
        if segment == "pregnant":
            trimester = context.user_data.get("trimester")
            if trimester:
                update_values["trimester"] = trimester

        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User)
                .where(User.id == user.id)
                .values(**update_values)
            )

            if segment in ("mom_girl", "mom_boy"):
                from db.models.child import Child as _Child
                child_name = context.user_data["child_name"]
                child_birthdate = context.user_data["child_birthdate"]
                child_gender = "girl" if segment == "mom_girl" else "boy"
                existing = await session.execute(
                    sa.select(_Child).where(
                        _Child.user_id == user.id,
                        _Child.deleted_at.is_(None),
                    ).order_by(_Child.created_at.asc()).limit(1)
                )
                existing_child = existing.scalar_one_or_none()
                if existing_child:
                    await session.execute(
                        sa.update(_Child).where(_Child.id == existing_child.id).values(
                            name=child_name,
                            birthdate=child_birthdate,
                            gender=child_gender,
                        )
                    )
                else:
                    await create_child(
                        session,
                        user_id=user.id,
                        name=child_name,
                        birthdate=child_birthdate,
                        gender=child_gender,
                    )

            await session.commit()

        user.onboarding_completed = True
        user.onboarding_step = None
        user.city = city
        user.timezone = timezone
        # Флаг для text handler: не вызывать Касси для этого же сообщения
        context.user_data["onboarding_just_completed"] = True

        # Step 3: Done message
        pb = progress_bar(3)
        done_text = (
            f"{pb}\n\n"
            f"🎉 Отлично, {display_name}! Познакомились!\n\n"
            "Завтра в 07:00 пришлю погоду + совет по образу.\n"
            "А пока — сфоткай вещи, чтобы я начала подбирать!"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📸 Сфоткать первую вещь", callback_data="onboard_done:photo")],
            [InlineKeyboardButton("Потом", callback_data="onboard_done:later")],
        ])
        await update.effective_message.reply_text(
            done_text, reply_markup=keyboard,
        )

        logger.info(
            "onboarding.completed",
            user_id=str(user.id),
            segment=segment,
            city=city,
        )
        logger.info("metric.onboarding_done",
            user_id=str(user.id),
            segment=user.segment,
        )

        return DONE_BUTTONS

    except Exception as e:
        await update.effective_message.reply_text(t("error.generic"))
        logger.error("onboarding.finish.failed", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)

    return ConversationHandler.END


# ── Done buttons handler ──────────────────────────────────────────────────

async def handle_done_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from bot.handlers.menu import get_main_menu
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    choice = query.data.split(":")[1]  # photo / later

    if choice == "photo":
        await query.message.reply_text(
            "Сфоткай вещь на светлом фоне. Начни с кофты 👚",
            reply_markup=get_main_menu(user, context),
        )
    else:
        await query.message.reply_text(
            "Хорошо! Когда будешь готова — просто сфоткай вещь и отправь мне 📸",
            reply_markup=get_main_menu(user, context),
        )

    return ConversationHandler.END


# ── /cancel fallback ───────────────────────────────────────────────────────

async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("segment", "child_gender", "child_name", "child_birthdate",
                "child_age", "city", "timezone", "city_candidates",
                "also_self", "pregnant_name", "trimester"):
        context.user_data.pop(key, None)
    await update.message.reply_text(
        "Отменено. /start чтобы начать заново",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ── Сборка ConversationHandler ────────────────────────────────────────────

def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", handle_start)],
        states={
            WELCOME: [
                CallbackQueryHandler(handle_welcome, pattern="^welcome:"),
            ],
            WHO_FOR: [
                CallbackQueryHandler(handle_who_for, pattern="^who_for:"),
                # backward compat: old "segment:" callbacks during resume
                CallbackQueryHandler(handle_segment, pattern="^segment:"),
            ],
            CHILD_GENDER: [
                CallbackQueryHandler(handle_child_gender, pattern="^child_gender:"),
                # backward compat: old "also_self:" callbacks
                CallbackQueryHandler(handle_also_self, pattern="^also_self:"),
            ],
            RESUME_CONFIRM: [
                CallbackQueryHandler(handle_resume_confirm, pattern="^resume:"),
            ],
            CHILD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_child_name),
            ],
            CHILD_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_child_age),
            ],
            SELF_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_self_name),
            ],
            # Legacy state: CHILD_BIRTHDATE mapped to same handler as CHILD_AGE
            CHILD_BIRTHDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_child_birthdate),
            ],
            CITY: [
                MessageHandler(filters.LOCATION, handle_city_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city_text),
            ],
            CITY_SUGGEST: [
                CallbackQueryHandler(handle_city_suggest, pattern="^city_pick:"),
            ],
            DONE_BUTTONS: [
                CallbackQueryHandler(handle_done_buttons, pattern="^onboard_done:"),
            ],
            PREGNANT_TRIMESTER: [
                CallbackQueryHandler(handle_pregnant_trimester, pattern="^trimester:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", handle_cancel)],
        allow_reentry=True,
    )

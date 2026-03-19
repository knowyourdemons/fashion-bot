"""
Онбординг флоу — ConversationHandler.

Шаги:
  0. Welcome screen (Касси intro + progress bar)
  1. WHO_FOR: для кого (ребёнок / себя / оба)
  2. CHILD_GENDER: девочка / мальчик
  3. Имя ребёнка
  4. Дата рождения (fuzzy: "3 года", "15.03.2023", ...)
  5. Размер одежды
  6. Размер обуви
  7. Город (геолокация / текст + Nominatim саджжест)
  8. Цветотип
  Финал → создать Child, onboarding_completed=True → показать главное меню
"""
import structlog
import sentry_sdk
import httpx
from datetime import datetime, date
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
    CHILD_BIRTHDATE,
    CHILD_SIZE,
    CHILD_SHOE_SIZE,
    CITY,
    CITY_SUGGEST,
    RESUME_CONFIRM,
    ASK_COLORTYPE,
) = range(11)

# Backward compat aliases
SEGMENT = WHO_FOR
ALSO_SELF = CHILD_GENDER

_STEP_TO_STATE: dict[str, int] = {
    "segment":         WHO_FOR,
    "child_gender":    CHILD_GENDER,
    "child_name":      CHILD_NAME,
    "child_birthdate": CHILD_BIRTHDATE,
    "child_size":      CHILD_SIZE,
    "child_shoe_size": CHILD_SHOE_SIZE,
    "city":            CITY,
    "colortype":       ASK_COLORTYPE,
}

# Тексты кнопок клавиатуры — не должны сохраняться как город
_CITY_KEYBOARD_LABELS = {
    "📍 Определить автоматически",
    "✏️ Ввести вручную",
    "📍 Отправить геолокацию",
    "Ввести вручную",
}

_COLORTYPE_MAP = {
    "🌸 Весна": "Весна",
    "☀️ Лето": "Лето",
    "🍂 Осень": "Осень",
    "❄️ Зима": "Зима",
    "🤷 Не знаю": None,
}

_COLORTYPE_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🌸 Весна", "☀️ Лето"],
        ["🍂 Осень", "❄️ Зима"],
        ["🤷 Не знаю"],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)

_AGE_TO_SIZE = {
    1: 80, 2: 92, 3: 98, 4: 104,
    5: 110, 6: 116, 7: 122, 8: 128,
    9: 134, 10: 140, 11: 146, 12: 152,
    13: 158, 14: 164, 15: 170, 16: 176,
}


# ── Прогресс-бар ────────────────────────────────────────────────────────────

def progress_bar(step: int, total: int = 5) -> str:
    filled = "🟪" * step
    empty = "⬜" * (total - step)
    return filled + empty


# ── Fuzzy парсинг даты рождения ─────────────────────────────────────────────

def parse_birthdate(text: str):
    """Парсит дату рождения из разных форматов. Returns date or None."""
    import re
    from datetime import date as _date, timedelta
    text = text.strip().lower()

    # "3" или "3 года" / "3 лет" / "3 г" → возраст
    age_match = re.match(r"^(\d{1,2})\s*(год|лет|года|г\.?)?$", text)
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


async def _ask_city(update: Update) -> None:
    keyboard = ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Определить автоматически", request_location=True)],
            [KeyboardButton("✏️ Ввести вручную")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(t("onboarding.city"), reply_markup=keyboard)


async def _ask_colortype(update: Update) -> None:
    await update.effective_message.reply_text(
        "🎨 Какой у тебя цветотип?\n\n"
        "🌸 Весна — тёплый, светлый (персик, золото, коралл)\n"
        "☀️ Лето — холодный, мягкий (лаванда, пудра, мята)\n"
        "🍂 Осень — тёплый, глубокий (горчица, терракота, олива)\n"
        "❄️ Зима — холодный, яркий (белый, чёрный, фуксия)\n\n"
        "Не знаю — пропустить",
        reply_markup=_COLORTYPE_KEYBOARD,
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


def _parse_shoe_size(text: str) -> float | None:
    """Принимает размер обуви целым или дробным (18–50). Примеры: 26, 26.5, 26,5"""
    try:
        normalized = text.strip().replace(",", ".")
        size = float(normalized)
        if 18 <= size <= 50:
            return size
        return None
    except ValueError:
        return None


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
            "Продолжить с места где остановился?",
            reply_markup=keyboard,
        )
        return RESUME_CONFIRM

    # Новый пользователь → приветствие Касси
    pb = progress_bar(0)
    welcome_text = (
        f"{pb}\n\n"
        "Привет! 👋 Я Касси — твой AI-стилист.\n\n"
        "Каждое утро буду присылать готовый образ по погоде "
        "из вещей, которые уже есть в шкафу.\n\n"
        "Познакомимся за 2 минуты? 😊"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Давай!", callback_data="welcome:start"),
    ]])
    await update.effective_message.reply_text(welcome_text, reply_markup=keyboard)
    return WELCOME


# ── Welcome callback ────────────────────────────────────────────────────────

async def handle_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    pb = progress_bar(1)
    await query.message.reply_text(
        f"{pb}\n\nДля кого подбираем образы?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👶 Для ребёнка", callback_data="who_for:child")],
            [InlineKeyboardButton("👩 Для себя", callback_data="who_for:self")],
            [InlineKeyboardButton("👩‍👧 И для ребёнка, и для себя", callback_data="who_for:both")],
        ]),
    )
    return WHO_FOR


# ── Шаг 1: Кому ────────────────────────────────────────────────────────────

async def handle_who_for(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")
    choice = query.data.split(":")[1]  # child / self / both

    if choice == "self":
        segment = "no_kids"
        context.user_data["segment"] = segment
        context.user_data["also_self"] = False
        await _save_user_fields(user, segment=segment, onboarding_step="city")
        pb = progress_bar(3)
        await query.message.reply_text(
            f"{pb}\n\n" + t("onboarding.city"),
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Определить автоматически", request_location=True)],
                 [KeyboardButton("✏️ Ввести вручную")]],
                resize_keyboard=True, one_time_keyboard=True,
            )
        )
        return CITY
    else:
        # child or both
        context.user_data["also_self"] = (choice == "both")
        await _save_user_fields(user, onboarding_step="child_gender")
        pb = progress_bar(2)
        await query.message.reply_text(
            f"{pb}\n\nДевочка или мальчик? 🎀",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👧 Девочка", callback_data="child_gender:girl"),
                 InlineKeyboardButton("👦 Мальчик", callback_data="child_gender:boy")],
            ]),
        )
        return CHILD_GENDER


# Backward-compat alias used in resume flow
async def handle_segment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_who_for(update, context)


# ── Шаг 2: Пол ребёнка ─────────────────────────────────────────────────────

async def handle_child_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    gender = query.data.split(":")[1]  # girl / boy
    context.user_data["child_gender"] = gender
    segment = "mom_girl" if gender == "girl" else "mom_boy"
    context.user_data["segment"] = segment
    user = context.user_data.get("db_user")
    await _save_user_fields(user, segment=segment, onboarding_step="child_name")
    pb = progress_bar(2)
    name_q = "Как зовут? 💕" if gender == "girl" else "Как зовут? 😊"
    await query.message.reply_text(f"{pb}\n\n{name_q}", reply_markup=ReplyKeyboardRemove())
    return CHILD_NAME


# Backward-compat alias
async def handle_also_self(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await handle_child_gender(update, context)


# ── Шаг 3: Имя ребёнка ────────────────────────────────────────────────────

async def handle_child_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Введи имя ребёнка:")
        return CHILD_NAME
    context.user_data["child_name"] = name
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="child_birthdate")
    gender = context.user_data.get("child_gender", "girl")
    pb = progress_bar(2)
    if gender == "boy":
        date_q = f"Когда родился {name}?\n\nНапиши дату (15.03.2023) или возраст (3 года)"
    else:
        date_q = f"Когда родилась {name}?\n\nНапиши дату (15.03.2023) или возраст (3 года)"
    await update.message.reply_text(f"{pb}\n\n{date_q}")
    return CHILD_BIRTHDATE


# ── Шаг 4: Дата рождения ──────────────────────────────────────────────────

async def handle_child_birthdate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    birthdate = parse_birthdate(text)
    if birthdate is None:
        await update.message.reply_text(
            "Не поняла 🤔 Напиши дату (15.03.2023) или просто возраст цифрой (3)"
        )
        return CHILD_BIRTHDATE
    context.user_data["child_birthdate"] = birthdate
    # Also extract age for size suggestion
    age_years = (date.today() - birthdate).days // 365
    context.user_data["child_age"] = age_years
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="child_size")
    child_name = context.user_data.get("child_name", "ребёнка")
    pb = progress_bar(3)
    await update.message.reply_text(
        f"{pb}\n\nКакой размер одежды {child_name}? 👗\n\n"
        "Напиши размер (86, 92, 104, 116...)\nИли возраст — подберу примерный"
    )
    return CHILD_SIZE


# ── Шаг 5: Размер одежды ──────────────────────────────────────────────────

async def handle_child_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    child_name = context.user_data.get("child_name", "ребёнка")
    size = text
    try:
        val = int(text)
        if 1 <= val <= 16:
            size = str(_AGE_TO_SIZE.get(val, val * 6 + 74))
        # else it's already a size number like 92, 104 etc.
    except ValueError:
        if text.lower() in ("не знаю", "не знаю размер", "пропустить"):
            age = context.user_data.get("child_age", 3)
            size = str(_AGE_TO_SIZE.get(age, "92"))
    context.user_data["child_size"] = size
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="child_shoe_size")
    pb = progress_bar(3)
    await update.message.reply_text(
        f"{pb}\n\nРазмер обуви {child_name}? 👟\n\n"
        "Напиши число (26 или 26.5)",
        reply_markup=ReplyKeyboardMarkup(
            [["⏭ Пропустить"]], resize_keyboard=True, one_time_keyboard=True
        )
    )
    return CHILD_SHOE_SIZE


# ── Шаг 6: Размер обуви ───────────────────────────────────────────────────

async def handle_child_shoe_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text == "⏭ Пропустить":
        context.user_data["child_shoe_size"] = None
    else:
        shoe_size = _parse_shoe_size(text)
        if shoe_size is None:
            await update.message.reply_text(
                "Введи размер обуви числом (26, 26.5) или нажми ⏭ Пропустить",
                reply_markup=ReplyKeyboardMarkup(
                    [["⏭ Пропустить"]], resize_keyboard=True, one_time_keyboard=True
                )
            )
            return CHILD_SHOE_SIZE
        context.user_data["child_shoe_size"] = shoe_size
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="city")
    pb = progress_bar(4)
    await update.message.reply_text(
        f"{pb}\n\nВ каком городе живёте? 🏙\n\nНужно для прогноза погоды",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Определить автоматически", request_location=True)],
             [KeyboardButton("✏️ Ввести вручную")]],
            resize_keyboard=True, one_time_keyboard=True,
        )
    )
    return CITY


# ── Шаг 7: Город ──────────────────────────────────────────────────────────

async def handle_city_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    loc = update.message.location
    city, timezone = await _reverse_geocode(loc.latitude, loc.longitude)
    context.user_data["city"] = city
    context.user_data["timezone"] = timezone
    await _save_user_fields(context.user_data["db_user"], onboarding_step="colortype")
    await _ask_colortype(update)
    return ASK_COLORTYPE


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
        await _save_user_fields(context.user_data["db_user"], onboarding_step="colortype")
        await _ask_colortype(update)
        return ASK_COLORTYPE

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
    await _save_user_fields(context.user_data["db_user"], onboarding_step="colortype")
    await _ask_colortype(update)
    return ASK_COLORTYPE


# ── Шаг 8: Цветотип ───────────────────────────────────────────────────────

async def handle_colortype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    # Принять любой текст — если не в карте, то None (пропустить)
    colortype = _COLORTYPE_MAP.get(text)
    context.user_data["colortype"] = colortype
    return await _finish_onboarding(update, context)


# ── Resume ─────────────────────────────────────────────────────────────────

async def handle_resume_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")

    if query.data == "resume:yes":
        return await _resume_step(update, context, user)

    # Начать заново — сбросить step в БД и в контексте
    for key in ("segment", "child_gender", "child_name", "child_birthdate", "child_size",
                "child_shoe_size", "city", "timezone", "city_candidates", "colortype",
                "also_self", "child_age"):
        context.user_data.pop(key, None)
    await _save_user_fields(user, onboarding_step=None, segment=None)
    # Show Касси welcome again
    pb = progress_bar(0)
    welcome_text = (
        f"{pb}\n\n"
        "Привет! 👋 Я Касси — твой AI-стилист.\n\n"
        "Каждое утро буду присылать готовый образ по погоде "
        "из вещей, которые уже есть в шкафу.\n\n"
        "Познакомимся за 2 минуты? 😊"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Давай!", callback_data="welcome:start"),
    ]])
    await query.message.reply_text(welcome_text, reply_markup=keyboard)
    return WELCOME


async def _resume_step(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User) -> int:
    step = user.onboarding_step
    segment = context.user_data.get("segment") or user.segment

    if step == "segment":
        pb = progress_bar(1)
        await update.effective_message.reply_text(
            f"{pb}\n\nДля кого подбираем образы?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👶 Для ребёнка", callback_data="who_for:child")],
                [InlineKeyboardButton("👩 Для себя", callback_data="who_for:self")],
                [InlineKeyboardButton("👩‍👧 И для ребёнка, и для себя", callback_data="who_for:both")],
            ]),
        )
        return WHO_FOR
    if step == "child_gender":
        pb = progress_bar(2)
        await update.effective_message.reply_text(
            f"{pb}\n\nДевочка или мальчик? 🎀",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👧 Девочка", callback_data="child_gender:girl"),
                 InlineKeyboardButton("👦 Мальчик", callback_data="child_gender:boy")],
            ]),
        )
        return CHILD_GENDER
    if step == "child_name":
        gender = context.user_data.get("child_gender", "girl" if segment == "mom_girl" else "boy")
        pb = progress_bar(2)
        name_q = "Как зовут? 💕" if gender == "girl" else "Как зовут? 😊"
        await update.effective_message.reply_text(f"{pb}\n\n{name_q}", reply_markup=ReplyKeyboardRemove())
        return CHILD_NAME
    if step == "child_birthdate":
        child_name = context.user_data.get("child_name", "")
        gender = context.user_data.get("child_gender", "girl")
        pb = progress_bar(2)
        if child_name:
            if gender == "boy":
                date_q = f"Когда родился {child_name}?\n\nНапиши дату (15.03.2023) или возраст (3 года)"
            else:
                date_q = f"Когда родилась {child_name}?\n\nНапиши дату (15.03.2023) или возраст (3 года)"
        else:
            date_q = t("onboarding.child_birthdate")
        await update.effective_message.reply_text(f"{pb}\n\n{date_q}")
        return CHILD_BIRTHDATE
    if step == "child_size":
        child_name = context.user_data.get("child_name", "ребёнка")
        pb = progress_bar(3)
        await update.effective_message.reply_text(
            f"{pb}\n\nКакой размер одежды {child_name}? 👗\n\n"
            "Напиши размер (86, 92, 104, 116...)\nИли возраст — подберу примерный"
        )
        return CHILD_SIZE
    if step == "child_shoe_size":
        child_name = context.user_data.get("child_name", "ребёнка")
        pb = progress_bar(3)
        await update.effective_message.reply_text(
            f"{pb}\n\nРазмер обуви {child_name}? 👟\n\nНапиши число (26 или 26.5)",
            reply_markup=ReplyKeyboardMarkup(
                [["⏭ Пропустить"]], resize_keyboard=True, one_time_keyboard=True
            )
        )
        return CHILD_SHOE_SIZE
    if step == "colortype":
        await _ask_colortype(update)
        return ASK_COLORTYPE
    # step == "city"
    await _ask_city(update)
    return CITY


# ── Финал ─────────────────────────────────────────────────────────────────

async def _finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from bot.handlers.menu import get_main_menu
    user = context.user_data.get("db_user")
    if not user:
        return ConversationHandler.END

    segment = context.user_data.get("segment") or (user.segment or "no_kids")
    city = context.user_data.get("city", "")
    timezone = context.user_data.get("timezone", "Europe/Vilnius")
    colortype = context.user_data.get("colortype")

    # Проверка обязательных полей для ребёнка
    if segment in ("mom_girl", "mom_boy"):
        required = ["child_name", "child_birthdate", "child_size"]
        missing = [k for k in required if not context.user_data.get(k)]
        if missing:
            logger.error("onboarding.missing_fields", missing=missing, user_id=str(user.id))
            await update.effective_message.reply_text(
                "Что-то пошло не так. Начни заново: /start"
            )
            return ConversationHandler.END

    try:
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User)
                .where(User.id == user.id)
                .values(
                    city=city,
                    timezone=timezone,
                    colortype=colortype,
                    onboarding_step=None,
                    onboarding_completed=True,
                )
            )

            if segment in ("mom_girl", "mom_boy"):
                from db.models.child import Child as _Child
                child_name = context.user_data["child_name"]
                child_birthdate = context.user_data["child_birthdate"]
                child_gender = "girl" if segment == "mom_girl" else "boy"
                child_size = context.user_data.get("child_size")
                child_shoe = context.user_data.get("child_shoe_size")
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
                            current_size=child_size,
                            shoe_size=child_shoe,
                        )
                    )
                else:
                    await create_child(
                        session,
                        user_id=user.id,
                        name=child_name,
                        birthdate=child_birthdate,
                        gender=child_gender,
                        current_size=child_size,
                        shoe_size=child_shoe,
                    )

            await session.commit()

        user.onboarding_completed = True
        user.onboarding_step = None
        user.city = city
        user.timezone = timezone
        user.colortype = colortype
        # Флаг для text handler: не вызывать Касси для этого же сообщения
        context.user_data["onboarding_just_completed"] = True

        child_name = context.user_data.get("child_name")
        if segment in ("mom_girl", "mom_boy") and child_name:
            item_target = f"вещей {child_name}"
        else:
            item_target = "из своего шкафа"

        welcome = (
            f"🎉 Отлично, {user.name}!\n\n"
            f"Теперь самое интересное — пришли 5 любимых вещей {item_target} "
            "и я соберу первый образ!\n\n"
            "📸 Фотографируй по одной вещи на светлом фоне"
        )
        await update.effective_message.reply_text(
            welcome, reply_markup=get_main_menu()
        )
        logger.info(
            "onboarding.completed",
            user_id=str(user.id),
            segment=segment,
            city=city,
            colortype=colortype,
        )

    except Exception as e:
        await update.effective_message.reply_text(t("error.generic"))
        logger.error("onboarding.finish.failed", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)

    return ConversationHandler.END


# ── /cancel fallback ───────────────────────────────────────────────────────

async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("segment", "child_gender", "child_name", "child_birthdate", "child_size",
                "child_shoe_size", "city", "timezone", "city_candidates", "colortype",
                "also_self", "child_age"):
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
            CHILD_BIRTHDATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_child_birthdate),
            ],
            CHILD_SIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_child_size),
            ],
            CHILD_SHOE_SIZE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_child_shoe_size),
            ],
            CITY: [
                MessageHandler(filters.LOCATION, handle_city_location),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_city_text),
            ],
            CITY_SUGGEST: [
                CallbackQueryHandler(handle_city_suggest, pattern="^city_pick:"),
            ],
            ASK_COLORTYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_colortype),
            ],
        },
        fallbacks=[CommandHandler("cancel", handle_cancel)],
        allow_reentry=True,
    )

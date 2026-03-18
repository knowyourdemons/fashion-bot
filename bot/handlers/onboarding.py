"""
Онбординг флоу — ConversationHandler.

Шаги:
  1. Выбор сегмента (InlineKeyboard)
  2. Имя ребёнка [mom_girl/mom_boy]
  3. Дата рождения dd.mm.yyyy [mom_girl/mom_boy]
  4. Размер одежды [mom_girl/mom_boy]
  5. Размер обуви [mom_girl/mom_boy]
  6. Город (геолокация / текст + Nominatim саджжест) [все]
  7. Цветотип [все]
  Финал → создать Child, onboarding_completed=True → показать главное меню
"""
import structlog
import sentry_sdk
import httpx
from datetime import datetime

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

from db.base import AsyncWriteSession
from db.models.user import User
from db.crud.children import create_child
from services.i18n.ru import t

logger = structlog.get_logger()

# ── Состояния ──────────────────────────────────────────────────────────────
(
    SEGMENT,
    CHILD_NAME,
    CHILD_BIRTHDATE,
    CHILD_SIZE,
    CHILD_SHOE_SIZE,
    CITY,
    CITY_SUGGEST,
    RESUME_CONFIRM,
    ASK_COLORTYPE,
) = range(9)

_STEP_TO_STATE: dict[str, int] = {
    "segment":         SEGMENT,
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


# ── Вспомогательные функции ────────────────────────────────────────────────

async def _save_user_fields(user: User, **fields) -> None:
    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(User).where(User.id == user.id).values(**fields)
        )
        await session.commit()
    for k, v in fields.items():
        setattr(user, k, v)


async def _ask_segment(update: Update) -> None:
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("onboarding.segment.mom_girl"), callback_data="segment:mom_girl"),
            InlineKeyboardButton(t("onboarding.segment.mom_boy"),  callback_data="segment:mom_boy"),
        ],
        [
            InlineKeyboardButton(t("onboarding.segment.pregnant"), callback_data="segment:pregnant"),
            InlineKeyboardButton(t("onboarding.segment.no_kids"),  callback_data="segment:no_kids"),
        ],
    ])
    await update.effective_message.reply_text(t("onboarding.start"), reply_markup=keyboard)


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


# ── Entry point ────────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from bot.handlers.menu import get_main_menu
    user = context.user_data.get("db_user")
    if not user:
        return ConversationHandler.END

    if user.onboarding_completed:
        await update.effective_message.reply_text(
            f"Привет, {user.name}! 👋",
            reply_markup=get_main_menu(),
        )
        return ConversationHandler.END

    # Предложить продолжить с места или начать заново
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

    await _ask_segment(update)
    await _save_user_fields(user, onboarding_step="segment")
    return SEGMENT


async def handle_resume_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = context.user_data.get("db_user")

    if query.data == "resume:yes":
        return await _resume_step(update, context, user)

    # Начать заново — сбросить step в БД и в контексте
    for key in ("segment", "child_name", "child_birthdate", "child_size", "child_shoe_size",
                "city", "timezone", "city_candidates", "colortype"):
        context.user_data.pop(key, None)
    await _save_user_fields(user, onboarding_step="segment", segment=None)
    await _ask_segment(update)
    return SEGMENT


async def _resume_step(update: Update, context: ContextTypes.DEFAULT_TYPE, user: User) -> int:
    step = user.onboarding_step
    segment = context.user_data.get("segment") or user.segment

    if step == "segment":
        await _ask_segment(update)
        return SEGMENT
    if step == "child_name":
        q = t("onboarding.child_name") if segment == "mom_girl" else "Как зовут сына?"
        await update.effective_message.reply_text(q, reply_markup=ReplyKeyboardRemove())
        return CHILD_NAME
    if step == "child_birthdate":
        await update.effective_message.reply_text(t("onboarding.child_birthdate"))
        return CHILD_BIRTHDATE
    if step == "child_size":
        await update.effective_message.reply_text(t("onboarding.child_size"))
        return CHILD_SIZE
    if step == "child_shoe_size":
        await update.effective_message.reply_text(t("onboarding.child_shoe_size"))
        return CHILD_SHOE_SIZE
    if step == "colortype":
        await _ask_colortype(update)
        return ASK_COLORTYPE
    # step == "city"
    await _ask_city(update)
    return CITY


# ── Шаг 1: Сегмент ────────────────────────────────────────────────────────

async def handle_segment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    segment = query.data.split(":")[1]
    context.user_data["segment"] = segment
    user = context.user_data.get("db_user")

    if segment in ("mom_girl", "mom_boy"):
        await _save_user_fields(user, segment=segment, onboarding_step="child_name")
        q = t("onboarding.child_name") if segment == "mom_girl" else "Как зовут сына?"
        await query.message.reply_text(q, reply_markup=ReplyKeyboardRemove())
        return CHILD_NAME
    else:
        await _save_user_fields(user, segment=segment, onboarding_step="city")
        await _ask_city(update)
        return CITY


# ── Шаг 2: Имя ребёнка ────────────────────────────────────────────────────

async def handle_child_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("Введи имя ребёнка:")
        return CHILD_NAME
    context.user_data["child_name"] = name
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="child_birthdate")
    await update.message.reply_text(t("onboarding.child_birthdate"))
    return CHILD_BIRTHDATE


# ── Шаг 3: Дата рождения ──────────────────────────────────────────────────

async def handle_child_birthdate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        birthdate = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text("Неверный формат. Введи дату в формате дд.мм.гггг:")
        return CHILD_BIRTHDATE
    context.user_data["child_birthdate"] = birthdate
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="child_size")
    await update.message.reply_text(t("onboarding.child_size"))
    return CHILD_SIZE


# ── Шаг 4: Размер одежды ──────────────────────────────────────────────────

async def handle_child_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    size = update.message.text.strip()
    context.user_data["child_size"] = size
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="child_shoe_size")
    await update.message.reply_text(t("onboarding.child_shoe_size"))
    return CHILD_SHOE_SIZE


# ── Шаг 5: Размер обуви ───────────────────────────────────────────────────

async def handle_child_shoe_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        shoe_size = int(text)
    except ValueError:
        await update.message.reply_text("Введи размер обуви цифрой (например, 27):")
        return CHILD_SHOE_SIZE
    context.user_data["child_shoe_size"] = shoe_size
    user = context.user_data.get("db_user")
    await _save_user_fields(user, onboarding_step="city")
    await _ask_city(update)
    return CITY


# ── Шаг 6: Город ──────────────────────────────────────────────────────────

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


# ── Шаг 7: Цветотип ───────────────────────────────────────────────────────

async def handle_colortype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    # Принять любой текст — если не в карте, то None (пропустить)
    colortype = _COLORTYPE_MAP.get(text)
    context.user_data["colortype"] = colortype
    return await _finish_onboarding(update, context)


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
        required = ["child_name", "child_birthdate", "child_size", "child_shoe_size"]
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
                existing = await session.execute(
                    sa.select(_Child).where(
                        _Child.user_id == user.id,
                        _Child.name == child_name,
                        _Child.deleted_at.is_(None),
                    )
                )
                existing_child = existing.scalar_one_or_none()
                if existing_child:
                    await session.execute(
                        sa.update(_Child).where(_Child.id == existing_child.id).values(
                            birthdate=context.user_data["child_birthdate"],
                            gender="girl" if segment == "mom_girl" else "boy",
                            current_size=context.user_data.get("child_size"),
                            shoe_size=context.user_data.get("child_shoe_size"),
                        )
                    )
                else:
                    await create_child(
                        session,
                        user_id=user.id,
                        name=child_name,
                        birthdate=context.user_data["child_birthdate"],
                        gender="girl" if segment == "mom_girl" else "boy",
                        current_size=context.user_data.get("child_size"),
                        shoe_size=context.user_data.get("child_shoe_size"),
                    )

            await session.commit()

        user.onboarding_completed = True
        user.onboarding_step = None
        user.city = city
        user.timezone = timezone
        user.colortype = colortype

        _CT_NAMES = {"spring": "Весна 🌸", "summer": "Лето ☀️", "autumn": "Осень 🍂", "winter": "Зима ❄️"}
        colortype_text = f"\n🎨 Цветотип: {_CT_NAMES.get(colortype, colortype)}" if colortype else ""
        welcome = (
            f"✅ Готово, {user.name}! Добро пожаловать 👗{colortype_text}\n\n"
            "Что умею:\n"
            "📸 Пришли фото вещи → добавлю в гардероб\n"
            "🌅 Morning Brief каждое утро — образ на день по погоде\n"
            "👗 Нажми кнопку Гардероб → список вещей\n"
            "❓ Помощь — справка"
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
    for key in ("segment", "child_name", "child_birthdate", "child_size",
                "child_shoe_size", "city", "timezone", "city_candidates", "colortype"):
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
            RESUME_CONFIRM: [
                CallbackQueryHandler(handle_resume_confirm, pattern="^resume:"),
            ],
            SEGMENT: [
                CallbackQueryHandler(handle_segment, pattern="^segment:"),
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

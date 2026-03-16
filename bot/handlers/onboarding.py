"""
Онбординг флоу — ConversationHandler.

Шаги:
  1. Выбор сегмента (InlineKeyboard)
  2. Имя ребёнка [mom_girl/mom_boy]
  3. Дата рождения dd.mm.yyyy [mom_girl/mom_boy]
  4. Размер одежды [mom_girl/mom_boy]
  5. Размер обуви [mom_girl/mom_boy]
  6. Город (геолокация или ввод вручную) [все]
  Финал → создать Child, onboarding_completed=True
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
SEGMENT, CHILD_NAME, CHILD_BIRTHDATE, CHILD_SIZE, CHILD_SHOE_SIZE, CITY = range(6)

_STEP_TO_STATE: dict[str, int] = {
    "segment":         SEGMENT,
    "child_name":      CHILD_NAME,
    "child_birthdate": CHILD_BIRTHDATE,
    "child_size":      CHILD_SIZE,
    "child_shoe_size": CHILD_SHOE_SIZE,
    "city":            CITY,
}


# ── Вспомогательные функции ────────────────────────────────────────────────

async def _save_user_fields(user: User, **fields) -> None:
    """Обновляет поля User в БД и в кэше context.user_data."""
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
            [KeyboardButton("📍 Отправить геолокацию", request_location=True)],
            [KeyboardButton("Ввести вручную")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.effective_message.reply_text(t("onboarding.city"), reply_markup=keyboard)


async def _reverse_geocode(lat: float, lon: float) -> tuple[str, str]:
    """Nominatim reverse geocoding + timezonefinder → (city, timezone)."""
    city = "Неизвестно"
    timezone = "Europe/Vilnius"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json"},
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


async def _forward_geocode_timezone(city: str) -> str:
    """Nominatim forward geocoding → timezone для города по имени."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": "FashionBot/1.0"},
            )
            data = resp.json()
            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                from timezonefinder import TimezoneFinder
                tz = TimezoneFinder().timezone_at(lat=lat, lng=lon)
                return tz or "Europe/Vilnius"
    except Exception as e:
        logger.warning("geocode.forward.failed", error=str(e))
    return "Europe/Vilnius"


# ── Entry point ────────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = context.user_data.get("db_user")
    if not user:
        return ConversationHandler.END

    if user.onboarding_completed:
        await update.effective_message.reply_text(
            f"Привет, {user.name}! Пришли фото вещи или /wardrobe",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    # Возобновить с сохранённого шага
    if user.onboarding_step and user.onboarding_step in _STEP_TO_STATE:
        return await _resume_step(update, context, user)

    await _ask_segment(update)
    await _save_user_fields(user, onboarding_step="segment")
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
        # pregnant / no_kids → сразу город
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
    return await _finish_onboarding(update, context)


async def handle_city_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Текстовый ввод города — сохраняем напрямую, без AI."""
    city = update.message.text.strip()
    if not city:
        await update.message.reply_text(t("onboarding.city"), reply_markup=ReplyKeyboardRemove())
        return CITY

    context.user_data["city"] = city
    context.user_data["timezone"] = await _forward_geocode_timezone(city)
    return await _finish_onboarding(update, context)


# ── Финал ─────────────────────────────────────────────────────────────────

async def _finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = context.user_data.get("db_user")
    if not user:
        return ConversationHandler.END

    segment = context.user_data.get("segment") or (user.segment or "no_kids")
    city = context.user_data.get("city", "")
    timezone = context.user_data.get("timezone", "Europe/Vilnius")

    try:
        async with AsyncWriteSession() as session:
            await session.execute(
                sa.update(User)
                .where(User.id == user.id)
                .values(
                    city=city,
                    timezone=timezone,
                    onboarding_step=None,
                    onboarding_completed=True,
                )
            )

            if segment in ("mom_girl", "mom_boy"):
                await create_child(
                    session,
                    user_id=user.id,
                    name=context.user_data.get("child_name", ""),
                    birthdate=context.user_data.get("child_birthdate"),
                    gender="girl" if segment == "mom_girl" else "boy",
                    current_size=context.user_data.get("child_size"),
                    shoe_size=context.user_data.get("child_shoe_size"),
                )

            await session.commit()

        user.onboarding_completed = True
        user.onboarding_step = None
        user.city = city
        user.timezone = timezone

        await update.effective_message.reply_text(
            t("onboarding.done"),
            reply_markup=ReplyKeyboardRemove(),
        )
        logger.info(
            "onboarding.completed",
            user_id=str(user.id),
            segment=segment,
            city=city,
        )

    except Exception as e:
        await update.effective_message.reply_text(t("error.generic"))
        logger.error("onboarding.finish.failed", error=str(e), user_id=str(user.id))
        sentry_sdk.capture_exception(e)

    return ConversationHandler.END


# ── Сборка ConversationHandler ────────────────────────────────────────────

def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("start", handle_start)],
        states={
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
        },
        fallbacks=[CommandHandler("start", handle_start)],
        allow_reentry=True,
    )

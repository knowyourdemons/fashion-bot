"""Travel capsule — 3-step inline flow: city → days → occasions → build."""
import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForceReply
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from telegram.ext import ApplicationHandlerStop

from core.permissions import get_effective_plan
from services.i18n import t, get_user_lang

logger = structlog.get_logger()

_OCCASIONS = [
    ("work", "🏢 Работа", "🏢 Work"),
    ("beach", "🏖 Пляж", "🏖 Beach"),
    ("culture", "🎭 Культура", "🎭 Culture"),
    ("dinner", "🍷 Ужин", "🍷 Dinner"),
    ("active", "🏃 Активный", "🏃 Active"),
    ("event", "👗 Событие", "👗 Event"),
]

_OCC_RU = {code: label_ru for code, label_ru, _ in _OCCASIONS}
_OCC_EN = {code: label_en for code, _, label_en in _OCCASIONS}


def _occasion_label(code: str, lang: str, selected: set) -> str:
    labels = _OCC_EN if lang == "en" else _OCC_RU
    label = labels.get(code, code)
    return f"✅ {label}" if code in selected else label


def _build_occasions_keyboard(selected: set, lang: str) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(_OCCASIONS), 2):
        row = []
        for j in range(i, min(i + 2, len(_OCCASIONS))):
            code = _OCCASIONS[j][0]
            row.append(InlineKeyboardButton(
                _occasion_label(code, lang, selected),
                callback_data=f"trv:occ:{code}",
            ))
        rows.append(row)
    build_text = t("travel.build_btn", lang)
    rows.append([InlineKeyboardButton(build_text, callback_data="trv:build")])
    return InlineKeyboardMarkup(rows)


async def handle_travel_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command /travel or callback travel:start → step 1: ask city."""
    user = context.user_data.get("db_user")
    if not user:
        return

    lang = get_user_lang(user)
    plan = get_effective_plan(user)

    if plan not in ("premium", "ultra", "admin"):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
        ]])
        text = t("travel.premium_gate", lang)
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    context.user_data["travel_step"] = "city"
    text = t("travel.ask_city", lang)
    placeholder = t("travel.city_placeholder", lang)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            text, reply_markup=ForceReply(input_field_placeholder=placeholder),
        )
    else:
        await update.message.reply_text(
            text, reply_markup=ForceReply(input_field_placeholder=placeholder),
        )


async def handle_travel_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Text message when travel_step=city → save city, show days."""
    if context.user_data.get("travel_step") != "city":
        return  # Not our message — let other handlers process it

    user = context.user_data.get("db_user")
    lang = get_user_lang(user) if user else "ru"
    city = update.message.text.strip()

    if not city or len(city) > 100:
        await update.message.reply_text(t("travel.invalid_city", lang))
        raise ApplicationHandlerStop()

    context.user_data["travel_city"] = city
    context.user_data["travel_step"] = "days"

    text = t("travel.ask_days", lang, city=city)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("3", callback_data="trv:days:3"),
        InlineKeyboardButton("5", callback_data="trv:days:5"),
        InlineKeyboardButton("7", callback_data="trv:days:7"),
        InlineKeyboardButton("10", callback_data="trv:days:10"),
        InlineKeyboardButton("14", callback_data="trv:days:14"),
    ]])
    await update.message.reply_text(text, reply_markup=kb)
    raise ApplicationHandlerStop()  # Prevent stylist chat from firing


async def handle_travel_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback trv:days:N → save days, show occasions."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    lang = get_user_lang(user) if user else "ru"

    days = int(query.data.split(":")[2])
    context.user_data["travel_days"] = days
    context.user_data["travel_step"] = "occasions"
    context.user_data["travel_occasions"] = set()

    city = context.user_data.get("travel_city", "?")
    text = t("travel.ask_occasions", lang, city=city, days=days)
    kb = _build_occasions_keyboard(set(), lang)

    await query.edit_message_text(text, reply_markup=kb)


async def handle_travel_occasion_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback trv:occ:CODE → toggle occasion selection."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    lang = get_user_lang(user) if user else "ru"

    occ = query.data.split(":")[2]
    selected = context.user_data.get("travel_occasions", set())

    if occ in selected:
        selected.discard(occ)
    else:
        selected.add(occ)
    context.user_data["travel_occasions"] = selected

    city = context.user_data.get("travel_city", "?")
    days = context.user_data.get("travel_days", 5)
    text = t("travel.ask_occasions", lang, city=city, days=days)
    kb = _build_occasions_keyboard(selected, lang)

    try:
        await query.edit_message_reply_markup(reply_markup=kb)
    except Exception:
        pass


async def handle_travel_build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback trv:build → build travel capsule and send result."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    lang = get_user_lang(user)
    city = context.user_data.get("travel_city", "?")
    days = context.user_data.get("travel_days", 5)
    occasions = list(context.user_data.get("travel_occasions", set()))

    await context.bot.send_chat_action(query.message.chat_id, ChatAction.TYPING)

    try:
        # Get weather for destination to determine temp_range
        temp_range = (10, 20)  # default
        try:
            from services.brief_weather import _geocode_city, _get_weather
            coords = await _geocode_city(city)
            if coords:
                weather = await _get_weather(coords[0], coords[1], "UTC")
                temp_d = weather.get("temp_day")
                if temp_d is not None:
                    temp_range = (temp_d - 5, temp_d + 5)
        except Exception:
            pass

        from db.base import AsyncReadSession
        from db.crud.wardrobe import get_owner_items
        from services.wardrobe_math import build_travel_capsule, format_travel_packing

        async with AsyncReadSession() as session:
            items = await get_owner_items(session, user.id, "user")

        from core.permissions import MIN_ITEMS_GAP_ANALYSIS
        if len(items) < MIN_ITEMS_GAP_ANALYSIS:
            await query.edit_message_text(t("capsule.too_few", lang, min=str(MIN_ITEMS_GAP_ANALYSIS)))
            _cleanup_travel(context)
            return

        # Map occasion codes to Russian labels for the backend
        occ_map = {"work": "работа", "beach": "пляж", "culture": "культура",
                    "dinner": "ужин", "active": "активный", "event": "событие"}
        occ_ru = [occ_map.get(o, o) for o in occasions] or ["культура"]

        capsule = build_travel_capsule(items, days, occ_ru, temp_range)
        packing = format_travel_packing(capsule)

        header = t("travel.result_header", lang, city=city, days=days)
        text = f"{header}\n\n{packing}"

        await query.edit_message_text(text)
        logger.info("travel.built", user_id=str(user.id), city=city, days=days,
                     items=len(capsule["items"]), combos=capsule["total_combos"])

    except Exception as e:
        logger.error("travel.error", user_id=str(user.id), error=str(e))
        await query.edit_message_text(t("error.generic", lang))
    finally:
        _cleanup_travel(context)


def _cleanup_travel(context):
    for key in ("travel_step", "travel_city", "travel_days", "travel_occasions"):
        context.user_data.pop(key, None)

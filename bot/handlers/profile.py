"""Profile handler + edit_city / edit_colortype / add_child flow."""
import time
import structlog
import sentry_sdk
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db.base import AsyncReadSession, AsyncWriteSession
from db.crud.children import get_children
from services.i18n import t, get_user_lang

logger = structlog.get_logger()

_COLORTYPE_LABELS = {
    "spring": "Весна 🌸",
    "summer": "Лето ☀️",
    "autumn": "Осень 🍂",
    "winter": "Зима ❄️",
}

_SEGMENT_LABELS = {
    "mom_girl": "👧 дочка",
    "mom_boy": "👦 сын",
    "pregnant": "🤰 беременность",
    "no_kids": "👩 для себя",
}


async def handle_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context.user_data.get("db_user")
    if not user:
        return

    lines = ["⚙️ *Профиль*\n"]
    lines.append(f"👤 Имя: {user.name}")
    if user.city:
        lines.append(f"🏙 Город: {user.city}")
    if user.colortype:
        ct_label = _COLORTYPE_LABELS.get(user.colortype, user.colortype)
        lines.append(f"🎨 Цветотип: {ct_label}")
    if user.segment:
        seg_label = _SEGMENT_LABELS.get(user.segment, user.segment)
        lines.append(f"👩 Подбираю для: {seg_label}")

    from core.permissions import get_effective_plan
    _effective_plan = get_effective_plan(user)
    plan_label = {"free": "Бесплатный", "premium": "Премиум", "admin": "Admin", "ultra": "Ultra"}.get(
        _effective_plan, _effective_plan
    )
    lines.append(f"💳 Тариф: {plan_label}")

    try:
        async with AsyncReadSession() as session:
            children = await get_children(session, user.id)
        if children:
            lines.append("\n👶 Дети:")
            for child in children:
                gender_icon = "👧" if child.gender == "girl" else "👦"
                parts = []
                if child.current_size:
                    parts.append(f"одежда {child.current_size}")
                if getattr(child, "shoe_size", None):
                    parts.append(f"обувь {child.shoe_size}")
                size_info = f" · {' · '.join(parts)}" if parts else ""
                lines.append(f"  {gender_icon} {child.name}{size_info}")
    except Exception as e:
        logger.error("profile.children.error", error=str(e))

    # Style preferences summary
    prefs = getattr(user, "style_preferences", None) or {}
    if prefs:
        pref_parts = []
        if prefs.get("style"):
            pref_parts.append(f"стиль: {prefs['style']}")
        if prefs.get("avoid"):
            pref_parts.append(f"избегать: {', '.join(prefs['avoid'][:3])}")
        if prefs.get("prefer"):
            pref_parts.append(f"люблю: {', '.join(prefs['prefer'][:3])}")
        if pref_parts:
            lines.append(f"💅 Предпочтения: {'; '.join(pref_parts)}")

    # Wardrobe math
    try:
        from db.crud.wardrobe import get_owner_items
        from services.wardrobe_math import calc_wardrobe_combos
        async with AsyncReadSession() as _ws:
            _w_items = await get_owner_items(_ws, user.id, "user")
        if _w_items:
            _combos = calc_wardrobe_combos(_w_items)
            _visual = len([i for i in _w_items if i.category_group not in ("underwear", "base_layer")])
            if _combos > 0:
                lines.append(f"\n📊 {_visual} вещей → {_combos} комбинаций")
    except Exception:
        pass

    # Kassi knows you %
    try:
        from services.preference_learner import build_user_preferences, calc_kassi_knows_pct
        _prefs = await build_user_preferences(str(user.id))
        _w_count = len(_w_items) if '_w_items' in locals() else 0
        _knows = calc_kassi_knows_pct(
            _prefs, _w_count,
            has_style_type=bool(prefs.get("style_type")),
            has_colortype=bool(user.colortype),
            has_body_type=bool(user.body_type),
        )
        if _knows <= 0:
            pass  # Don't show anything for brand new users
        elif _knows < 15:
            lines.append("\U0001f9e0 Касси только знакомится с тобой...")
        elif _knows < 50:
            lines.append(f"\U0001f9e0 Касси знает тебя на {_knows}% — с каждым днём точнее!")
        else:
            lines.append(f"\U0001f9e0 Касси знает тебя на {_knows}%")
    except Exception:
        pass

    # Style type from quiz
    if prefs.get("style_type"):
        from bot.handlers.style_quiz import STYLE_TYPES
        _st = STYLE_TYPES.get(prefs["style_type"])
        if _st:
            lines.append(f"✨ Стиль: {_st['label']}")

    # Реферальный код
    ref_code = getattr(user, "referral_code", None)
    if ref_code:
        lines.append(f"\n🎁 Твой реферальный код: `{ref_code}`")

    edit_buttons = [
        [
            InlineKeyboardButton("👗 Моя капсула", callback_data="capsule:build"),
            InlineKeyboardButton("🧳 Чемодан", callback_data="travel:start"),
        ],
        [InlineKeyboardButton("🏙 Изменить город", callback_data="edit_city")],
        [InlineKeyboardButton("🎨 Изменить цветотип", callback_data="edit_colortype")],
        [InlineKeyboardButton("💅 Стиль", callback_data="edit_style_prefs")],
        [InlineKeyboardButton("🌍 Язык / Language", callback_data="settings:lang")],
        [InlineKeyboardButton("👶 Добавить ребёнка", callback_data="add_child_start")],
    ]
    if getattr(user, "colortype", None):
        edit_buttons.append([
            InlineKeyboardButton("📸 Переснять селфи", callback_data="redo_selfie"),
        ])
    # Кнопки редактирования детей
    try:
        async with AsyncReadSession() as _s2:
            _ch = await get_children(_s2, user.id)
        for _c in [c for c in _ch if not c.deleted_at][:3]:
            edit_buttons.append([InlineKeyboardButton(
                f"📏 Размер {_c.name}", callback_data=f"edit_child_size:{_c.id}"
            )])
    except Exception:
        pass
    markup = InlineKeyboardMarkup(edit_buttons)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=markup)


async def handle_edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: edit_city → запросить новый город с кнопкой геолокации."""
    from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
    query = update.callback_query
    await query.answer()
    context.user_data["editing"] = "city"
    context.user_data["editing_ts"] = time.time()
    location_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Определить автоматически", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await query.message.reply_text(
        "🏙 В каком городе живёте?\n\nНапиши название города или отправь геолокацию (или «отмена»)",
        reply_markup=location_keyboard,
    )


async def handle_edit_city_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка геолокации при editing=city."""
    user = context.user_data.get("db_user")
    editing = context.user_data.get("editing")
    if not user or editing != "city":
        return

    loc = update.message.location
    if not loc:
        return

    from telegram import ReplyKeyboardRemove
    from bot.handlers.onboarding import _reverse_geocode

    city_name, tz_str = await _reverse_geocode(loc.latitude, loc.longitude)

    import sqlalchemy as sa
    from db.models.user import User as UserModel
    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(UserModel).where(UserModel.id == user.id).values(
                city=city_name, timezone=tz_str,
            )
        )
        await session.commit()
    user.city = city_name
    user.timezone = tz_str

    redis = context.bot_data.get("redis")
    if redis:
        await redis.delete(f"weather:cache:{city_name}")

    context.user_data.pop("editing", None)
    context.user_data.pop("editing_ts", None)
    await update.message.reply_text(
        f"✅ Город обновлён: {city_name}",
        reply_markup=ReplyKeyboardRemove(),
    )
    # Показать основное меню
    from bot.handlers.menu import get_main_menu
    await update.message.reply_text("Меню:", reply_markup=get_main_menu(context.user_data.get("db_user") if hasattr(context, "user_data") else None, context))


async def handle_edit_colortype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: edit_colortype → inline кнопки Весна/Лето/Осень/Зима."""
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🌸 Весна", callback_data="set_colortype:spring"),
        InlineKeyboardButton("☀️ Лето", callback_data="set_colortype:summer"),
    ], [
        InlineKeyboardButton("🍂 Осень", callback_data="set_colortype:autumn"),
        InlineKeyboardButton("❄️ Зима", callback_data="set_colortype:winter"),
    ]])
    await query.message.reply_text(
        "🎨 Выбери свой цветотип:\n\n"
        "🌸 Весна — тёплые светлые тона\n"
        "☀️ Лето — холодные приглушённые\n"
        "🍂 Осень — тёплые насыщенные\n"
        "❄️ Зима — холодные контрастные",
        reply_markup=keyboard,
    )


async def handle_set_colortype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: set_colortype:{value} → сохранить цветотип."""
    query = update.callback_query
    await query.answer()
    colortype = query.data.split(":")[1]
    user = context.user_data.get("db_user")
    if not user:
        return
    import sqlalchemy as sa
    from db.models.user import User as UserModel
    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(UserModel).where(UserModel.id == user.id).values(colortype=colortype)
        )
        await session.commit()
    user.colortype = colortype
    label = _COLORTYPE_LABELS.get(colortype, colortype)
    lang = get_user_lang(user)
    await query.message.reply_text(t("profile.colortype_updated", lang, label=label))


async def handle_edit_child_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: edit_child_size:{child_id} → запросить новый размер."""
    query = update.callback_query
    await query.answer()
    child_id_str = query.data.split(":")[1]
    context.user_data["editing"] = "child_size"
    context.user_data["editing_child_id"] = child_id_str
    context.user_data["editing_ts"] = time.time()
    await query.message.reply_text(
        "👕 Укажи размер одежды (56–176) и обуви через пробел:\n"
        "Например: «104 27» или «104» (только одежда)\n"
        "Или напиши «отмена»"
    )


async def handle_add_child_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: add_child_start → проверить лимит и начать мини-онбординг."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    from core.permissions import get_effective_plan, get_limit
    plan = get_effective_plan(user)
    child_limit = get_limit("children", plan)

    async with AsyncReadSession() as session:
        children = await get_children(session, user.id)
    active_children = [c for c in children if not c.deleted_at]

    if len(active_children) >= child_limit:
        word = "ребёнок" if child_limit == 1 else "детей"
        await query.message.reply_text(
            f"Максимум {child_limit} {word} для твоего плана.\n"
            "Обнови план чтобы добавить ещё! ✨"
        )
        return

    context.user_data["adding_child"] = {"step": "gender"}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("👧 Девочка", callback_data="new_child:girl"),
        InlineKeyboardButton("👦 Мальчик", callback_data="new_child:boy"),
    ]])
    lang = get_user_lang(user)
    await query.message.reply_text(t("profile.girl_or_boy", lang), reply_markup=keyboard)


async def handle_new_child_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: new_child:girl / new_child:boy → запросить имя."""
    query = update.callback_query
    await query.answer()

    gender = query.data.split(":")[1]  # "girl" or "boy"
    adding = context.user_data.get("adding_child", {})
    adding["gender"] = gender
    adding["step"] = "name"
    context.user_data["adding_child"] = adding

    name_word = "дочку" if gender == "girl" else "сына"
    await query.message.reply_text(f"Как зовут {name_word}? 👶\n(или «отмена»)")


async def _finish_add_child(message, user, context) -> None:
    """Создать Child в БД и обновить segment если нужно."""
    import sqlalchemy as sa
    from db.models.user import User as UserModel
    from db.models.child import Child
    from bot.handlers.onboarding import parse_birthdate

    adding = context.user_data.get("adding_child", {})
    gender = adding.get("gender", "girl")
    name = adding.get("name", "")
    birthdate = adding.get("birthdate")
    size = adding.get("size", "")
    shoe = adding.get("shoe")

    if not name or not birthdate:
        lang = get_user_lang(user)
        await message.reply_text(t("profile.child_error", lang))
        context.user_data.pop("adding_child", None)
        return

    try:
        async with AsyncWriteSession() as session:
            child = Child(
                user_id=user.id,
                name=name,
                gender=gender,
                birthdate=birthdate,
                current_size=size or None,
                shoe_size=shoe,
            )
            session.add(child)

            # Обновить segment только если no_kids → mom_girl/mom_boy
            if getattr(user, "segment", "no_kids") == "no_kids":
                new_segment = "mom_girl" if gender == "girl" else "mom_boy"
                await session.execute(
                    sa.update(UserModel)
                    .where(UserModel.id == user.id)
                    .values(segment=new_segment)
                )
                user.segment = new_segment

            await session.commit()

        gender_icon = "👧" if gender == "girl" else "👦"
        await message.reply_text(
            f"✅ {gender_icon} {name} добавлена в профиль!\n"
            "Теперь добавь её вещи — пришли фото одежды 📸"
        )
        logger.info("add_child.done", user_id=str(user.id), name=name, gender=gender)
    except Exception as e:
        lang = get_user_lang(user)
        await message.reply_text(t("profile.save_error", lang))
        logger.error("add_child.error", error=str(e))
        sentry_sdk.capture_exception(e)
    finally:
        context.user_data.pop("adding_child", None)


# ── Style preferences ────────────────────────────────────────────────────

_STYLE_OPTIONS = [
    ("casual", "🧢 Кэжуал"),
    ("smart_casual", "👔 Smart casual"),
    ("minimal", "⬜ Минимализм"),
    ("boho", "🌻 Бохо"),
    ("classic", "👗 Классика"),
    ("sporty", "🏃 Спортивный"),
]

_AVOID_COLORS = [
    ("яркие", "🚫 Яркие"),
    ("пастельные", "🚫 Пастельные"),
    ("чёрный", "🚫 Чёрный"),
    ("принты", "🚫 Принты"),
]


async def handle_edit_style_prefs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show style preference selection — step 1: choose style."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    keyboard = []
    row = []
    for code, label in _STYLE_OPTIONS:
        row.append(InlineKeyboardButton(label, callback_data=f"set_style:{code}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    await query.message.reply_text(
        "💅 Какой стиль тебе ближе?\n(это поможет подбирать образы точнее)",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_set_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Set style preference and ask about colors to avoid."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    style = query.data.split(":")[1]

    # Save style immediately
    import sqlalchemy as sa
    from db.models.user import User as UserModel
    prefs = getattr(user, "style_preferences", None) or {}
    prefs["style"] = style

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(UserModel).where(UserModel.id == user.id)
            .values(style_preferences=prefs)
        )
        await session.commit()
    user.style_preferences = prefs

    style_label = dict(_STYLE_OPTIONS).get(style, style)
    await query.message.reply_text(
        f"✅ Стиль: {style_label}\n\n"
        "Есть что-то, что ты НЕ любишь носить?\n"
        "(нажми «Готово» если всё ок)",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚫 Яркие цвета", callback_data="avoid_pref:яркие"),
                InlineKeyboardButton("🚫 Принты", callback_data="avoid_pref:принты"),
            ],
            [
                InlineKeyboardButton("🚫 Обтягивающее", callback_data="avoid_pref:обтягивающее"),
                InlineKeyboardButton("🚫 Оверсайз", callback_data="avoid_pref:оверсайз"),
            ],
            [InlineKeyboardButton("✅ Готово", callback_data="avoid_pref:done")],
        ]),
    )


async def handle_avoid_pref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add item to avoid list or finish."""
    query = update.callback_query
    await query.answer()

    user = context.user_data.get("db_user")
    if not user:
        return

    value = query.data.split(":")[1]

    if value == "done":
        prefs = getattr(user, "style_preferences", None) or {}
        avoid = prefs.get("avoid", [])
        if avoid:
            await query.message.reply_text(
                f"✅ Настройки сохранены!\nИзбегаем: {', '.join(avoid)}\n\n"
                "Теперь образы будут ещё точнее подобраны под тебя 🎯"
            )
        else:
            lang = get_user_lang(user)
            await query.message.reply_text(t("profile.prefs_saved", lang))
        return

    import sqlalchemy as sa
    from db.models.user import User as UserModel
    prefs = getattr(user, "style_preferences", None) or {}
    avoid = prefs.get("avoid", [])
    if value not in avoid:
        avoid.append(value)
    prefs["avoid"] = avoid

    async with AsyncWriteSession() as session:
        await session.execute(
            sa.update(UserModel).where(UserModel.id == user.id)
            .values(style_preferences=prefs)
        )
        await session.commit()
    user.style_preferences = prefs

    await query.answer(f"Добавлено: {value} 🚫")

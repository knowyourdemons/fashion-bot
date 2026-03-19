"""Profile handler + edit_city / edit_colortype / add_child flow."""
import time
import structlog
import sentry_sdk
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db.base import AsyncReadSession, AsyncWriteSession
from db.crud.children import get_children

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
        lines.append(f"👗 Подбираю для: {seg_label}")

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

    edit_buttons = [
        [InlineKeyboardButton("🏙 Изменить город", callback_data="edit_city")],
        [InlineKeyboardButton("🎨 Определить цветотип", callback_data="edit_colortype")],
        [InlineKeyboardButton("👶 Добавить ребёнка", callback_data="add_child_start")],
    ]
    markup = InlineKeyboardMarkup(edit_buttons)
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=markup)


async def handle_edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: edit_city → запросить новый город."""
    query = update.callback_query
    await query.answer()
    context.user_data["editing"] = "city"
    context.user_data["editing_ts"] = time.time()
    await query.message.reply_text("🏙 В каком городе живёте?\n\nНапиши название города (или «отмена»)")


async def handle_edit_colortype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: edit_colortype → ждать селфи для определения цветотипа."""
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_colortype_selfie"] = True
    await query.message.reply_text(
        "🎨 Пришли селфи при дневном свете ☀️\nОпределю твой цветотип по фото!"
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
    await query.message.reply_text("Девочка или мальчик? 🎀", reply_markup=keyboard)


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
    from db.models.children import Child
    from bot.handlers.onboarding import parse_birthdate

    adding = context.user_data.get("adding_child", {})
    gender = adding.get("gender", "girl")
    name = adding.get("name", "")
    birthdate = adding.get("birthdate")
    size = adding.get("size", "")

    if not name or not birthdate:
        await message.reply_text("Что-то пошло не так 🤔 Попробуй снова через /profile")
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
        await message.reply_text("Ошибка при сохранении 😔 Попробуй снова")
        logger.error("add_child.error", error=str(e))
        sentry_sdk.capture_exception(e)
    finally:
        context.user_data.pop("adding_child", None)

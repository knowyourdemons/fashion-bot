"""Profile handler."""
import structlog
from telegram import Update
from telegram.ext import ContextTypes

from db.base import AsyncReadSession
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

    lines = [f"⚙️ *Профиль*\n"]
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
            lines.append(f"\n👶 Дети:")
            for child in children:
                gender_icon = "👧" if child.gender == "girl" else "👦"
                parts = []
                if child.current_size:
                    parts.append(f"одежда {child.current_size}")
                if getattr(child, "shoe_size", None):
                    parts.append(f"обувь {child.shoe_size}")
                size_info = f" · {" · ".join(parts)}" if parts else ""
                lines.append(f"  {gender_icon} {child.name}{size_info}")
    except Exception as e:
        logger.error("profile.children.error", error=str(e))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

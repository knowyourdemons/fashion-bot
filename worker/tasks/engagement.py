"""Engagement push для trial-юзеров в ключевые дни (3/7/10/11)."""
import structlog
from datetime import date
from worker.slow_worker import register

logger = structlog.get_logger()

_ENGAGEMENT_SCHEDULE = {
    3: {
        "text": "Привет! 👋 У тебя уже {count} вещей в гардеробе. "
                "Добавь ещё — чем больше вещей, тем интереснее образы!\n\n"
                "📸 Просто пришли фото",
        "condition": "low_wardrobe",
    },
    7: {
        "text": "Неделя вместе! 🎉 Я собрала уже {brief_count} образов для {child_name}.\n\n"
                "Знаешь что? Попробуй спросить меня:\n"
                "💬 «Что надеть на день рождения?»\n"
                "💬 «Какой цвет подойдёт к розовой куртке?»",
        "condition": "always",
    },
    10: {
        "text": "Через 4 дня заканчивается Premium-доступ ⏰\n\n"
                "За это время ты получила:\n"
                "✨ {brief_count} образов\n"
                "💬 {chat_count} советов\n\n"
                "Всё это за $9/мес — дешевле одной чашки кофе ☕",
        "condition": "is_trial",
    },
    11: {
        "text": "Осталось 3 дня Premium! 😱\n\n"
                "После окончания:\n"
                "• Образы только вт/чт (сейчас каждый день)\n"
                "• Без переодеваний\n"
                "• 1 вопрос в день (сейчас 20)\n\n"
                "Сохранить все возможности?",
        "condition": "is_trial",
        "button": ("✨ Продолжить Premium", "show_upgrade"),
    },
}


@register("check_engagement")
async def check_engagement(payload: dict) -> dict:
    import uuid as _uuid
    from sqlalchemy import select, func
    from sqlalchemy.orm import selectinload
    from core.redis import get_redis
    from db.base import AsyncReadSession
    from db.models.user import User
    from db.models.brief_log import BriefLog
    from db.crud.children import get_children
    from db.crud.wardrobe import get_owner_items
    from core.permissions import is_trial_active
    from config import settings

    user_id = _uuid.UUID(payload["user_id"])

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User).options(selectinload(User.children))
            .where(User.id == user_id, User.deleted_at.is_(None))
        )
        user = result.scalar_one_or_none()

    if not user or not user.trial_started_at:
        return {}

    trial_day = (date.today() - user.trial_started_at.date()).days + 1

    if trial_day not in _ENGAGEMENT_SCHEDULE:
        return {}

    config = _ENGAGEMENT_SCHEDULE[trial_day]

    if config["condition"] == "is_trial" and not is_trial_active(user):
        return {}

    children = [c for c in (user.children or []) if c.deleted_at is None]
    child_name = children[0].name if children else "тебя"
    child = children[0] if children else None

    # Wardrobe count
    owner_id = child.id if child else user.id
    owner_type = "child" if child else "user"
    async with AsyncReadSession() as session:
        items = await get_owner_items(session, owner_id, owner_type)
    wardrobe_count = len(items)

    if config["condition"] == "low_wardrobe" and wardrobe_count >= 15:
        return {}

    # Brief count + chat count
    async with AsyncReadSession() as session:
        brief_count = await session.scalar(
            select(func.count(BriefLog.id)).where(BriefLog.user_id == user.id)
        ) or 0

    # Liked briefs count (только для trial report дня 11)
    liked_count = 0
    if trial_day == 11:
        async with AsyncReadSession() as session:
            from db.crud.brief_log import count_liked_briefs as _clb
            liked_count = await _clb(session, user.id)

    redis_client = get_redis()
    try:
        engagement_key = f"engagement:{user.id}:{date.today().isoformat()}"
        if await redis_client.exists(engagement_key):
            return {}
        await redis_client.set(engagement_key, "1", ex=86400)

        from config import settings as _settings
        from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
        bot = Bot(token=_settings.telegram_bot_token)

        # День 11 — подробный trial report
        if trial_day == 11:
            text = (
                f"📊 Твой отчёт за 11 дней с Касси:\n\n"
                f"👗 Образов собрано: {brief_count}\n"
                f"👍 Понравились: {liked_count}\n"
                f"📸 Вещей в гардеробе: {wardrobe_count}\n\n"
                f"Касси уже знает стиль {child_name} и подбирает всё точнее!\n\n"
                f"Через 3 дня Premium закончится.\n"
                f"Без него: образы только вт/чт, без переодеваний."
            )
            markup = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Продолжить Premium", callback_data="show_upgrade"),
                InlineKeyboardButton("📊 Сравнить планы", callback_data="compare_plans"),
            ]])
        else:
            chat_count = brief_count * 2  # приблизительно
            text = config["text"].format(
                count=wardrobe_count,
                child_name=child_name,
                brief_count=brief_count,
                chat_count=chat_count,
            )
            markup = None
            if "button" in config:
                label, callback = config["button"]
                markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=callback)]])

        await bot.send_message(chat_id=user.telegram_id, text=text, reply_markup=markup)
        logger.info("engagement.sent", user_id=str(user.id), trial_day=trial_day)
    except Exception as e:
        logger.warning("engagement.failed", user_id=str(user.id), error=str(e))
    except Exception as e:
        logger.warning("engagement.send_failed", user_id=str(user.id), error=str(e))

    return {}

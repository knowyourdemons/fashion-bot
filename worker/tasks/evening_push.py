"""Evening push — напоминание о завтрашнем брифе в 20:00 UTC."""
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


async def run() -> None:
    """Ежедневно в 20:00 UTC — пуш пользователям у которых завтра есть бриф."""
    from db.base import AsyncReadSession
    from db.models.user import User
    from sqlalchemy import select, orm
    from config import settings
    from telegram import Bot
    from core.permissions import get_effective_plan, is_brief_day_tomorrow

    bot = Bot(token=settings.telegram_bot_token)
    count = 0

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User)
            .options(orm.selectinload(User.children))
            .where(
                User.onboarding_completed.is_(True),
                User.deleted_at.is_(None),
                User.is_active.is_(True),
            )
        )
        users = list(result.scalars().all())

    for user in users:
        try:
            effective_plan = get_effective_plan(user)
            if not is_brief_day_tomorrow(effective_plan, user.timezone or "Europe/Vilnius"):
                continue

            children = [c for c in (user.children or []) if c.deleted_at is None]
            child_name = children[0].name if children else None

            if child_name:
                text = (
                    f"🌅 Завтра утром Касси подготовит образ для {child_name}!\n"
                    f"Добавь новые вещи сегодня вечером 📸"
                )
            else:
                text = (
                    f"🌅 Завтра утром Касси подготовит твой образ дня!\n"
                    f"Добавь новые вещи сегодня вечером 📸"
                )

            await bot.send_message(chat_id=user.telegram_id, text=text)
            logger.info("push.evening_sent", user_id=str(user.id))
            count += 1
        except Exception as e:
            logger.warning("push.evening_failed", user_id=str(user.id), error=str(e))

    logger.info("evening_push.run", sent=count)

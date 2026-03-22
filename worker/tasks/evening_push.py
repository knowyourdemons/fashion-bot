"""Evening push — напоминание о завтрашнем брифе. Timezone-aware: local 20:xx."""
import structlog
from datetime import datetime

import pytz

logger = structlog.get_logger()

_TARGET_HOUR = 20  # 20:00 по местному времени юзера


async def run() -> None:
    """Каждый час — пуш юзерам у которых сейчас 20:xx по их timezone."""
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
            # Timezone filter: only send when user's local time is 20:xx
            tz_name = user.timezone or "Europe/Vilnius"
            try:
                tz = pytz.timezone(tz_name)
                local_hour = datetime.now(tz).hour
            except Exception:
                local_hour = datetime.utcnow().hour + 2  # fallback EET
            if local_hour != _TARGET_HOUR:
                continue

            effective_plan = get_effective_plan(user)
            if not is_brief_day_tomorrow(effective_plan, tz_name):
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
            logger.info("push.evening_sent", user_id=str(user.id), tz=tz_name)
            count += 1
        except Exception as e:
            logger.warning("push.evening_failed", user_id=str(user.id), error=str(e))

    logger.info("evening_push.run", sent=count, hour=_TARGET_HOUR)

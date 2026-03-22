"""
Напоминания юзерам после 3/7/30 дней молчания.

Логика:
- 3 дня без активности: "Привет! Касси скучает — сфоткай новую вещь 📸"
- 7 дней: "Уже неделя! Гардероб ждёт обновлений 👗"
- 30 дней: "Давно не виделись! Покажи что нового 🌸"

Защита от спама: Redis lock `reminder_sent:{user_id}` (3 дня TTL).
"""
import structlog
from datetime import datetime, timedelta, timezone, date

from worker.slow_worker import register

logger = structlog.get_logger()

REMINDER_RULES = [
    (3, "Привет! 👋 Касси скучает — давно не присылала фото.\n"
        "Сфоткай новую вещь — соберу свежий образ! 📸"),
    (7, "Уже неделя! 👗 Гардероб ждёт обновлений.\n"
        "Добавь пару вещей — образы станут интереснее ✨"),
    (30, "Давно не виделись! 🌸 Покажи что нового в гардеробе.\n"
         "Даже 1-2 фото — и Касси подготовит образ 📸"),
]


async def run() -> None:
    """Cron: ежедневно 10:00 UTC. Находит неактивных, шлёт напоминания."""
    from sqlalchemy import select
    from db.base import AsyncReadSession
    from db.models.user import User
    from core.redis import get_redis
    from core.queue import RedisQueue, QueuePriority

    logger.info("reminders.run")
    redis = get_redis()
    now = datetime.now(timezone.utc)

    for days, text in REMINDER_RULES:
        cutoff = now - timedelta(days=days)
        # Next rule threshold — don't send 3-day reminder to 7-day inactive user
        next_cutoff = now - timedelta(days=days + 3)

        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                    User.updated_at <= cutoff,
                    User.updated_at > next_cutoff,
                )
            )
            users = result.scalars().all()

        queued = 0
        for user in users:
            # Dedup: don't send if already sent in last 3 days
            lock_key = f"reminder_sent:{user.id}"
            if await redis.exists(lock_key):
                continue

            queue = RedisQueue(redis)
            await queue.push(
                "send_reminder",
                {
                    "user_id": str(user.id),
                    "telegram_id": user.telegram_id,
                    "reminder_type": days,
                    "text": text,
                },
                priority=QueuePriority.LOW,
            )
            queued += 1

        logger.info("reminders.queued", days=days, count=queued)


@register("send_reminder")
async def handle_send_reminder(payload: dict) -> dict:
    """Send reminder via Telegram. Locks for 3 days to prevent spam."""
    from core.redis import get_redis
    from config import settings
    from telegram import Bot

    user_id = payload["user_id"]
    telegram_id = payload["telegram_id"]
    text = payload["text"]
    reminder_type = payload.get("reminder_type", 3)

    logger.info("reminders.send", user_id=user_id, reminder_type=reminder_type)

    try:
        bot = Bot(token=settings.telegram_bot_token)
        await bot.send_message(chat_id=telegram_id, text=text)

        # Lock: don't resend for 3 days
        redis = get_redis()
        await redis.set(f"reminder_sent:{user_id}", "1", ex=259200)  # 3 days

        logger.info("reminders.sent", user_id=user_id, days=reminder_type)
    except Exception as e:
        logger.warning("reminders.send_failed", user_id=user_id, error=str(e))

    return {"sent": True}

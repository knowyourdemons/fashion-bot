"""
Напоминания юзерам после 3/7/30 дней молчания.
"""
import structlog
from worker.slow_worker import register

logger = structlog.get_logger()

REMINDER_RULES = [(3, "reminder.3days"), (7, "reminder.7days"), (30, "reminder.30days")]


async def run() -> None:
    """Cron: ежедневно 10:00 UTC."""
    logger.info("reminders.run")
    # TODO: получить юзеров с last_active < now - N days
    # Не слать если уже слали за последние 3 дня
    # Пушить send_reminder в queue:low


@register("send_reminder")
async def handle_send_reminder(payload: dict) -> dict:
    user_id = payload["user_id"]
    reminder_type = payload.get("reminder_type", 3)
    logger.info("reminders.send", user_id=user_id, reminder_type=reminder_type)
    # TODO: отправить через Telegram
    return {"sent": True}

"""
Birthday alert — поздравление ребёнка + подсказка обновить размер.

Ежедневно в 08:00 UTC проверяет: у кого из детей сегодня день рождения?
Шлёт поздравление маме + напоминание обновить размер одежды/обуви.
"""
import structlog
from datetime import date

logger = structlog.get_logger()

_BIRTHDAY_MESSAGES = {
    1: "🎂 {name} исполнился 1 годик! Поздравляю! 🎈\n"
       "Малыш быстро растёт — проверь размер одежды в профиле 📏",
    2: "🎂 {name} исполнилось 2 годика! 🎈\n"
       "Скоро в садик — обнови гардероб! 📸",
    3: "🎂 {name} исполнилось 3 года! 🎈 Уже совсем большая!\n"
       "Проверь — может, пора обновить размер? 📏",
    "default": "🎂 С днём рождения, {name}! 🎈🎉\n"
               "Поздравляю! Проверь размер — дети быстро растут 📏",
}


async def run() -> None:
    """Cron: ежедневно 08:00 UTC. Проверяет дни рождения."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.base import AsyncReadSession
    from db.models.user import User
    from db.models.child import Child
    from core.redis import get_redis
    from config import settings
    from telegram import Bot

    logger.info("birthday_alert.run")
    today = date.today()

    async with AsyncReadSession() as session:
        result = await session.execute(
            select(Child).where(
                Child.deleted_at.is_(None),
                Child.birthdate.isnot(None),
            )
        )
        children = result.scalars().all()

    redis = get_redis()
    sent = 0

    for child in children:
        if child.birthdate.month != today.month or child.birthdate.day != today.day:
            continue

        # Dedup
        lock_key = f"birthday_sent:{child.id}:{today.isoformat()}"
        if await redis.exists(lock_key):
            continue

        age = (today - child.birthdate).days // 365
        msg_template = _BIRTHDAY_MESSAGES.get(age, _BIRTHDAY_MESSAGES["default"])
        text = msg_template.format(name=child.name)

        # Get parent
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(User.id == child.user_id, User.deleted_at.is_(None))
            )
            user = result.scalar_one_or_none()

        if not user:
            continue

        try:
            bot = Bot(token=settings.telegram_bot_token)
            await bot.send_message(chat_id=user.telegram_id, text=text)
            await redis.set(lock_key, "1", ex=86400)
            sent += 1
            logger.info("birthday_alert.sent", child=child.name, age=age, user_id=str(user.id))
        except Exception as e:
            logger.warning("birthday_alert.failed", child=child.name, error=str(e))

    logger.info("birthday_alert.done", sent=sent)

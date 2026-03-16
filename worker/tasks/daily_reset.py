"""Ежедневный сброс счётчика запросов."""
import structlog
from sqlalchemy import update, func

from db.base import AsyncWriteSession
from db.models.user import User

logger = structlog.get_logger()


async def reset_daily_limits() -> None:
    """Сбрасывает daily_requests_used=0 для всех пользователей раз в сутки."""
    async with AsyncWriteSession() as session:
        await session.execute(
            update(User).values(daily_requests_used=0, daily_requests_reset_at=func.now())
        )
        await session.commit()
    logger.info("daily_reset.done")

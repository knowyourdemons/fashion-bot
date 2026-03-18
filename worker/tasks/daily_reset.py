"""Ежедневный сброс счётчиков — запускается каждый час, фильтрует по timezone."""
import structlog
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import update, select, func

from db.base import AsyncWriteSession, AsyncReadSession
from db.models.user import User

logger = structlog.get_logger()


async def reset_daily_limits() -> None:
    """Сбрасывает daily_requests_used=0 для пользователей, у которых сейчас 00:00 по local timezone."""
    now_utc = datetime.now(timezone.utc)

    # Собираем все уникальные timezone из БД
    async with AsyncReadSession() as session:
        result = await session.execute(
            select(User.timezone).where(User.timezone.isnot(None)).distinct()
        )
        timezones = [row[0] for row in result.fetchall()]

    # Определяем, у каких timezone сейчас полночь (0:00–0:59)
    midnight_tzs: list[str] = []
    for tz_name in timezones:
        try:
            local_hour = now_utc.astimezone(ZoneInfo(tz_name)).hour
        except (ZoneInfoNotFoundError, Exception):
            continue
        if local_hour == 0:
            midnight_tzs.append(tz_name)

    if not midnight_tzs:
        return

    async with AsyncWriteSession() as session:
        await session.execute(
            update(User)
            .where(User.timezone.in_(midnight_tzs))
            .values(daily_requests_used=0, daily_requests_reset_at=func.now())
        )
        await session.commit()

    logger.info("daily_reset.done", timezones=midnight_tzs, count=len(midnight_tzs))

"""CRUD операции для BriefLog."""
import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.brief_log import BriefLog


async def create_log(session: AsyncSession, **kwargs) -> BriefLog:
    log = BriefLog(**kwargs)
    session.add(log)
    await session.flush()
    return log


async def get_log(session: AsyncSession, log_id: uuid.UUID) -> Optional[BriefLog]:
    result = await session.execute(
        select(BriefLog).where(BriefLog.id == log_id)
    )
    return result.scalar_one_or_none()


async def update_feedback(session: AsyncSession, log_id: uuid.UUID, feedback: str) -> None:
    await session.execute(
        update(BriefLog).where(BriefLog.id == log_id).values(feedback=feedback)
    )

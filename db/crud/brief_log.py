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


async def update_collage_file_id(session: AsyncSession, log_id: uuid.UUID, file_id: str) -> None:
    await session.execute(
        update(BriefLog).where(BriefLog.id == log_id).values(collage_file_id=file_id)
    )


async def count_user_briefs(session: AsyncSession, user_id: uuid.UUID) -> int:
    from sqlalchemy import func as _func
    from sqlalchemy import select as _sel
    return await session.scalar(
        _sel(_func.count(BriefLog.id)).where(BriefLog.user_id == user_id)
    ) or 0


async def count_liked_briefs(session: AsyncSession, user_id: uuid.UUID) -> int:
    from sqlalchemy import func as _func
    from sqlalchemy import select as _sel
    return await session.scalar(
        _sel(_func.count(BriefLog.id)).where(
            BriefLog.user_id == user_id,
            BriefLog.feedback == "up",
        )
    ) or 0

"""CRUD операции для Child."""
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.child import Child


async def create_child(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    name: str,
    birthdate: date,
    gender: str,
    current_size: Optional[str] = None,
    shoe_size: Optional[int] = None,
) -> Child:
    child = Child(
        user_id=user_id,
        name=name,
        birthdate=birthdate,
        gender=gender,
        current_size=current_size,
        shoe_size=shoe_size,
    )
    session.add(child)
    await session.flush()
    return child


async def get_children(session: AsyncSession, user_id: uuid.UUID) -> list[Child]:
    result = await session.execute(
        select(Child)
        .where(Child.user_id == user_id, Child.deleted_at.is_(None))
        .order_by(Child.created_at)
    )
    return list(result.scalars().all())

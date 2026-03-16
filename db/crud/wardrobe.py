"""CRUD операции для WardrobeItem."""
import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.wardrobe import WardrobeItem


async def get_owner_items(
    session: AsyncSession,
    owner_id: uuid.UUID,
    owner_type: str,
    include_deleted: bool = False,
) -> list[WardrobeItem]:
    q = select(WardrobeItem).where(
        WardrobeItem.owner_id == owner_id,
        WardrobeItem.owner_type == owner_type,
    )
    if not include_deleted:
        q = q.where(WardrobeItem.deleted_at == None)
    result = await session.execute(q)
    return list(result.scalars().all())


async def get_by_id(
    session: AsyncSession, item_id: uuid.UUID
) -> Optional[WardrobeItem]:
    result = await session.execute(
        select(WardrobeItem).where(
            WardrobeItem.id == item_id,
            WardrobeItem.deleted_at == None,
        )
    )
    return result.scalar_one_or_none()


async def create(session: AsyncSession, **kwargs) -> WardrobeItem:
    item = WardrobeItem(**kwargs)
    session.add(item)
    await session.flush()
    return item


async def increment_wear_count(
    session: AsyncSession, item_id: uuid.UUID, current_version: int
) -> bool:
    """Оптимистичная блокировка."""
    from datetime import date
    result = await session.execute(
        update(WardrobeItem)
        .where(
            WardrobeItem.id == item_id,
            WardrobeItem.version == current_version,
        )
        .values(
            wear_count=WardrobeItem.wear_count + 1,
            last_worn=date.today(),
            version=current_version + 1,
        )
        .returning(WardrobeItem.id)
    )
    return result.scalar_one_or_none() is not None


async def soft_delete(session: AsyncSession, item_id: uuid.UUID) -> None:
    from datetime import datetime
    await session.execute(
        update(WardrobeItem)
        .where(WardrobeItem.id == item_id)
        .values(deleted_at=datetime.utcnow())
    )

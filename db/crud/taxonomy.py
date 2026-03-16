"""CRUD для ItemCategory."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models.taxonomy import ItemCategory


async def get_all_active(session: AsyncSession) -> list[ItemCategory]:
    result = await session.execute(
        select(ItemCategory)
        .options(selectinload(ItemCategory.children))
        .where(ItemCategory.is_active == True, ItemCategory.parent_id == None)
        .order_by(ItemCategory.sort_order)
    )
    return list(result.scalars().all())


async def get_by_code(session: AsyncSession, code: str) -> ItemCategory | None:
    result = await session.execute(
        select(ItemCategory).where(ItemCategory.code == code, ItemCategory.is_active == True)
    )
    return result.scalar_one_or_none()

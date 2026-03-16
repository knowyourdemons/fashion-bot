"""CRUD для ScoringMatrix."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.scoring_matrix import ScoringMatrix


async def get_active_matrices(session: AsyncSession) -> list[ScoringMatrix]:
    result = await session.execute(
        select(ScoringMatrix).where(ScoringMatrix.is_active == True)
    )
    return list(result.scalars().all())

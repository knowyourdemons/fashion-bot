"""CRUD операции для User."""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models.user import User


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    result = await session.execute(
        select(User)
        .options(selectinload(User.children))
        .where(User.telegram_id == telegram_id, User.deleted_at == None)
    )
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    result = await session.execute(
        select(User)
        .options(selectinload(User.children))
        .where(User.id == user_id, User.deleted_at == None)
    )
    return result.scalar_one_or_none()


async def create(session: AsyncSession, telegram_id: int, name: str) -> User:
    user = User(telegram_id=telegram_id, name=name)
    session.add(user)
    await session.flush()
    return user


async def update_user_plan(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan: str,
    plan_expires_at: Optional[datetime],
    subscription_id: Optional[str],
    payment_provider: Optional[str],
) -> None:
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            plan=plan,
            plan_expires_at=plan_expires_at,
            subscription_id=subscription_id,
            payment_provider=payment_provider,
        )
    )


async def update_onboarding_step(
    session: AsyncSession,
    user_id: uuid.UUID,
    step: Optional[str],
    completed: bool = False,
) -> None:
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(onboarding_step=step, onboarding_completed=completed)
    )

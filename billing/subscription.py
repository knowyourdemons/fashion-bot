"""
Управление подписками: create/cancel/pause/resume.
"""
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from billing.base import PaymentProvider
from config import settings
from db.crud.users import update_user_plan
from db.models.user import User

logger = structlog.get_logger()


class SubscriptionService:
    def __init__(self, provider: PaymentProvider, session: AsyncSession) -> None:
        self._provider = provider
        self._session = session

    async def create(
        self,
        user: User,
        plan: str,
        period: str,
    ) -> dict[str, Any]:
        invoice = await self._provider.create_invoice(
            user_id=str(user.id),
            plan=plan,
            period=period,
        )
        logger.info(
            "subscription.created",
            user_id=str(user.id),
            plan=plan,
            period=period,
        )
        return invoice

    async def activate(
        self,
        user: User,
        plan: str,
        period: str,
        subscription_id: str | None = None,
        provider: str = "stars",
    ) -> None:
        days = 30 if period == "monthly" else 365
        expires_at = datetime.utcnow() + timedelta(days=days)

        await update_user_plan(
            session=self._session,
            user_id=user.id,
            plan=plan,
            plan_expires_at=expires_at,
            subscription_id=subscription_id,
            payment_provider=provider,
        )
        logger.info(
            "subscription.activated",
            user_id=str(user.id),
            plan=plan,
            expires_at=expires_at.isoformat(),
        )

    async def cancel(self, user: User) -> bool:
        if not user.subscription_id:
            return True

        result = await self._provider.cancel_subscription(user.subscription_id)
        if result:
            await update_user_plan(
                session=self._session,
                user_id=user.id,
                plan="free",
                plan_expires_at=None,
                subscription_id=None,
                payment_provider=None,
            )
            logger.info("subscription.cancelled", user_id=str(user.id))
        return result

    async def pause(self, user: User) -> bool:
        if not user.subscription_id:
            return False
        result = await self._provider.pause_subscription(user.subscription_id)
        if result:
            logger.info("subscription.paused", user_id=str(user.id))
        return result

    async def resume(self, user: User) -> bool:
        if not user.subscription_id:
            return False
        result = await self._provider.resume_subscription(user.subscription_id)
        if result:
            logger.info("subscription.resumed", user_id=str(user.id))
        return result

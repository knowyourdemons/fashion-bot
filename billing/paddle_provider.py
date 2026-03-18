"""
Paddle payment provider — STUB.
Paddle — Merchant of Record, комиссия 5%+$0.50.
Подходит для международных платежей без своего юрлица.
Подключается через settings.payment_provider = "paddle".
Документация: https://developer.paddle.com/
"""
from typing import Any

import structlog

from billing.base import PaymentProvider

logger = structlog.get_logger()


class PaddleProvider(PaymentProvider):
    """Заглушка Paddle. Активировать при необходимости Merchant of Record."""

    async def create_invoice(
        self,
        user_id: str,
        plan: str,
        period: str,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "Paddle не подключен — см. https://developer.paddle.com/"
        )

    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        raise NotImplementedError("Paddle не подключен")

    async def cancel_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("Paddle не подключен")

    async def pause_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("Paddle не подключен")

    async def resume_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("Paddle не подключен")

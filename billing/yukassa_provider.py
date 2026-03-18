"""
ЮKassa payment provider — STUB.
Требует российское/белорусское юрлицо и provider_token от BotFather.
Подключается через settings.payment_provider = "yukassa".
"""
from typing import Any

import structlog

from billing.base import PaymentProvider

logger = structlog.get_logger()


class YuKassaProvider(PaymentProvider):
    """Заглушка ЮKassa. Активировать когда будет юрлицо и provider_token."""

    async def create_invoice(
        self,
        user_id: str,
        plan: str,
        period: str,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "ЮKassa не подключена — нужен provider_token от BotFather и юрлицо"
        )

    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        raise NotImplementedError("ЮKassa не подключена")

    async def cancel_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("ЮKassa не подключена")

    async def pause_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("ЮKassa не подключена")

    async def resume_subscription(self, subscription_id: str) -> bool:
        raise NotImplementedError("ЮKassa не подключена")

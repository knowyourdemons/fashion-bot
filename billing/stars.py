"""
Telegram Stars payment provider.
Stars не поддерживают подписки — только разовые платежи.
"""
from typing import Any

import structlog

from billing.base import PaymentProvider

logger = structlog.get_logger()

# plan_key → кол-во Stars
PLAN_PRICES_STARS: dict[str, int] = {
    "premium_monthly":   700,
    "premium_quarterly": 1700,
    "premium_yearly":    5500,
}


class StarsProvider(PaymentProvider):
    async def create_invoice(
        self,
        user_id: str,
        plan_key: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        from core.permissions import PRICES
        amount = PLAN_PRICES_STARS.get(plan_key)
        if not amount:
            raise ValueError(f"Неизвестный plan_key: {plan_key}")

        price = PRICES.get(plan_key, {})
        label = price.get("label", plan_key)

        return {
            "type": "stars_invoice",
            "title": "Касси Premium",
            "description": label,
            "payload": f"premium:{plan_key}:{user_id}",
            "currency": "XTR",
            "prices": [{"label": "Premium", "amount": amount}],
            "provider_token": "",  # пустой для Stars
        }

    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        # Telegram сам верифицирует Stars — проверяем только наличие события
        return "successful_payment" in payload

    async def cancel_subscription(self, subscription_id: str) -> bool:
        logger.info("stars.cancel_subscription", subscription_id=subscription_id)
        return True

    async def pause_subscription(self, subscription_id: str) -> bool:
        logger.info("stars.pause_subscription", subscription_id=subscription_id)
        return True

    async def resume_subscription(self, subscription_id: str) -> bool:
        logger.info("stars.resume_subscription", subscription_id=subscription_id)
        return True

"""
Telegram Stars payment provider.
Stars не поддерживают подписки — только разовые платежи.
"""
from typing import Any

import structlog

from billing.base import PaymentProvider
from config import settings

logger = structlog.get_logger()

# Курс: 1 XTR = $0.013 (приблизительно)
PLAN_PRICES_STARS: dict[str, dict[str, int]] = {
    "basic": {"monthly": 385, "annual": 3692},    # ~$5 / ~$48
    "family": {"monthly": 923, "annual": 8846},   # ~$12 / ~$115
    "premium": {"monthly": 1462, "annual": 14000}, # ~$19 / ~$182
}


class StarsProvider(PaymentProvider):
    async def create_invoice(
        self,
        user_id: str,
        plan: str,
        period: str,
    ) -> dict[str, Any]:
        prices = PLAN_PRICES_STARS.get(plan, {})
        amount = prices.get(period, 0)
        if not amount:
            raise ValueError(f"Неизвестный план/период: {plan}/{period}")

        period_label = "месяц" if period == "monthly" else "год"
        return {
            "type": "stars_invoice",
            "title": f"Fashion Bot {plan.capitalize()} — {period_label}",
            "description": f"Подписка на {period_label}",
            "payload": f"sub:{plan}:{period}:{user_id}",
            "currency": "XTR",
            "prices": [{"label": f"Подписка {plan}", "amount": amount}],
            "provider_token": settings.telegram_payment_token,
        }

    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        # Telegram сам верифицирует Stars — проверяем только payload формат
        return "successful_payment" in payload

    async def cancel_subscription(self, subscription_id: str) -> bool:
        # Stars не поддерживают отмену через API
        logger.info("stars.cancel_subscription", subscription_id=subscription_id)
        return True

    async def pause_subscription(self, subscription_id: str) -> bool:
        logger.info("stars.pause_subscription", subscription_id=subscription_id)
        return True

    async def resume_subscription(self, subscription_id: str) -> bool:
        logger.info("stars.resume_subscription", subscription_id=subscription_id)
        return True

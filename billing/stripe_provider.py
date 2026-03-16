"""
Stripe payment provider.
Поддерживает recurring подписки.
"""
from typing import Any

import httpx
import structlog

from billing.base import PaymentProvider
from config import settings

logger = structlog.get_logger()

PLAN_PRICES_USD: dict[str, dict[str, int]] = {
    "basic": {"monthly": 500, "annual": 4800},      # в центах
    "family": {"monthly": 1200, "annual": 11500},
    "premium": {"monthly": 1900, "annual": 18200},
}

STRIPE_API = "https://api.stripe.com/v1"


class StripeProvider(PaymentProvider):
    def __init__(self) -> None:
        self._secret = settings.stripe_secret_key
        self._webhook_secret = settings.stripe_webhook_secret

    async def create_invoice(
        self,
        user_id: str,
        plan: str,
        period: str,
    ) -> dict[str, Any]:
        prices = PLAN_PRICES_USD.get(plan, {})
        amount = prices.get(period, 0)
        if not amount:
            raise ValueError(f"Неизвестный план/период: {plan}/{period}")

        interval = "month" if period == "monthly" else "year"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{STRIPE_API}/checkout/sessions",
                auth=(self._secret, ""),
                data={
                    "mode": "subscription",
                    "success_url": "https://fashionbot.app/success",
                    "cancel_url": "https://fashionbot.app/cancel",
                    "metadata[user_id]": user_id,
                    "metadata[plan]": plan,
                    "metadata[period]": period,
                    "line_items[0][price_data][currency]": "usd",
                    "line_items[0][price_data][product_data][name]": f"Fashion Bot {plan}",
                    "line_items[0][price_data][unit_amount]": str(amount),
                    "line_items[0][price_data][recurring][interval]": interval,
                    "line_items[0][quantity]": "1",
                },
            )
            resp.raise_for_status()
            session = resp.json()

        return {"type": "stripe_checkout", "url": session["url"], "session_id": session["id"]}

    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        import hmac, hashlib
        sig_header = payload.get("stripe_signature", "")
        body = payload.get("body", "")
        try:
            parts = {p.split("=")[0]: p.split("=")[1] for p in sig_header.split(",")}
            ts = parts["t"]
            expected = hmac.new(
                self._webhook_secret.encode(),
                f"{ts}.{body}".encode(),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, parts.get("v1", ""))
        except Exception:
            return False

    async def cancel_subscription(self, subscription_id: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{STRIPE_API}/subscriptions/{subscription_id}",
                auth=(self._secret, ""),
            )
            return resp.status_code == 200

    async def pause_subscription(self, subscription_id: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{STRIPE_API}/subscriptions/{subscription_id}",
                auth=(self._secret, ""),
                data={"pause_collection[behavior]": "void"},
            )
            return resp.status_code == 200

    async def resume_subscription(self, subscription_id: str) -> bool:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{STRIPE_API}/subscriptions/{subscription_id}",
                auth=(self._secret, ""),
                data={"pause_collection": ""},
            )
            return resp.status_code == 200

"""
Stripe payment provider.
Поддерживает разовые платежи и подписки.
"""
import hmac
import hashlib
from typing import Any

import httpx
import structlog

from billing.base import PaymentProvider
from config import settings

logger = structlog.get_logger()

# period key → (Stripe interval, interval_count)
_PERIOD_TO_INTERVAL = {
    "monthly":   ("month", 1),
    "quarterly": ("month", 3),
    "yearly":    ("year",  1),
}

# plan_key → period (для handle_pay_stripe который передаёт plan_key напрямую)
_PLAN_KEY_TO_PERIOD = {
    "premium_monthly":   "monthly",
    "premium_quarterly": "quarterly",
    "premium_yearly":    "yearly",
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
        from core.permissions import PRICES

        # period может быть "monthly"/"quarterly"/"yearly" ИЛИ plan_key ("premium_monthly")
        if period in _PLAN_KEY_TO_PERIOD:
            period = _PLAN_KEY_TO_PERIOD[period]

        plan_key = f"{plan}_{period}" if not period.startswith(plan) else period
        # Нормализация: "premium_monthly" → ищем в PRICES
        if plan_key not in PRICES:
            plan_key = f"premium_{period}"

        price = PRICES.get(plan_key)
        if not price:
            raise ValueError(f"Неизвестный план/период: {plan}/{period}")

        amount_cents = price["usd"]  # уже в центах
        label = price.get("label_usd", price.get("label", "Premium"))

        interval, interval_count = _PERIOD_TO_INTERVAL.get(period, ("month", 1))

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{STRIPE_API}/checkout/sessions",
                auth=(self._secret, ""),
                data={
                    "mode": "subscription",
                    "success_url": "https://fashioncastle.app/success",
                    "cancel_url": "https://fashioncastle.app/cancel",
                    "metadata[user_id]": user_id,
                    "metadata[plan_key]": plan_key,
                    "line_items[0][price_data][currency]": "usd",
                    "line_items[0][price_data][product_data][name]": f"Касси Premium — {label}",
                    "line_items[0][price_data][unit_amount]": str(amount_cents),
                    "line_items[0][price_data][recurring][interval]": interval,
                    "line_items[0][price_data][recurring][interval_count]": str(interval_count),
                    "line_items[0][quantity]": "1",
                },
            )
            resp.raise_for_status()
            session = resp.json()

        return {"type": "stripe_checkout", "url": session["url"], "session_id": session["id"]}

    async def verify_payment(self, payload: dict[str, Any]) -> bool:
        sig_header = payload.get("stripe_signature", "")
        body = payload.get("body", b"")
        if isinstance(body, str):
            body = body.encode()
        try:
            parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in sig_header.split(",") if "=" in p}
            ts = parts.get("t", "")
            signed_payload = f"{ts}.".encode() + body
            expected = hmac.new(
                self._webhook_secret.encode(),
                signed_payload,
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

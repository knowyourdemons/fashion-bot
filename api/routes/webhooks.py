from datetime import datetime, timedelta, timezone

import hmac
import hashlib
import json

from fastapi import APIRouter, Request, HTTPException
from telegram import Update
import structlog

from config import settings

router = APIRouter()
logger = structlog.get_logger()


async def _activate_premium_after_payment(
    telegram_user_id: int,
    plan: str,
    period: str,
    subscription_id: str | None,
    provider: str,
) -> None:
    """Активирует premium/ultra в БД после успешного платежа."""
    from db.base import AsyncWriteSession
    from db.crud.users import get_by_telegram_id, update_user_plan

    period_months = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(period, 1)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30 * period_months)

    async with AsyncWriteSession() as session:
        user = await get_by_telegram_id(session, telegram_user_id)
        if not user:
            logger.warning(
                "webhook.user_not_found",
                telegram_user_id=telegram_user_id,
                provider=provider,
            )
            return
        await update_user_plan(
            session=session,
            user_id=user.id,
            plan=plan,
            plan_expires_at=expires_at,
            subscription_id=subscription_id,
            payment_provider=provider,
        )
    logger.info(
        "webhook.premium_activated",
        telegram_user_id=telegram_user_id,
        plan=plan,
        period=period,
        expires_at=expires_at.isoformat(),
        provider=provider,
    )


@router.post("/stripe")
async def stripe_webhook(request: Request) -> dict:
    """Stripe webhook: checkout.session.completed → activate premium."""
    body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify signature
    if settings.stripe_webhook_secret:
        try:
            parts = {p.split("=")[0]: p.split("=")[1] for p in sig_header.split(",")}
            ts = parts["t"]
            expected = hmac.new(
                settings.stripe_webhook_secret.encode(),
                f"{ts}.{body.decode()}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, parts.get("v1", "")):
                raise HTTPException(status_code=400, detail="Invalid signature")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("stripe_webhook.signature_error", error=str(e))
            raise HTTPException(status_code=400, detail="Signature error")

    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = event.get("type")
    logger.info("stripe_webhook.received", event_type=event_type)

    if event_type == "checkout.session.completed":
        session_obj = event.get("data", {}).get("object", {})
        metadata = session_obj.get("metadata", {})
        # StripeProvider stores telegram_id under "user_id" key
        telegram_user_id = metadata.get("telegram_user_id") or metadata.get("user_id")
        plan = metadata.get("plan", "premium")
        period = metadata.get("period", "monthly")
        subscription_id = session_obj.get("subscription")

        if telegram_user_id:
            try:
                await _activate_premium_after_payment(
                    telegram_user_id=int(telegram_user_id),
                    plan=plan,
                    period=period,
                    subscription_id=subscription_id,
                    provider="stripe",
                )
            except Exception as e:
                logger.error("stripe_webhook.activation_error", error=str(e))

    return {"ok": True}


@router.post("/telegram")
async def telegram_webhook(request: Request) -> dict:
    tg_app = request.app.state.tg_app
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

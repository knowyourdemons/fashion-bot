""/api/v1/webhooks/stripe|telegram"""
from fastapi import APIRouter, Request
router = APIRouter()

@router.post("/stripe")
async def stripe_webhook(request: Request):
    # TODO: verify signature, process event
    return {"ok": True}

@router.post("/telegram")
async def telegram_webhook(request: Request):
    # TODO: process Telegram update
    return {"ok": True}

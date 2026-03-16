from fastapi import APIRouter, Request, HTTPException
from telegram import Update
import structlog

router = APIRouter()
logger = structlog.get_logger()

@router.post("/stripe")
async def stripe_webhook(request: Request):
    # TODO: verify signature, process event
    return {"ok": True}

@router.post("/telegram")
async def telegram_webhook(request: Request):
    tg_app = request.app.state.tg_app
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return {"ok": True}

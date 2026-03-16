"""POST /api/v1/auth/telegram"""
from fastapi import APIRouter
router = APIRouter()

@router.post("/telegram")
async def auth_telegram():
    # TODO: verify Telegram initData, issue JWT
    return {"token": "TODO"}

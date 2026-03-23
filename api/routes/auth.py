from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/telegram")
async def auth_telegram():
    """Telegram auth — not implemented yet. Returns 501."""
    raise HTTPException(status_code=501, detail="Auth not implemented. Use Telegram bot directly.")

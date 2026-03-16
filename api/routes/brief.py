"""GET/POST /api/v1/brief"""
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def get_brief():
    return {}

@router.post("/feedback")
async def brief_feedback():
    return {}

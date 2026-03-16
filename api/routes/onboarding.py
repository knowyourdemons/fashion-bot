"""/api/v1/onboarding"""
from fastapi import APIRouter
router = APIRouter()

@router.post("/")
async def onboarding_step():
    return {}

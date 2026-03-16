""/api/v1/billing"""
from fastapi import APIRouter
router = APIRouter()

@router.post("/subscribe")
async def subscribe():
    return {}

@router.post("/cancel")
async def cancel():
    return {}

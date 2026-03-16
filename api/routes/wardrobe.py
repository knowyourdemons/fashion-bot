"""CRUD /api/v1/wardrobe"""
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def list_items():
    return []

@router.post("/")
async def add_item():
    return {}

@router.delete("/{item_id}")
async def delete_item(item_id: str):
    return {"deleted": item_id}

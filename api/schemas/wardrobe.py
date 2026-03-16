"""Wardrobe schemas."""
from pydantic import BaseModel

class WardrobeItemOut(BaseModel):
    id: str
    category_code: str
    color: str
    type: str

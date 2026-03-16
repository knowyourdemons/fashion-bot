"""User schemas."""
from pydantic import BaseModel

class UserOut(BaseModel):
    id: str
    name: str
    plan: str
    segment: str | None = None

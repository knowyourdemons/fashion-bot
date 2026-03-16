"""Brief schemas."""
from pydantic import BaseModel

class BriefOut(BaseModel):
    date: str
    outfit: str
    score: str | None = None
    is_wow: bool = False

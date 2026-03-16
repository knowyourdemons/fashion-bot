import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class BriefLog(Base):
    __tablename__ = "brief_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    weather_summary: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    outfit_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outfit_items: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    score: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(
        String(8), nullable=True
    )  # "up" / "down"
    is_wow: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ScoringMatrix(Base):
    __tablename__ = "scoring_matrices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    age_from: Mapped[int] = mapped_column(Integer, nullable=False)
    age_to: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(
        Enum("boy", "girl", "all", name="matrix_gender_enum"), nullable=False
    )
    is_pregnant: Mapped[bool] = mapped_column(Boolean, default=False)
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="v1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

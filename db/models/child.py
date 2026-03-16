import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User
    from db.models.wardrobe import WardrobeItem


class Child(Base):
    __tablename__ = "children"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    birthdate: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str] = mapped_column(
        Enum("boy", "girl", name="gender_enum"), nullable=False
    )
    colortype: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    shoe_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_size: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Soft delete
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="children")
    wardrobe_items: Mapped[list["WardrobeItem"]] = relationship(
        "WardrobeItem",
        primaryjoin="and_(Child.id == WardrobeItem.owner_id, WardrobeItem.owner_type == 'child')",
        foreign_keys="WardrobeItem.owner_id",
        lazy="noload",
    )

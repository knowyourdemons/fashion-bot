import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class ItemCategory(Base):
    """Дерево категорий одежды (taxonomy)."""

    __tablename__ = "item_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    group: Mapped[str] = mapped_column(String(64), nullable=False)
    label_ru: Mapped[str] = mapped_column(String(255), nullable=False)
    label_en: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("item_categories.id"), nullable=True
    )
    level: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    children: Mapped[list["ItemCategory"]] = relationship(
        "ItemCategory", back_populates="parent", lazy="noload"
    )
    parent: Mapped[Optional["ItemCategory"]] = relationship(
        "ItemCategory", back_populates="children", remote_side="ItemCategory.id"
    )


class TaxonomyVersion(Base):
    """Версионирование справочника таксономии."""

    __tablename__ = "taxonomy_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UnknownItem(Base):
    """Вещи, которые Claude не смог классифицировать."""

    __tablename__ = "unknown_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    wardrobe_item_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wardrobe_items.id", ondelete="SET NULL"), nullable=True
    )
    user_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    photo_id: Mapped[str] = mapped_column(String(512), nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_code: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    ARRAY, Boolean, Date, DateTime, Enum, Integer, Numeric, String, Text, func
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WardrobeItem(Base):
    __tablename__ = "wardrobe_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Владелец (user или child)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    owner_type: Mapped[str] = mapped_column(
        Enum("user", "child", name="owner_type_enum"), nullable=False
    )

    # Категория
    category_group: Mapped[str] = mapped_column(
        Enum(
            "outerwear", "top", "bottom", "one_piece", "footwear",
            "accessory", "base_layer", "sportswear", "special",
            "home_beach", "pregnant_specific",
            name="category_group_enum",
        ),
        nullable=False,
    )
    category_code: Mapped[str] = mapped_column(String(128), nullable=False)
    is_unknown_category: Mapped[bool] = mapped_column(Boolean, default=False)
    user_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Описание
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(String(128), nullable=False)
    style: Mapped[str] = mapped_column(String(128), nullable=False)
    brand: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    season: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    occasion: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # Медиа
    photo_id: Mapped[str] = mapped_column(String(512), nullable=False)
    photo_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    photo_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Размеры
    size_fit: Mapped[Optional[str]] = mapped_column(
        Enum("маловата", "впору", "великовата", name="size_fit_enum"), nullable=True
    )
    size_actual: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    size_recommended: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # Состояние
    condition: Mapped[str] = mapped_column(
        Enum("новая", "хорошая", "ношеная", "на_выброс", name="condition_enum"),
        nullable=False,
        default="хорошая",
    )
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    wear_count: Mapped[int] = mapped_column(Integer, default=0)
    last_worn: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Скоринг
    score_item: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2), nullable=True)
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    score_version: Mapped[str] = mapped_column(String(16), default="v1.0")
    score_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Флаги
    is_base_layer: Mapped[bool] = mapped_column(Boolean, default=False)
    show_in_collage: Mapped[bool] = mapped_column(Boolean, default=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    keep: Mapped[bool] = mapped_column(Boolean, default=True)
    wishlist: Mapped[bool] = mapped_column(Boolean, default=False)

    # Оптимистичная блокировка
    version: Mapped[int] = mapped_column(Integer, default=0)

    # Soft delete
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

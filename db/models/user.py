import uuid
from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.child import Child
    from db.models.wardrobe import WardrobeItem


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Vilnius")

    plan: Mapped[str] = mapped_column(
        Enum("free", "basic", "family", "premium", name="plan_enum"),
        default="free",
    )
    segment: Mapped[Optional[str]] = mapped_column(
        Enum("mom_girl", "mom_boy", "pregnant", "no_kids", name="segment_enum"),
        nullable=True,
    )
    body_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trimester: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1/2/3 for pregnant
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # ПДР для беременных
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Stripe
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    plan_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_paused_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_provider: Mapped[Optional[str]] = mapped_column(
        Enum("stars", "stripe", "paddle", name="payment_provider_enum"),
        nullable=True,
    )

    # Referrals
    referral_code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, default=lambda: uuid.uuid4().hex[:8].upper()
    )
    referred_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Limits
    daily_requests_used: Mapped[int] = mapped_column(Integer, default=0)
    daily_requests_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Onboarding
    onboarding_step: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    colortype: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Style preferences: {"avoid": ["юбки", "каблуки"], "prefer": ["минимализм"],
    #   "style": "casual", "work_days": 5}
    style_preferences: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    milestones_reached: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)

    # Soft delete
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    children: Mapped[list["Child"]] = relationship(
        "Child", back_populates="user", lazy="noload"
    )
    wardrobe_items: Mapped[list["WardrobeItem"]] = relationship(
        "WardrobeItem",
        primaryjoin="and_(User.id == WardrobeItem.owner_id, WardrobeItem.owner_type == 'user')",
        foreign_keys="WardrobeItem.owner_id",
        lazy="noload",
    )

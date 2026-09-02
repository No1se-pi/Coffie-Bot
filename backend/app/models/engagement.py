"""Public reviews, reusable passes, and explainable bulk bonus batches."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import BulkBonusStatus, PassStatus, PaymentMethod, ReviewStatus


class PublicReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Customer-authored review; only approved rows are publicly visible."""

    __tablename__ = "public_reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_between_1_and_5"),
        UniqueConstraint("user_id", "order_id", name="user_order_review"),
        Index("ix_public_reviews_public", "status", "created_at"),
        Index("ix_public_reviews_user_created", "user_id", "created_at"),
        Index("ix_public_reviews_venue_created", "venue_id", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    order_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="RESTRICT")
    )
    venue_id: Mapped[UUID] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"))
    employee_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, name="public_review_status", length=16),
        nullable=False,
        default=ReviewStatus.PENDING,
        server_default=ReviewStatus.PENDING.value,
    )
    moderation_note: Mapped[str | None] = mapped_column(Text)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderated_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )


class PassTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pass definition and its optional pay-at-location storefront offer."""

    __tablename__ = "pass_templates"
    __table_args__ = (
        CheckConstraint("total_uses > 0", name="positive_total_uses"),
        CheckConstraint("validity_days > 0", name="positive_validity_days"),
        CheckConstraint("price_minor >= 0", name="non_negative_price"),
        Index("ix_pass_templates_active_created", "is_active", "created_at"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    total_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    purchase_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )


class PassTemplateVenue(Base):
    __tablename__ = "pass_template_venues"
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("pass_templates.id", ondelete="RESTRICT"), primary_key=True
    )
    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), primary_key=True
    )


class PassTemplateCategory(Base):
    __tablename__ = "pass_template_categories"
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("pass_templates.id", ondelete="RESTRICT"), primary_key=True
    )
    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="RESTRICT"), primary_key=True
    )


class PassTemplateItem(Base):
    __tablename__ = "pass_template_items"
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("pass_templates.id", ondelete="RESTRICT"), primary_key=True
    )
    item_id: Mapped[UUID] = mapped_column(
        ForeignKey("menu_items.id", ondelete="RESTRICT"), primary_key=True
    )


class CustomerPass(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Issued pass with name/limits snapshotted from its immutable template."""

    __tablename__ = "customer_passes"
    __table_args__ = (
        CheckConstraint(
            "total_uses > 0 AND remaining_uses >= 0 AND remaining_uses <= total_uses",
            name="valid_use_balance",
        ),
        CheckConstraint("expires_at > issued_at", name="expiration_after_issue"),
        UniqueConstraint("issued_by_staff_id", "idempotency_key", name="staff_pass_issue_key"),
        UniqueConstraint(
            "cancelled_by_staff_id",
            "cancellation_idempotency_key",
            name="staff_pass_cancel_key",
        ),
        Index("ix_customer_passes_user_status", "user_id", "status", "expires_at"),
    )

    template_id: Mapped[UUID] = mapped_column(ForeignKey("pass_templates.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    description_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    image_media_id_snapshot: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    total_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PassStatus] = mapped_column(
        enum_type(PassStatus, name="customer_pass_status", length=16),
        nullable=False,
        default=PassStatus.ACTIVE,
        server_default=PassStatus.ACTIVE.value,
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancellation_idempotency_key: Mapped[str | None] = mapped_column(String(128))
    cancellation_request_hash: Mapped[str | None] = mapped_column(String(64))


class PassPurchase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pay-at-location pass order; activation requires a staff confirmation."""

    __tablename__ = "pass_purchases"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="user_pass_purchase_key"),
        CheckConstraint("price_minor >= 0", name="non_negative_price"),
        CheckConstraint(
            "status IN ('pending', 'paid', 'cancelled')",
            name="valid_status",
        ),
        Index("ix_pass_purchases_status_created", "status", "created_at"),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("pass_templates.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        enum_type(PaymentMethod, name="pass_purchase_payment_method", length=24), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_pass_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customer_passes.id", ondelete="RESTRICT"), unique=True
    )
    confirmed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PassUsage(UUIDPrimaryKeyMixin, Base):
    """Append-only proof of one successful pass redemption."""

    __tablename__ = "pass_usages"
    __table_args__ = (
        CheckConstraint("uses_before > uses_after AND uses_after >= 0", name="decrements_once"),
        UniqueConstraint("actor_staff_id", "idempotency_key", name="staff_pass_usage_key"),
        Index("ix_pass_usages_pass_created", "pass_id", "created_at"),
    )

    pass_id: Mapped[UUID] = mapped_column(ForeignKey("customer_passes.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    venue_id: Mapped[UUID] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"))
    item_id: Mapped[UUID] = mapped_column(ForeignKey("menu_items.id", ondelete="RESTRICT"))
    uses_before: Mapped[int] = mapped_column(Integer, nullable=False)
    uses_after: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BulkBonusBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One immutable confirmed bulk command and its audience snapshot."""

    __tablename__ = "bulk_bonus_batches"
    __table_args__ = (
        CheckConstraint("points_per_user > 0", name="positive_points_per_user"),
        CheckConstraint("recipient_count > 0", name="positive_recipient_count"),
        CheckConstraint("total_points = points_per_user * recipient_count", name="valid_total"),
        UniqueConstraint("created_by_staff_id", "idempotency_key", name="staff_bulk_bonus_key"),
    )

    status: Mapped[BulkBonusStatus] = mapped_column(
        enum_type(BulkBonusStatus, name="bulk_bonus_status", length=16), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    points_per_user: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    venue_id: Mapped[UUID | None] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"))
    audience_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )


class BulkBonusItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bulk_bonus_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "user_id", name="batch_user"),
        UniqueConstraint("operation_id", name="operation"),
    )

    batch_id: Mapped[UUID] = mapped_column(ForeignKey("bulk_bonus_batches.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT")
    )
    points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

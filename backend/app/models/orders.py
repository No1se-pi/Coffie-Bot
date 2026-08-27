"""Order aggregate, immutable price snapshots, and delivery configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
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
from app.models.enums import (
    FulfillmentMode,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)


class DeliverySettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Organization-level pickup/delivery policy for one deployment."""

    __tablename__ = "delivery_settings"
    __table_args__ = (
        CheckConstraint("minimum_order_minor >= 0", name="non_negative_minimum_order"),
        CheckConstraint("fixed_fee_minor >= 0", name="non_negative_fixed_fee"),
        CheckConstraint(
            "free_delivery_threshold_minor IS NULL OR free_delivery_threshold_minor >= 0",
            name="non_negative_free_delivery_threshold",
        ),
        CheckConstraint(
            "earliest_preparation_minutes >= 0",
            name="non_negative_earliest_preparation",
        ),
    )

    singleton_key: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, default="default", server_default="default"
    )
    delivery_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    minimum_order_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    fixed_fee_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    free_delivery_threshold_minor: Mapped[int | None] = mapped_column(BigInteger)
    scheduling_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    earliest_preparation_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    operating_hours: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    default_pickup_location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    consolidation_location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL")
    )
    updated_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )


class DeliveryZone(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Simple admin-selected delivery zone; no fake GIS matching is implied."""

    __tablename__ = "delivery_zones"
    __table_args__ = (
        CheckConstraint("fee_minor >= 0", name="non_negative_fee"),
        CheckConstraint(
            "minimum_order_minor IS NULL OR minimum_order_minor >= 0",
            name="non_negative_minimum_order",
        ),
        Index("ix_delivery_zones_active_sort", "is_active", "sort_order"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    minimum_order_minor: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One customer-visible order that may contain several venue suborders."""

    __tablename__ = "customer_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="user_order_idempotency"),
        CheckConstraint(
            "subtotal_minor >= 0 AND promotion_discount_minor >= 0 "
            "AND points_discount_minor >= 0 AND delivery_fee_minor >= 0 "
            "AND total_minor >= 0",
            name="non_negative_amounts",
        ),
        CheckConstraint("status_version >= 1", name="positive_status_version"),
        Index("ix_customer_orders_user_created", "user_id", "created_at"),
        Index("ix_customer_orders_status_created", "status", "created_at"),
        Index("ix_customer_orders_courier_status", "assigned_courier_staff_id", "status"),
    )

    number: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    fulfillment_mode: Mapped[FulfillmentMode] = mapped_column(
        enum_type(FulfillmentMode, name="order_fulfillment_mode", length=16), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_type(OrderStatus, name="order_status", length=24),
        nullable=False,
        default=OrderStatus.NEW,
        server_default=OrderStatus.NEW.value,
    )
    status_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pickup_location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    consolidation_location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    delivery_zone_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("delivery_zones.id", ondelete="SET NULL")
    )
    assigned_courier_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    contact_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery_address: Mapped[str | None] = mapped_column(Text)
    entrance: Mapped[str | None] = mapped_column(String(32))
    apartment: Mapped[str | None] = mapped_column(String(32))
    floor: Mapped[str | None] = mapped_column(String(32))
    customer_comment: Mapped[str | None] = mapped_column(Text)
    desired_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pickup_name_snapshot: Mapped[str | None] = mapped_column(String(160))
    pickup_address_snapshot: Mapped[str | None] = mapped_column(Text)
    delivery_zone_name_snapshot: Mapped[str | None] = mapped_column(String(160))
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promotion_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delivery_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        enum_type(PaymentMethod, name="order_payment_method", length=24), nullable=False
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        enum_type(PaymentStatus, name="order_payment_status", length=24),
        nullable=False,
        default=PaymentStatus.UNPAID,
        server_default=PaymentStatus.UNPAID.value,
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderSuborder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_suborders"
    __table_args__ = (
        UniqueConstraint("order_id", "venue_id", name="order_venue_suborder"),
        CheckConstraint(
            "subtotal_minor >= 0 AND promotion_discount_minor >= 0 "
            "AND points_discount_minor >= 0 AND total_minor >= 0",
            name="non_negative_amounts",
        ),
        Index("ix_order_suborders_venue_status", "venue_id", "status", "created_at"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="RESTRICT"), nullable=False
    )
    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        enum_type(OrderStatus, name="suborder_status", length=24),
        nullable=False,
        default=OrderStatus.NEW,
        server_default=OrderStatus.NEW.value,
    )
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promotion_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrderLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint(
            "unit_base_price_minor >= 0 AND unit_modifiers_price_minor >= 0 "
            "AND subtotal_minor >= 0 AND promotion_discount_minor >= 0 "
            "AND points_discount_minor >= 0 AND total_minor >= 0",
            name="non_negative_amounts",
        ),
        Index("ix_order_lines_suborder_sort", "suborder_id", "sort_order"),
    )

    suborder_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_suborders.id", ondelete="RESTRICT"), nullable=False
    )
    menu_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("menu_items.id", ondelete="SET NULL")
    )
    client_line_id: Mapped[UUID] = mapped_column(nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_base_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit_modifiers_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    promotion_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points_discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OrderLineModifier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_line_modifiers"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_quantity"),
        CheckConstraint(
            "unit_price_delta_minor >= 0 AND total_price_delta_minor >= 0",
            name="non_negative_amounts",
        ),
        Index("ix_order_line_modifiers_line_sort", "order_line_id", "sort_order"),
    )

    order_line_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    modifier_option_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("modifier_options.id", ondelete="SET NULL")
    )
    group_name: Mapped[str] = mapped_column(String(160), nullable=False)
    option_name: Mapped[str] = mapped_column(String(160), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_price_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class OrderAppliedPromotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_applied_promotions"
    __table_args__ = (
        UniqueConstraint("suborder_id", "promotion_id", name="suborder_promotion"),
        CheckConstraint("discount_minor > 0", name="positive_discount"),
    )

    suborder_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_suborders.id", ondelete="RESTRICT"), nullable=False
    )
    promotion_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("promotions.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrderPointRedemption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "order_point_redemptions"
    __table_args__ = (
        UniqueConstraint("order_id", "venue_id", name="order_venue_redemption"),
        CheckConstraint("points > 0 AND discount_minor > 0", name="positive_redemption"),
    )

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="RESTRICT"), nullable=False
    )
    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    loyalty_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrderEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only status/audit history visible through privacy-safe DTOs."""

    __tablename__ = "order_events"
    __table_args__ = (Index("ix_order_events_order_created", "order_id", "created_at", "id"),)

    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_orders.id", ondelete="RESTRICT"), nullable=False
    )
    suborder_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("order_suborders.id", ondelete="RESTRICT")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    actor_role: Mapped[str] = mapped_column(String(24), nullable=False)
    from_status: Mapped[OrderStatus | None] = mapped_column(
        enum_type(OrderStatus, name="order_event_from_status", length=24)
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        enum_type(OrderStatus, name="order_event_to_status", length=24), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(256))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

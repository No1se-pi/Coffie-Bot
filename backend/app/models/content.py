"""Coffee-shop settings, locations, promotions, and informational menu."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import PromotionActionType, PromotionStatus, RoundingMode


class Venue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer-facing establishment/brand within this installation.

    A venue deliberately does not contain a physical address or opening hours:
    those belong to :class:`Location`, whose lifecycle also covers future shared
    pickup and consolidation points.
    """

    __tablename__ = "venues"
    __table_args__ = (
        CheckConstraint(
            "loyalty_accrual_basis_points BETWEEN 0 AND 10000",
            name="valid_loyalty_accrual_basis_points",
        ),
        Index("ix_venues_public_sort", "is_active", "archived_at", "sort_order"),
    )

    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(254))
    website: Mapped[str | None] = mapped_column(String(2048))
    telegram: Mapped[str | None] = mapped_column(String(2048))
    logo_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loyalty_points_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    loyalty_accrual_basis_points: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1_000, server_default="1000"
    )
    loyalty_rounding_mode: Mapped[RoundingMode] = mapped_column(
        enum_type(RoundingMode, name="venue_loyalty_rounding_mode", length=16),
        nullable=False,
        default=RoundingMode.FLOOR,
        server_default=RoundingMode.FLOOR.value,
    )


class Location(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint(
            "business_day_boundary_minutes >= 0 AND business_day_boundary_minutes < 1440",
            name="valid_business_day_boundary",
        ),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="valid_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="valid_longitude",
        ),
        Index(
            "uq_locations_one_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
        Index("ix_locations_active_sort", "is_active", "sort_order"),
        Index("ix_locations_venue_active_sort", "venue_id", "is_active", "sort_order"),
    )

    # Nullable by design: a future organization-level consolidation point may
    # serve several venues without itself being owned by one of them.
    venue_id: Mapped[UUID | None] = mapped_column(ForeignKey("venues.id", ondelete="SET NULL"))
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    business_day_boundary_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    phone: Mapped[str | None] = mapped_column(String(64))
    map_url: Mapped[str | None] = mapped_column(String(2048))
    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class AppSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )


class Promotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at > starts_at",
            name="valid_publication_window",
        ),
        CheckConstraint(
            "discount_value IS NULL OR discount_value > 0",
            name="positive_discount_value",
        ),
        CheckConstraint(
            "action_type <> 'percent_discount' OR discount_value <= 10000",
            name="valid_percent_discount_value",
        ),
        CheckConstraint(
            "NOT pricing_enabled OR (action_type IS NOT NULL AND discount_value IS NOT NULL)",
            name="complete_pricing_action",
        ),
        CheckConstraint(
            "active_to_date IS NULL OR active_from_date IS NULL "
            "OR active_to_date >= active_from_date",
            name="valid_pricing_date_window",
        ),
        CheckConstraint("minimum_order_minor >= 0", name="non_negative_minimum_order"),
        UniqueConstraint("id", "venue_id", name="uq_promotions_id_venue"),
        Index("ix_promotions_status_window", "status", "starts_at", "ends_at"),
        Index("ix_promotions_venue_pricing", "venue_id", "pricing_enabled", "priority"),
    )

    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    button_label: Mapped[str | None] = mapped_column(String(80))
    button_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[PromotionStatus] = mapped_column(
        enum_type(PromotionStatus, name="promotion_status", length=16),
        nullable=False,
        default=PromotionStatus.DRAFT,
        server_default=PromotionStatus.DRAFT.value,
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pricing_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    action_type: Mapped[PromotionActionType | None] = mapped_column(
        enum_type(PromotionActionType, name="promotion_action_type", length=24)
    )
    discount_value: Mapped[int | None] = mapped_column(BigInteger)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    stackable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    active_from_date: Mapped[date | None] = mapped_column(Date)
    active_to_date: Mapped[date | None] = mapped_column(Date)
    active_weekdays: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    active_time_from: Mapped[time | None] = mapped_column(Time)
    active_time_to: Mapped[time | None] = mapped_column(Time)
    fulfillment_modes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    customer_birthday_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    minimum_order_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class MenuCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "menu_categories"
    __table_args__ = (
        UniqueConstraint("id", "venue_id", name="uq_menu_categories_id_venue"),
        Index("ix_menu_categories_visible_sort", "venue_id", "is_visible", "sort_order"),
    )

    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    icon_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MenuItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "menu_items"
    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="non_negative_price"),
        CheckConstraint(
            "old_price_minor IS NULL OR old_price_minor >= 0", name="non_negative_old_price"
        ),
        CheckConstraint(
            "points_price IS NULL OR points_price > 0",
            name="positive_points_price",
        ),
        ForeignKeyConstraint(
            ["category_id", "venue_id"],
            ["menu_categories.id", "menu_categories.venue_id"],
            name="fk_menu_items_category_venue",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "venue_id", name="uq_menu_items_id_venue"),
        Index(
            "ix_menu_items_category_visible_sort",
            "venue_id",
            "category_id",
            "is_visible",
            "sort_order",
        ),
        Index("ix_menu_items_available", "is_available"),
    )

    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    category_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    old_price_minor: Mapped[int | None] = mapped_column(BigInteger)
    points_price: Mapped[int | None] = mapped_column(BigInteger)
    points_reward_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reward_templates.id", ondelete="SET NULL")
    )
    composition: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(String(80))
    labels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModifierGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic selection rule shared by one or more items of a single venue."""

    __tablename__ = "modifier_groups"
    __table_args__ = (
        CheckConstraint("min_selections >= 0", name="non_negative_min_selections"),
        CheckConstraint("max_selections >= min_selections", name="valid_selection_range"),
        UniqueConstraint("id", "venue_id", name="uq_modifier_groups_id_venue"),
        Index("ix_modifier_groups_venue_sort", "venue_id", "is_enabled", "sort_order"),
    )

    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    min_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModifierOption(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Priced option inside a generic modifier group."""

    __tablename__ = "modifier_options"
    __table_args__ = (
        CheckConstraint("price_delta_minor >= 0", name="non_negative_price_delta"),
        CheckConstraint("max_quantity >= 1", name="positive_max_quantity"),
        Index("ix_modifier_options_group_sort", "group_id", "is_enabled", "sort_order"),
    )

    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("modifier_groups.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    price_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    allows_quantity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MenuItemModifierGroup(Base):
    """Venue-safe many-to-many attachment of groups to menu items."""

    __tablename__ = "menu_item_modifier_groups"
    __table_args__ = (
        PrimaryKeyConstraint("menu_item_id", "modifier_group_id"),
        ForeignKeyConstraint(
            ["menu_item_id", "venue_id"],
            ["menu_items.id", "menu_items.venue_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["modifier_group_id", "venue_id"],
            ["modifier_groups.id", "modifier_groups.venue_id"],
            ondelete="CASCADE",
        ),
    )

    menu_item_id: Mapped[UUID] = mapped_column(nullable=False)
    modifier_group_id: Mapped[UUID] = mapped_column(nullable=False)
    venue_id: Mapped[UUID] = mapped_column(nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PromotionMenuCategory(Base):
    __tablename__ = "promotion_menu_categories"
    __table_args__ = (
        PrimaryKeyConstraint("promotion_id", "category_id"),
        ForeignKeyConstraint(
            ["promotion_id", "venue_id"],
            ["promotions.id", "promotions.venue_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["category_id", "venue_id"],
            ["menu_categories.id", "menu_categories.venue_id"],
            ondelete="CASCADE",
        ),
    )

    promotion_id: Mapped[UUID] = mapped_column(nullable=False)
    category_id: Mapped[UUID] = mapped_column(nullable=False)
    venue_id: Mapped[UUID] = mapped_column(nullable=False)


class PromotionMenuItem(Base):
    __tablename__ = "promotion_menu_items"
    __table_args__ = (
        PrimaryKeyConstraint("promotion_id", "menu_item_id"),
        ForeignKeyConstraint(
            ["promotion_id", "venue_id"],
            ["promotions.id", "promotions.venue_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["menu_item_id", "venue_id"],
            ["menu_items.id", "menu_items.venue_id"],
            ondelete="CASCADE",
        ),
    )

    promotion_id: Mapped[UUID] = mapped_column(nullable=False)
    menu_item_id: Mapped[UUID] = mapped_column(nullable=False)
    venue_id: Mapped[UUID] = mapped_column(nullable=False)

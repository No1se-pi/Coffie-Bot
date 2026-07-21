"""Coffee-shop settings, locations, promotions, and informational menu."""

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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import PromotionStatus


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
    )

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
        Index("ix_promotions_status_window", "status", "starts_at", "ends_at"),
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


class MenuCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "menu_categories"
    __table_args__ = (Index("ix_menu_categories_visible_sort", "is_visible", "sort_order"),)

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
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
        Index("ix_menu_items_category_visible_sort", "category_id", "is_visible", "sort_order"),
        Index("ix_menu_items_available", "is_available"),
    )

    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("menu_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    old_price_minor: Mapped[int | None] = mapped_column(BigInteger)
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

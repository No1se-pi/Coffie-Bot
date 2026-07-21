"""Durable broadcasts and PostgreSQL-backed notification outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import BroadcastStatus, DeliveryStatus, OutboxStatus


class Broadcast(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcasts"
    __table_args__ = (
        CheckConstraint(
            "success_count >= 0 AND failure_count >= 0 AND skipped_count >= 0",
            name="non_negative_delivery_counts",
        ),
        Index("ix_broadcasts_status_created", "status", "created_at"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    button_label: Mapped[str | None] = mapped_column(String(80))
    button_url: Mapped[str | None] = mapped_column(String(2048))
    audience_filter: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[BroadcastStatus] = mapped_column(
        enum_type(BroadcastStatus, name="broadcast_status", length=16),
        nullable=False,
        default=BroadcastStatus.DRAFT,
        server_default=BroadcastStatus.DRAFT.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    confirmed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    success_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    skipped_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class BroadcastDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        Index("uq_broadcast_deliveries_broadcast_user", "broadcast_id", "user_id", unique=True),
        Index("ix_broadcast_deliveries_claim", "status", "next_attempt_at"),
    )

    broadcast_id: Mapped[UUID] = mapped_column(
        ForeignKey("broadcasts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        enum_type(DeliveryStatus, name="delivery_status", length=16),
        nullable=False,
        default=DeliveryStatus.PENDING,
        server_default=DeliveryStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(128))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        Index("ix_notification_outbox_claim", "status", "next_attempt_at"),
        CheckConstraint("attempts >= 0", name="non_negative_attempts"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[OutboxStatus] = mapped_column(
        enum_type(OutboxStatus, name="outbox_status", length=16),
        nullable=False,
        default=OutboxStatus.PENDING,
        server_default=OutboxStatus.PENDING.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(128))

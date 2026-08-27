"""Manual/POS-ready receipts, immutable revisions, and simple risk signals."""

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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import ReceiptSource, ReceiptStatus


class ReceiptRiskSettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Database-owned thresholds so installation policy never lives in service code."""

    __tablename__ = "receipt_risk_settings"
    __table_args__ = (
        CheckConstraint("singleton_key = 'default'", name="singleton_key"),
        CheckConstraint(
            "high_amount_minor > 0 AND staff_hour_limit > 0 AND "
            "same_amount_day_limit > 0 AND customer_day_limit > 0 AND "
            "staff_cancel_day_limit > 0",
            name="positive_thresholds",
        ),
    )

    singleton_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    photo_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    high_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    staff_hour_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    same_amount_day_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_day_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    staff_cancel_day_limit: Mapped[int] = mapped_column(Integer, nullable=False)


class Receipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint("created_by_staff_id", "idempotency_key", name="staff_idempotency"),
        UniqueConstraint("source", "external_id", name="source_external_id"),
        CheckConstraint("amount_minor > 0", name="positive_amount"),
        CheckConstraint("current_revision >= 1", name="positive_revision"),
        CheckConstraint(
            "(status = 'cancelled' AND cancelled_at IS NOT NULL) OR "
            "(status = 'active' AND cancelled_at IS NULL)",
            name="valid_cancel_state",
        ),
        Index("ix_receipts_customer_created", "user_id", "created_at"),
        Index("ix_receipts_staff_created", "created_by_staff_id", "created_at"),
        Index("ix_receipts_venue_created", "venue_id", "created_at"),
        Index("ix_receipts_number", "receipt_number"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    venue_id: Mapped[UUID] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="RESTRICT")
    )
    source: Mapped[ReceiptSource] = mapped_column(
        enum_type(ReceiptSource, name="receipt_source", length=16), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(160))
    receipt_number: Mapped[str | None] = mapped_column(String(160))
    fiscal_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReceiptStatus] = mapped_column(
        enum_type(ReceiptStatus, name="receipt_status", length=16), nullable=False
    )
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"), nullable=False
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )


class ReceiptRevision(UUIDPrimaryKeyMixin, Base):
    """Full immutable receipt snapshot written for create and every metadata edit."""

    __tablename__ = "receipt_revisions"
    __table_args__ = (
        UniqueConstraint("receipt_id", "revision", name="receipt_revision"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        Index("ix_receipt_revisions_receipt_created", "receipt_id", "created_at"),
    )

    receipt_id: Mapped[UUID] = mapped_column(ForeignKey("receipts.id", ondelete="RESTRICT"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="RESTRICT")
    )
    receipt_number: Mapped[str | None] = mapped_column(String(160))
    external_id: Mapped[str | None] = mapped_column(String(160))
    fiscal_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReceiptRiskFlag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "receipt_risk_flags"
    __table_args__ = (
        UniqueConstraint("receipt_id", "code", name="receipt_code"),
        Index("ix_receipt_risk_flags_open_created", "resolved_at", "created_at"),
    )

    receipt_id: Mapped[UUID] = mapped_column(ForeignKey("receipts.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)

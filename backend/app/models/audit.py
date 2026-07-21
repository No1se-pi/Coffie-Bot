"""Structured immutable business audit events."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import AuditSeverity


class AuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_created_type", "created_at", "event_type"),
        Index("ix_audit_events_actor", "actor_user_id", "created_at"),
        Index("ix_audit_events_subject", "subject_user_id", "created_at"),
        Index("ix_audit_events_suspicious", "is_suspicious", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )
    subject_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    object_type: Mapped[str | None] = mapped_column(String(80))
    object_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    severity: Mapped[AuditSeverity] = mapped_column(
        enum_type(AuditSeverity, name="audit_severity", length=16),
        nullable=False,
        default=AuditSeverity.INFO,
        server_default=AuditSeverity.INFO.value,
    )
    is_suspicious: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))

"""Metadata for files stored in the non-executable media volume."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import MediaStatus


class MediaFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_files"
    __table_args__ = (
        CheckConstraint("byte_size > 0", name="positive_byte_size"),
        Index("ix_media_files_status", "status"),
        Index("ix_media_files_sha256", "sha256"),
    )

    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    detected_mime: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[MediaStatus] = mapped_column(
        enum_type(MediaStatus, name="media_status", length=16),
        nullable=False,
        default=MediaStatus.ACTIVE,
        server_default=MediaStatus.ACTIVE.value,
    )
    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

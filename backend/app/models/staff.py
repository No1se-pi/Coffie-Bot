"""Moderated employee tip profiles and private customer feedback."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import FeedbackCategory, FeedbackStatus, TipProfileStatus


class StaffTipProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_tip_profiles"
    __table_args__ = (Index("ix_staff_tip_profiles_status_visible", "status", "is_visible"),)

    staff_member_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    published_name: Mapped[str | None] = mapped_column(String(128))
    published_bio: Mapped[str | None] = mapped_column(Text)
    published_tip_url: Mapped[str | None] = mapped_column(String(2048))
    published_photo_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    published_tip_qr_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    pending_name: Mapped[str | None] = mapped_column(String(128))
    pending_bio: Mapped[str | None] = mapped_column(Text)
    pending_tip_url: Mapped[str | None] = mapped_column(String(2048))
    pending_photo_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    pending_tip_qr_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    status: Mapped[TipProfileStatus] = mapped_column(
        enum_type(TipProfileStatus, name="tip_profile_status", length=20),
        nullable=False,
        default=TipProfileStatus.DRAFT,
        server_default=TipProfileStatus.DRAFT.value,
    )
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )
    moderation_note: Mapped[str | None] = mapped_column(Text)


class FeedbackItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback_items"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_between_1_and_5"),
        Index("ix_feedback_items_status_created", "status", "created_at"),
        Index("ix_feedback_items_user_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[FeedbackCategory] = mapped_column(
        enum_type(FeedbackCategory, name="feedback_category", length=24),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    may_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[FeedbackStatus] = mapped_column(
        enum_type(FeedbackStatus, name="feedback_status", length=16),
        nullable=False,
        default=FeedbackStatus.NEW,
        server_default=FeedbackStatus.NEW.value,
    )
    assigned_to_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )
    internal_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

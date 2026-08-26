"""Customer identities separated from the stable legacy ``users`` profile."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import IdentityProvider

if TYPE_CHECKING:
    from app.models.access import StaffMember, User


class CustomerIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A verified external identifier owned by exactly one customer profile.

    ``subject`` is provider-normalized: decimal Telegram ID for ``telegram`` and
    E.164-like text for ``phone``. Keeping the provider namespace explicit lets a
    future MAX adapter attach identities without changing the customer table.
    """

    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "subject",
            name="uq_customer_identities_provider_subject",
        ),
        Index("ix_customer_identities_user_provider", "user_id", "provider"),
        Index("ix_customer_identities_last_used", "provider", "last_used_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider: Mapped[IdentityProvider] = mapped_column(
        enum_type(IdentityProvider, name="identity_provider", length=16),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    user: Mapped[User] = relationship(back_populates="identities")
    verified_by: Mapped[StaffMember | None] = relationship(foreign_keys=[verified_by_staff_id])


class CustomerMerge(UUIDPrimaryKeyMixin, Base):
    """Immutable receipt and direct lineage edge for one committed account merge.

    Historical loyalty/audit/visit rows keep their original ``users.id``.  This
    edge lets readers traverse those ids without rewriting an immutable journal,
    while stored totals make idempotent API replays independent of later changes.
    """

    __tablename__ = "customer_merges"
    __table_args__ = (
        UniqueConstraint("source_user_id", name="uq_customer_merges_source_user_id"),
        UniqueConstraint("idempotency_key", name="uq_customer_merges_idempotency_key"),
        CheckConstraint("source_user_id <> canonical_user_id", name="distinct_users"),
        CheckConstraint(
            "points_transferred >= 0 AND source_points_before >= 0 "
            "AND canonical_points_before >= 0 AND canonical_points_after >= 0",
            name="non_negative_point_totals",
        ),
        CheckConstraint(
            "stamps_transferred >= 0 AND source_stamps_before >= 0 "
            "AND canonical_stamps_before >= 0 AND canonical_stamps_after >= 0",
            name="non_negative_stamp_totals",
        ),
        CheckConstraint(
            "identities_moved >= 0 AND rewards_moved >= 0 "
            "AND sessions_revoked >= 0 AND cards_revoked >= 0",
            name="non_negative_merge_counts",
        ),
        CheckConstraint("feedback_moved >= 0", name="non_negative_feedback_moved"),
        CheckConstraint(
            "birthday_resolution IS NULL OR "
            "birthday_resolution IN ('keep_canonical', 'use_source')",
            name="valid_birthday_resolution",
        ),
        Index("ix_customer_merges_canonical_created", "canonical_user_id", "created_at"),
        Index("ix_customer_merges_actor_created", "actor_staff_id", "created_at"),
    )

    source_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_points_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    canonical_points_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    source_points_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_points_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    points_transferred: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_points_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_stamps_before: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_stamps_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stamps_transferred: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_stamps_after: Mapped[int] = mapped_column(Integer, nullable=False)
    visit_snapshot_from_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    identities_moved: Mapped[int] = mapped_column(Integer, nullable=False)
    rewards_moved: Mapped[int] = mapped_column(Integer, nullable=False)
    sessions_revoked: Mapped[int] = mapped_column(Integer, nullable=False)
    cards_revoked: Mapped[int] = mapped_column(Integer, nullable=False)
    feedback_moved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    birthday_resolution: Mapped[str | None] = mapped_column(String(24))
    source_staff_rebound: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

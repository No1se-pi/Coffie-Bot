"""Telegram identity, staff access, invitations, and opaque sessions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import PermissionCode, Role, UserStatus

if TYPE_CHECKING:
    from app.models.cards import UserCard
    from app.models.customers import CustomerIdentity
    from app.models.loyalty import UserLoyaltyState


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "(status = 'merged' AND merged_into_user_id IS NOT NULL AND merged_at IS NOT NULL) "
            "OR (status <> 'merged' AND merged_into_user_id IS NULL AND merged_at IS NULL)",
            name="valid_merge_state",
        ),
        CheckConstraint(
            "merged_into_user_id IS NULL OR merged_into_user_id <> id",
            name="not_self_merged",
        ),
        CheckConstraint(
            "(birthday_month IS NULL AND birthday_day IS NULL) OR "
            "(birthday_month BETWEEN 1 AND 12 AND birthday_day BETWEEN 1 AND "
            "CASE birthday_month WHEN 2 THEN 29 WHEN 4 THEN 30 WHEN 6 THEN 30 "
            "WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END)",
            name="valid_birthday_month_day",
        ),
        CheckConstraint(
            "(birthday_month IS NULL AND birthday_day IS NULL AND birthday_set_at IS NULL) OR "
            "(birthday_month IS NOT NULL AND birthday_day IS NOT NULL "
            "AND birthday_set_at IS NOT NULL)",
            name="consistent_birthday_set_state",
        ),
        Index("ix_users_username", "username"),
        Index("ix_users_status", "status"),
        Index("ix_users_merged_into", "merged_into_user_id", "merged_at"),
    )

    # Kept as a nullable compatibility projection while authoritative lookup
    # moves to CustomerIdentity. Phone-only profiles intentionally leave it NULL.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(16))
    photo_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[UserStatus] = mapped_column(
        enum_type(UserStatus, name="user_status", length=16),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    internal_note: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merged_into_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Year is unnecessary PII: the promotion only needs an annual month/day.
    birthday_month: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_day: Mapped[int | None] = mapped_column(SmallInteger)
    birthday_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    birthday_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    birthday_updated_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )

    staff_member: Mapped[StaffMember | None] = relationship(
        back_populates="user",
        foreign_keys="StaffMember.user_id",
        uselist=False,
    )
    sessions: Mapped[list[Session]] = relationship(back_populates="user")
    cards: Mapped[list[UserCard]] = relationship(back_populates="user")
    identities: Mapped[list[CustomerIdentity]] = relationship(back_populates="user")
    merged_into: Mapped[User | None] = relationship(
        remote_side="User.id",
        foreign_keys=[merged_into_user_id],
        back_populates="merged_sources",
    )
    merged_sources: Mapped[list[User]] = relationship(
        foreign_keys=[merged_into_user_id],
        back_populates="merged_into",
    )
    loyalty_state: Mapped[UserLoyaltyState | None] = relationship(
        back_populates="user",
        uselist=False,
    )


class StaffMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_members"
    __table_args__ = (
        CheckConstraint("role <> 'customer'", name="role_not_customer"),
        Index("ix_staff_members_role_active", "role", "is_active"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    role: Mapped[Role] = mapped_column(
        enum_type(Role, name="role", length=16),
        nullable=False,
        default=Role.STAFF,
        server_default=Role.STAFF.value,
    )
    display_name: Mapped[str | None] = mapped_column(String(128))
    position: Mapped[str | None] = mapped_column(String(128))
    bio: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    can_edit_tip_profile: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    user: Mapped[User] = relationship(
        back_populates="staff_member",
        foreign_keys=[user_id],
    )
    permissions: Mapped[list[StaffPermission]] = relationship(
        back_populates="staff_member",
        cascade="all, delete-orphan",
    )


class StaffPermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_permissions"
    __table_args__ = (
        Index(
            "uq_staff_permissions_staff_permission",
            "staff_member_id",
            "permission",
            unique=True,
        ),
    )

    staff_member_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    permission: Mapped[PermissionCode] = mapped_column(
        enum_type(PermissionCode, name="permission_code", length=40),
        nullable=False,
    )
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    staff_member: Mapped[StaffMember] = relationship(back_populates="permissions")


class Session(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_active", "user_id", "expires_at", "revoked_at"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(256))
    created_ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    user: Mapped[User] = relationship(back_populates="sessions")


class StaffInvite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_invites"
    __table_args__ = (
        CheckConstraint("role <> 'customer'", name="role_not_customer"),
        Index("ix_staff_invites_target_telegram_id", "target_telegram_id"),
        Index("ix_staff_invites_expires_at", "expires_at"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    target_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    role: Mapped[Role] = mapped_column(
        enum_type(Role, name="invite_role", length=16),
        nullable=False,
        default=Role.STAFF,
        server_default=Role.STAFF.value,
    )
    invited_by_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invited_by: Mapped[StaffMember] = relationship(foreign_keys=[invited_by_staff_id])
    used_by: Mapped[User | None] = relationship(foreign_keys=[used_by_user_id])

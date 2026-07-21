"""Revocable opaque customer card identifiers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import CardStatus

if TYPE_CHECKING:
    from app.models.access import StaffMember, User


class UserCard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_cards"
    __table_args__ = (
        Index(
            "uq_user_cards_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_user_cards_status", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    qr_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    short_code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    status: Mapped[CardStatus] = mapped_column(
        enum_type(CardStatus, name="card_status", length=16),
        nullable=False,
        default=CardStatus.ACTIVE,
        server_default=CardStatus.ACTIVE.value,
    )
    issued_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="cards")
    issued_by: Mapped[StaffMember | None] = relationship(foreign_keys=[issued_by_staff_id])
    revoked_by: Mapped[StaffMember | None] = relationship(foreign_keys=[revoked_by_staff_id])

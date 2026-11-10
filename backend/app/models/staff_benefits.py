"""Employee-only monthly allowance lots and immutable allocations."""

from datetime import date, datetime
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
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StaffBenefitPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_benefit_policies"
    __table_args__ = (
        CheckConstraint("monthly_points > 0", name="positive_monthly_points"),
        CheckConstraint("minor_units_per_point > 0", name="positive_point_value"),
    )

    staff_id: Mapped[UUID] = mapped_column(ForeignKey("staff_members.id"), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monthly_points: Mapped[int] = mapped_column(BigInteger, default=3000, nullable=False)
    minor_units_per_point: Mapped[int] = mapped_column(BigInteger, default=100, nullable=False)
    all_items: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    item_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class StaffBenefitGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "staff_benefit_grants"
    __table_args__ = (
        UniqueConstraint("staff_id", "period", name="staff_benefit_month"),
        CheckConstraint("initial_points > 0", name="positive_initial_points"),
        CheckConstraint("remaining_points BETWEEN 0 AND initial_points", name="valid_remaining"),
        CheckConstraint("expires_at > earned_at", name="expiry_after_grant"),
    )

    staff_id: Mapped[UUID] = mapped_column(ForeignKey("staff_members.id"), index=True)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    initial_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class StaffBenefitOperation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "staff_benefit_operations"
    __table_args__ = (
        UniqueConstraint("staff_id", "idempotency_key", name="staff_benefit_operation_key"),
        CheckConstraint("kind IN ('grant', 'spend', 'expire')", name="valid_kind"),
        CheckConstraint("balance_after >= 0", name="non_negative_balance"),
        CheckConstraint(
            "(kind = 'grant' AND delta > 0) OR (kind <> 'grant' AND delta < 0)",
            name="valid_delta",
        ),
    )

    staff_id: Mapped[UUID] = mapped_column(ForeignKey("staff_members.id"), index=True)
    grant_id: Mapped[UUID] = mapped_column(ForeignKey("staff_benefit_grants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reward_id: Mapped[UUID | None] = mapped_column(ForeignKey("rewards.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

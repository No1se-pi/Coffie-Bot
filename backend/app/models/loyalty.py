"""Relational contract for future transactional loyalty services."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import (
    LoyaltyOperationType,
    LoyaltyProgram,
    OperationStatus,
    RewardStatus,
    RewardType,
    RoundingMode,
)

if TYPE_CHECKING:
    from app.models.access import User


class RewardTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reward_templates"
    __table_args__ = (
        CheckConstraint(
            "validity_days IS NULL OR validity_days > 0", name="positive_validity_days"
        ),
        CheckConstraint("value_int IS NULL OR value_int >= 0", name="non_negative_value"),
        Index("ix_reward_templates_program_active", "source_program", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="SET NULL")
    )
    reward_type: Mapped[RewardType] = mapped_column(
        enum_type(RewardType, name="reward_type", length=24),
        nullable=False,
    )
    source_program: Mapped[LoyaltyProgram] = mapped_column(
        enum_type(LoyaltyProgram, name="loyalty_program", length=16),
        nullable=False,
    )
    value_int: Mapped[int | None] = mapped_column(BigInteger)
    terms: Mapped[str | None] = mapped_column(Text)
    validity_days: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )


class LoyaltySettings(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_settings"
    __table_args__ = (
        CheckConstraint("minor_units_per_point > 0", name="positive_minor_units_per_point"),
        CheckConstraint(
            "redemption_minor_units_per_point > 0",
            name="positive_redemption_minor_units_per_point",
        ),
        CheckConstraint("minimum_purchase_minor >= 0", name="non_negative_minimum_purchase"),
        CheckConstraint("maximum_purchase_minor > 0", name="positive_maximum_purchase"),
        CheckConstraint(
            "maximum_redemption_percent >= 0 AND maximum_redemption_percent <= 100",
            name="redemption_percent_between_0_and_100",
        ),
        CheckConstraint("minimum_redemption_points >= 0", name="non_negative_minimum_redemption"),
        CheckConstraint("welcome_bonus_points >= 0", name="non_negative_welcome_bonus"),
        CheckConstraint("visit_required_count > 0", name="positive_visit_required_count"),
        CheckConstraint("visit_daily_limit > 0", name="positive_visit_daily_limit"),
        CheckConstraint("visit_allowed_misses >= 0", name="non_negative_visit_allowed_misses"),
        CheckConstraint("stamp_required_count > 0", name="positive_stamp_required_count"),
        CheckConstraint("stamps_per_purchase > 0", name="positive_stamps_per_purchase"),
        CheckConstraint("stamp_operation_limit > 0", name="positive_stamp_operation_limit"),
        CheckConstraint(
            "business_day_boundary_minutes >= 0 AND business_day_boundary_minutes < 1440",
            name="valid_business_day_boundary",
        ),
    )

    singleton_key: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        unique=True,
        default="default",
        server_default="default",
    )
    currency_name: Mapped[str] = mapped_column(String(64), nullable=False, default="баллы")
    currency_code: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")

    points_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    minor_units_per_point: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1000)
    redemption_minor_units_per_point: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=100,
        server_default="100",
    )
    minimum_purchase_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    maximum_purchase_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1_000_000
    )
    rounding_mode: Mapped[RoundingMode] = mapped_column(
        enum_type(RoundingMode, name="rounding_mode", length=16),
        nullable=False,
        default=RoundingMode.FLOOR,
        server_default=RoundingMode.FLOOR.value,
    )
    maximum_redemption_percent: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=50,
    )
    minimum_redemption_points: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    welcome_bonus_points: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    points_validity_days: Mapped[int | None] = mapped_column(Integer)
    daily_accrual_limit_points: Mapped[int | None] = mapped_column(BigInteger)
    operation_accrual_limit_points: Mapped[int | None] = mapped_column(BigInteger)
    large_operation_threshold_minor: Mapped[int | None] = mapped_column(BigInteger)
    large_operation_requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    visits_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    visit_required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    visits_must_be_consecutive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    visit_daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    business_day_boundary_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visit_allowed_misses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    visit_reset_on_miss: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    visit_reward_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reward_templates.id", ondelete="SET NULL")
    )
    visit_reward_validity_days: Mapped[int | None] = mapped_column(Integer)
    visit_restart_cycle: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    stamps_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    stamp_required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=9)
    stamps_per_purchase: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stamp_operation_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stamp_reward_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reward_templates.id", ondelete="SET NULL")
    )
    stamp_reward_validity_days: Mapped[int | None] = mapped_column(Integer)
    reset_stamps_after_reward: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    updated_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="SET NULL")
    )


class UserLoyaltyState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_loyalty_states"
    __table_args__ = (
        CheckConstraint("points_balance >= 0", name="non_negative_points_balance"),
        CheckConstraint("visit_streak >= 0", name="non_negative_visit_streak"),
        CheckConstraint("stamp_count >= 0", name="non_negative_stamp_count"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    points_balance: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    visit_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_visit_business_date: Mapped[date | None] = mapped_column(Date)
    visit_cycle_started_on: Mapped[date | None] = mapped_column(Date)
    allowed_misses_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    stamp_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    user: Mapped[User] = relationship(back_populates="loyalty_state")


class LoyaltyOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "loyalty_operations"
    __table_args__ = (
        UniqueConstraint("operation_type", "idempotency_key", name="operation_type_idempotency"),
        CheckConstraint(
            "purchase_amount_minor IS NULL OR purchase_amount_minor > 0", name="positive_purchase"
        ),
        Index("ix_loyalty_operations_user_created", "user_id", "created_at"),
        Index("ix_loyalty_operations_actor_created", "actor_staff_id", "created_at"),
        Index("ix_loyalty_operations_status_created", "status", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    operation_type: Mapped[LoyaltyOperationType] = mapped_column(
        enum_type(LoyaltyOperationType, name="loyalty_operation_type", length=24),
        nullable=False,
    )
    status: Mapped[OperationStatus] = mapped_column(
        enum_type(OperationStatus, name="operation_status", length=16),
        nullable=False,
        default=OperationStatus.COMMITTED,
        server_default=OperationStatus.COMMITTED.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purchase_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    points_delta: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    balance_before: Mapped[int | None] = mapped_column(BigInteger)
    balance_after: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    reversal_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        unique=True,
    )
    approved_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PointTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "point_transactions"
    __table_args__ = (
        CheckConstraint("balance_before >= 0 AND balance_after >= 0", name="non_negative_balances"),
        Index("ix_point_transactions_user_created", "user_id", "created_at"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purchase_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Visit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("user_id", "business_date", "ordinal", name="user_business_date_ordinal"),
        Index("ix_visits_business_date", "business_date"),
        CheckConstraint("streak_after >= 0", name="non_negative_streak_after"),
        CheckConstraint("ordinal > 0", name="positive_ordinal"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    staff_member_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"),
        nullable=False,
    )
    location_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT")
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    streak_after: Mapped[int] = mapped_column(Integer, nullable=False)


class Reward(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rewards"
    __table_args__ = (
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at", name="expiration_after_creation"
        ),
        Index("ix_rewards_user_status_expires", "user_id", "status", "expires_at"),
        Index("ix_rewards_status_expires", "status", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("reward_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reward_type: Mapped[RewardType] = mapped_column(
        enum_type(RewardType, name="issued_reward_type", length=24),
        nullable=False,
    )
    value_int: Mapped[int | None] = mapped_column(BigInteger)
    terms: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RewardStatus] = mapped_column(
        enum_type(RewardStatus, name="reward_status", length=16),
        nullable=False,
        default=RewardStatus.ACTIVE,
        server_default=RewardStatus.ACTIVE.value,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    redemption_operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        unique=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT")
    )
    cancellation_operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        unique=True,
    )
    internal_comment: Mapped[str | None] = mapped_column(Text)


class StampTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stamp_transactions"
    __table_args__ = (
        CheckConstraint("stamps_before >= 0 AND stamps_after >= 0", name="non_negative_stamps"),
        CheckConstraint("delta <> 0", name="non_zero_delta"),
        Index("ix_stamp_transactions_user_created", "user_id", "created_at"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    stamps_before: Mapped[int] = mapped_column(Integer, nullable=False)
    stamps_after: Mapped[int] = mapped_column(Integer, nullable=False)
    issued_reward_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rewards.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

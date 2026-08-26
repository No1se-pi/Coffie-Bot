"""Wallet, point-lot, transfer routing, and birthday promotion persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import enum_type
from app.models.enums import PointAllocationType, PointLotSourceType, WalletMode


class LoyaltyWallet(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mutable point snapshot for the shared scope or one venue."""

    __tablename__ = "loyalty_wallets"
    __table_args__ = (
        CheckConstraint("balance_points >= 0", name="non_negative_balance_points"),
        CheckConstraint("version > 0", name="positive_version"),
        Index(
            "uq_loyalty_wallets_shared_user",
            "user_id",
            unique=True,
            postgresql_where=text("venue_id IS NULL"),
        ),
        Index(
            "uq_loyalty_wallets_user_venue",
            "user_id",
            "venue_id",
            unique=True,
            postgresql_where=text("venue_id IS NOT NULL"),
        ),
        Index("ix_loyalty_wallets_user_scope", "user_id", "venue_id", "id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    venue_id: Mapped[UUID | None] = mapped_column(ForeignKey("venues.id", ondelete="RESTRICT"))
    balance_points: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class PointLot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A minted batch consumed by immutable allocations."""

    __tablename__ = "point_lots"
    __table_args__ = (
        CheckConstraint("initial_points > 0", name="positive_initial_points"),
        CheckConstraint(
            "remaining_points >= 0 AND remaining_points <= initial_points",
            name="valid_remaining_points",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > earned_at", name="expiry_after_earned_at"
        ),
        CheckConstraint(
            "(source_type = 'opening_balance' AND source_operation_id IS NULL "
            "AND expires_at IS NULL) OR "
            "(source_type <> 'opening_balance' AND source_operation_id IS NOT NULL)",
            name="valid_source_operation_and_expiry",
        ),
        CheckConstraint(
            "transferred_from_lot_id IS NULL OR transferred_from_lot_id <> id",
            name="not_self_transferred",
        ),
        CheckConstraint(
            "expired_at IS NULL OR (expires_at IS NOT NULL "
            "AND expired_at >= expires_at AND remaining_points = 0)",
            name="valid_expired_state",
        ),
        Index(
            "ix_point_lots_wallet_fifo",
            "wallet_id",
            "earned_at",
            "id",
            postgresql_where=text("remaining_points > 0"),
        ),
        Index(
            "ix_point_lots_due_expiry",
            "expires_at",
            "wallet_id",
            "id",
            postgresql_where=text("remaining_points > 0 AND expires_at IS NOT NULL"),
        ),
        Index("ix_point_lots_source_operation", "source_operation_id", "id"),
    )

    wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_wallets.id", ondelete="RESTRICT"), nullable=False
    )
    source_operation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT")
    )
    source_venue_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT")
    )
    transferred_from_lot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("point_lots.id", ondelete="RESTRICT")
    )
    source_type: Mapped[PointLotSourceType] = mapped_column(
        enum_type(PointLotSourceType, name="point_lot_source_type", length=24),
        nullable=False,
    )
    initial_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Transfers copy earned_at so a mode switch cannot make old points younger
    # or change strict FIFO ordering.
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expiry_reminder_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PointAllocation(UUIDPrimaryKeyMixin, Base):
    """Append-only explanation for every debit, expiry, or restore."""

    __tablename__ = "point_allocations"
    __table_args__ = (
        CheckConstraint("points > 0", name="positive_points"),
        CheckConstraint(
            "(allocation_type = 'reversal_restore' AND reverses_allocation_id IS NOT NULL) OR "
            "(allocation_type <> 'reversal_restore' AND reverses_allocation_id IS NULL)",
            name="valid_reversal_reference",
        ),
        UniqueConstraint(
            "operation_id",
            "lot_id",
            "allocation_type",
            name="uq_point_allocations_operation_lot_allocation_type",
        ),
        Index("ix_point_allocations_operation", "operation_id", "created_at", "id"),
        Index("ix_point_allocations_lot", "lot_id", "created_at", "id"),
    )

    operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"), nullable=False
    )
    lot_id: Mapped[UUID] = mapped_column(
        ForeignKey("point_lots.id", ondelete="RESTRICT"), nullable=False
    )
    allocation_type: Mapped[PointAllocationType] = mapped_column(
        enum_type(PointAllocationType, name="point_allocation_type", length=32),
        nullable=False,
    )
    points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reverses_allocation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("point_allocations.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletModeSwitch(UUIDPrimaryKeyMixin, Base):
    """Owner-confirmed, idempotent receipt for a global mode transition."""

    __tablename__ = "wallet_mode_switches"
    __table_args__ = (
        CheckConstraint("total_points_before >= 0", name="non_negative_total_before"),
        CheckConstraint("total_points_after >= 0", name="non_negative_total_after"),
        CheckConstraint("total_points_before = total_points_after", name="conserved_total_points"),
        CheckConstraint("from_mode <> to_mode", name="different_modes"),
        CheckConstraint("wallets_moved >= 0 AND lots_moved >= 0", name="non_negative_move_counts"),
        UniqueConstraint("idempotency_key", name="uq_wallet_mode_switches_idempotency_key"),
        Index("ix_wallet_mode_switches_completed", "completed_at", "id"),
    )

    actor_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    actor_staff_id: Mapped[UUID] = mapped_column(
        ForeignKey("staff_members.id", ondelete="RESTRICT"), nullable=False
    )
    from_mode: Mapped[WalletMode] = mapped_column(
        enum_type(WalletMode, name="wallet_switch_from_mode", length=16), nullable=False
    )
    to_mode: Mapped[WalletMode] = mapped_column(
        enum_type(WalletMode, name="wallet_switch_to_mode", length=16), nullable=False
    )
    fallback_venue_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    total_points_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_points_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wallets_moved: Mapped[int] = mapped_column(Integer, nullable=False)
    lots_moved: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WalletTransfer(UUIDPrimaryKeyMixin, Base):
    """Per-user source/destination journal pair produced by a mode switch."""

    __tablename__ = "wallet_transfers"
    __table_args__ = (
        CheckConstraint("points > 0", name="positive_points"),
        CheckConstraint("source_wallet_id <> destination_wallet_id", name="different_wallets"),
        CheckConstraint("debit_operation_id <> credit_operation_id", name="different_operations"),
        UniqueConstraint(
            "switch_id",
            "source_wallet_id",
            "destination_wallet_id",
            name="uq_wallet_transfers_switch_wallet_pair",
        ),
    )

    switch_id: Mapped[UUID] = mapped_column(
        ForeignKey("wallet_mode_switches.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_wallets.id", ondelete="RESTRICT"), nullable=False
    )
    destination_wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_wallets.id", ondelete="RESTRICT"), nullable=False
    )
    debit_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    credit_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_operations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    points: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PointLotRoute(UUIDPrimaryKeyMixin, Base):
    """Map even a fully spent historic lot to the current wallet scope."""

    __tablename__ = "point_lot_routes"
    __table_args__ = (
        UniqueConstraint(
            "switch_id", "source_lot_id", name="uq_point_lot_routes_switch_source_lot"
        ),
        CheckConstraint(
            "destination_lot_id IS NULL OR destination_lot_id <> source_lot_id",
            name="different_destination_lot",
        ),
        Index("ix_point_lot_routes_source_created", "source_lot_id", "created_at", "id"),
    )

    switch_id: Mapped[UUID] = mapped_column(
        ForeignKey("wallet_mode_switches.id", ondelete="RESTRICT"), nullable=False
    )
    source_lot_id: Mapped[UUID] = mapped_column(
        ForeignKey("point_lots.id", ondelete="RESTRICT"), nullable=False
    )
    destination_wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_wallets.id", ondelete="RESTRICT"), nullable=False
    )
    destination_lot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("point_lots.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountMergeLotRoute(UUIDPrimaryKeyMixin, Base):
    """Preserve source-lot lineage while merge credits the canonical profile."""

    __tablename__ = "account_merge_lot_routes"
    __table_args__ = (
        UniqueConstraint(
            "customer_merge_id",
            "source_lot_id",
            name="uq_account_merge_lot_routes_merge_source_lot",
        ),
        CheckConstraint(
            "destination_lot_id IS NULL OR destination_lot_id <> source_lot_id",
            name="different_destination_lot",
        ),
        Index("ix_account_merge_lot_routes_source", "source_lot_id", "created_at", "id"),
    )

    customer_merge_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_merges.id", ondelete="RESTRICT"), nullable=False
    )
    source_lot_id: Mapped[UUID] = mapped_column(
        ForeignKey("point_lots.id", ondelete="RESTRICT"), nullable=False
    )
    destination_wallet_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_wallets.id", ondelete="RESTRICT"), nullable=False
    )
    destination_lot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("point_lots.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BirthdayPromotionVenue(UUIDPrimaryKeyMixin, Base):
    """Normalized eligible venues; an empty set means every active venue."""

    __tablename__ = "birthday_promotion_venues"
    __table_args__ = (
        UniqueConstraint(
            "settings_id",
            "venue_id",
            name="uq_birthday_promotion_venues_settings_venue",
        ),
    )

    settings_id: Mapped[UUID] = mapped_column(
        ForeignKey("loyalty_settings.id", ondelete="CASCADE"), nullable=False
    )
    venue_id: Mapped[UUID] = mapped_column(
        ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False
    )

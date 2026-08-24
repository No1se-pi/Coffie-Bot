"""add Loyalty V2 wallets, point lots, expiry and birthday policy

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOYALTY_OPERATION_TYPES = (
    "purchase_accrual",
    "points_redemption",
    "points_product_purchase",
    "welcome_bonus",
    "admin_adjustment",
    "operation_reversal",
    "points_expiration",
    "visit_mark",
    "stamp_added",
    "reward_created",
    "reward_redeemed",
    "reward_cancelled",
    "account_merge_debit",
    "account_merge_credit",
    "wallet_transfer_debit",
    "wallet_transfer_credit",
)
LOT_SOURCE_TYPES = (
    "opening_balance",
    "accrual",
    "welcome_bonus",
    "reward_bonus",
    "admin_adjustment",
    "reversal",
    "wallet_transfer",
    "account_merge",
)
ALLOCATION_TYPES = (
    "spend",
    "expiry",
    "reversal_debit",
    "reversal_restore",
    "wallet_transfer_debit",
    "account_merge_debit",
)


def upgrade() -> None:
    _replace_enum_constraint(
        "loyalty_operations",
        "operation_type",
        "loyalty_operation_type",
        LOYALTY_OPERATION_TYPES,
    )
    _extend_customer_merge_receipts()
    _add_policy_columns()
    _create_wallet_tables()
    _create_transfer_tables()
    _create_birthday_venue_table()
    _backfill_opening_wallets_and_lots()


def _extend_customer_merge_receipts() -> None:
    op.add_column(
        "customer_merges",
        sa.Column("feedback_moved", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "customer_merges",
        sa.Column("birthday_resolution", sa.String(length=24), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_customer_merges_non_negative_feedback_moved"),
        "customer_merges",
        "feedback_moved >= 0",
    )
    op.create_check_constraint(
        op.f("ck_customer_merges_valid_birthday_resolution"),
        "customer_merges",
        "birthday_resolution IS NULL OR birthday_resolution IN ('keep_canonical', 'use_source')",
    )


def _add_policy_columns() -> None:
    # Existing venues get a neutral policy.  Real brand rates are seed/config
    # data; a schema migration must never encode customer-facing slugs/names.
    op.add_column(
        "venues",
        sa.Column("loyalty_points_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "venues",
        sa.Column(
            "loyalty_accrual_basis_points",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
    )
    op.add_column(
        "venues",
        sa.Column(
            "loyalty_rounding_mode",
            sa.String(length=16),
            nullable=False,
            server_default="floor",
        ),
    )
    op.create_check_constraint(
        op.f("ck_venues_valid_loyalty_accrual_basis_points"),
        "venues",
        "loyalty_accrual_basis_points BETWEEN 0 AND 10000",
    )
    op.create_check_constraint(
        op.f("ck_venues_venue_loyalty_rounding_mode"),
        "venues",
        "loyalty_rounding_mode IN ('floor', 'half_up', 'ceiling')",
    )

    op.add_column("users", sa.Column("birthday_month", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("birthday_day", sa.SmallInteger(), nullable=True))
    op.add_column("users", sa.Column("birthday_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("birthday_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("birthday_updated_by_staff_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_birthday_updated_by_staff_id_staff_members"),
        "users",
        "staff_members",
        ["birthday_updated_by_staff_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_users_valid_birthday_month_day"),
        "users",
        "(birthday_month IS NULL AND birthday_day IS NULL) OR "
        "(birthday_month BETWEEN 1 AND 12 AND birthday_day BETWEEN 1 AND "
        "CASE birthday_month WHEN 2 THEN 29 WHEN 4 THEN 30 WHEN 6 THEN 30 "
        "WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END)",
    )
    op.create_check_constraint(
        op.f("ck_users_consistent_birthday_set_state"),
        "users",
        "(birthday_month IS NULL AND birthday_day IS NULL AND birthday_set_at IS NULL) OR "
        "(birthday_month IS NOT NULL AND birthday_day IS NOT NULL "
        "AND birthday_set_at IS NOT NULL)",
    )

    op.add_column(
        "loyalty_settings",
        sa.Column("wallet_mode", sa.String(length=16), nullable=False, server_default="shared"),
    )
    op.add_column(
        "loyalty_settings",
        sa.Column("points_expiry_months", sa.Integer(), nullable=False, server_default="6"),
    )
    op.add_column(
        "loyalty_settings",
        sa.Column("expiry_reminder_days", sa.Integer(), nullable=False, server_default="14"),
    )
    op.add_column("loyalty_settings", sa.Column("default_bonus_venue_id", sa.Uuid(), nullable=True))
    op.add_column(
        "loyalty_settings",
        sa.Column(
            "birthday_promotion_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "loyalty_settings",
        sa.Column(
            "birthday_discount_basis_points",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
    )
    op.add_column(
        "loyalty_settings",
        sa.Column("birthday_window_days", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "loyalty_settings",
        sa.Column(
            "birthday_stackable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_foreign_key(
        op.f("fk_loyalty_settings_default_bonus_venue_id_venues"),
        "loyalty_settings",
        "venues",
        ["default_bonus_venue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Legacy installations may already grant a positive welcome bonus.  Adopt
    # their explicitly configured default physical location as provenance so
    # post-upgrade registration does not fail or mint an unexplained lot.
    # Shared installations without such a location remain compatible: their
    # origin-less lot is handled by the explicit fallback during a later split.
    op.execute(
        sa.text(
            """
            UPDATE loyalty_settings AS settings
            SET default_bonus_venue_id = candidate.venue_id
            FROM LATERAL (
                SELECT locations.venue_id
                FROM locations
                JOIN venues ON venues.id = locations.venue_id
                WHERE locations.is_default IS TRUE
                  AND locations.is_active IS TRUE
                  AND locations.venue_id IS NOT NULL
                  AND venues.is_active IS TRUE
                  AND venues.archived_at IS NULL
                ORDER BY locations.id
                LIMIT 1
            ) AS candidate
            WHERE settings.welcome_bonus_points > 0
              AND settings.default_bonus_venue_id IS NULL
            """
        )
    )
    op.create_check_constraint(
        op.f("ck_loyalty_settings_wallet_mode"),
        "loyalty_settings",
        "wallet_mode IN ('shared', 'separate')",
    )
    op.create_check_constraint(
        op.f("ck_loyalty_settings_positive_points_expiry_months"),
        "loyalty_settings",
        "points_expiry_months > 0",
    )
    op.create_check_constraint(
        op.f("ck_loyalty_settings_non_negative_expiry_reminder_days"),
        "loyalty_settings",
        "expiry_reminder_days >= 0",
    )
    op.create_check_constraint(
        op.f("ck_loyalty_settings_valid_birthday_discount_basis_points"),
        "loyalty_settings",
        "birthday_discount_basis_points BETWEEN 0 AND 10000",
    )
    op.create_check_constraint(
        op.f("ck_loyalty_settings_positive_birthday_window_days"),
        "loyalty_settings",
        "birthday_window_days > 0",
    )


def _create_wallet_tables() -> None:
    op.create_table(
        "loyalty_wallets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=True),
        sa.Column("balance_points", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamp_and_id_columns(),
        sa.CheckConstraint(
            "balance_points >= 0", name=op.f("ck_loyalty_wallets_non_negative_balance_points")
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_loyalty_wallets_positive_version")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_loyalty_wallets_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["venues.id"],
            name=op.f("fk_loyalty_wallets_venue_id_venues"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_loyalty_wallets")),
    )
    op.create_index(
        "uq_loyalty_wallets_shared_user",
        "loyalty_wallets",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("venue_id IS NULL"),
    )
    op.create_index(
        "uq_loyalty_wallets_user_venue",
        "loyalty_wallets",
        ["user_id", "venue_id"],
        unique=True,
        postgresql_where=sa.text("venue_id IS NOT NULL"),
    )
    op.create_index(
        "ix_loyalty_wallets_user_scope",
        "loyalty_wallets",
        ["user_id", "venue_id", "id"],
        unique=False,
    )

    op.create_table(
        "point_lots",
        sa.Column("wallet_id", sa.Uuid(), nullable=False),
        sa.Column("source_operation_id", sa.Uuid(), nullable=True),
        sa.Column("source_venue_id", sa.Uuid(), nullable=True),
        sa.Column("transferred_from_lot_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=24), nullable=False),
        sa.Column("initial_points", sa.BigInteger(), nullable=False),
        sa.Column("remaining_points", sa.BigInteger(), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_reminder_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_and_id_columns(),
        sa.CheckConstraint(
            "initial_points > 0", name=op.f("ck_point_lots_positive_initial_points")
        ),
        sa.CheckConstraint(
            "remaining_points >= 0 AND remaining_points <= initial_points",
            name=op.f("ck_point_lots_valid_remaining_points"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > earned_at",
            name=op.f("ck_point_lots_expiry_after_earned_at"),
        ),
        sa.CheckConstraint(
            "(source_type = 'opening_balance' AND source_operation_id IS NULL "
            "AND expires_at IS NULL) OR "
            "(source_type <> 'opening_balance' AND source_operation_id IS NOT NULL)",
            name=op.f("ck_point_lots_valid_source_operation_and_expiry"),
        ),
        sa.CheckConstraint(
            "transferred_from_lot_id IS NULL OR transferred_from_lot_id <> id",
            name=op.f("ck_point_lots_not_self_transferred"),
        ),
        sa.CheckConstraint(
            "expired_at IS NULL OR (expires_at IS NOT NULL "
            "AND expired_at >= expires_at AND remaining_points = 0)",
            name=op.f("ck_point_lots_valid_expired_state"),
        ),
        sa.CheckConstraint(
            _in_values("source_type", LOT_SOURCE_TYPES),
            name=op.f("ck_point_lots_point_lot_source_type"),
        ),
        sa.ForeignKeyConstraint(
            ["wallet_id"],
            ["loyalty_wallets.id"],
            name=op.f("fk_point_lots_wallet_id_loyalty_wallets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_operation_id"],
            ["loyalty_operations.id"],
            name=op.f("fk_point_lots_source_operation_id_loyalty_operations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_venue_id"],
            ["venues.id"],
            name=op.f("fk_point_lots_source_venue_id_venues"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transferred_from_lot_id"],
            ["point_lots.id"],
            name=op.f("fk_point_lots_transferred_from_lot_id_point_lots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_point_lots")),
    )
    op.create_index(
        "ix_point_lots_wallet_fifo",
        "point_lots",
        ["wallet_id", "earned_at", "id"],
        unique=False,
        postgresql_where=sa.text("remaining_points > 0"),
    )
    op.create_index(
        "ix_point_lots_due_expiry",
        "point_lots",
        ["expires_at", "wallet_id", "id"],
        unique=False,
        postgresql_where=sa.text("remaining_points > 0 AND expires_at IS NOT NULL"),
    )
    op.create_index(
        "ix_point_lots_source_operation",
        "point_lots",
        ["source_operation_id", "id"],
        unique=False,
    )

    op.create_table(
        "point_allocations",
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=False),
        sa.Column("allocation_type", sa.String(length=32), nullable=False),
        sa.Column("points", sa.BigInteger(), nullable=False),
        sa.Column("reverses_allocation_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("points > 0", name=op.f("ck_point_allocations_positive_points")),
        sa.CheckConstraint(
            "(allocation_type = 'reversal_restore' AND reverses_allocation_id IS NOT NULL) OR "
            "(allocation_type <> 'reversal_restore' AND reverses_allocation_id IS NULL)",
            name=op.f("ck_point_allocations_valid_reversal_reference"),
        ),
        sa.CheckConstraint(
            _in_values("allocation_type", ALLOCATION_TYPES),
            name=op.f("ck_point_allocations_point_allocation_type"),
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"],
            ["loyalty_operations.id"],
            name=op.f("fk_point_allocations_operation_id_loyalty_operations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["point_lots.id"],
            name=op.f("fk_point_allocations_lot_id_point_lots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_allocation_id"],
            ["point_allocations.id"],
            name=op.f("fk_point_allocations_reverses_allocation_id_point_allocations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_point_allocations")),
        sa.UniqueConstraint(
            "operation_id",
            "lot_id",
            "allocation_type",
            name=op.f("uq_point_allocations_operation_lot_allocation_type"),
        ),
        sa.UniqueConstraint(
            "reverses_allocation_id",
            name=op.f("uq_point_allocations_reverses_allocation_id"),
        ),
    )
    op.create_index(
        "ix_point_allocations_operation",
        "point_allocations",
        ["operation_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_point_allocations_lot",
        "point_allocations",
        ["lot_id", "created_at", "id"],
        unique=False,
    )


def _create_transfer_tables() -> None:
    op.create_table(
        "wallet_mode_switches",
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_staff_id", sa.Uuid(), nullable=False),
        sa.Column("from_mode", sa.String(length=16), nullable=False),
        sa.Column("to_mode", sa.String(length=16), nullable=False),
        sa.Column("fallback_venue_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("preview_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("total_points_before", sa.BigInteger(), nullable=False),
        sa.Column("total_points_after", sa.BigInteger(), nullable=False),
        sa.Column("wallets_moved", sa.Integer(), nullable=False),
        sa.Column("lots_moved", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "total_points_before >= 0",
            name=op.f("ck_wallet_mode_switches_non_negative_total_before"),
        ),
        sa.CheckConstraint(
            "total_points_after >= 0",
            name=op.f("ck_wallet_mode_switches_non_negative_total_after"),
        ),
        sa.CheckConstraint(
            "total_points_before = total_points_after",
            name=op.f("ck_wallet_mode_switches_conserved_total_points"),
        ),
        sa.CheckConstraint(
            "from_mode <> to_mode", name=op.f("ck_wallet_mode_switches_different_modes")
        ),
        sa.CheckConstraint(
            "wallets_moved >= 0 AND lots_moved >= 0",
            name=op.f("ck_wallet_mode_switches_non_negative_move_counts"),
        ),
        sa.CheckConstraint(
            "from_mode IN ('shared', 'separate')",
            name=op.f("ck_wallet_mode_switches_wallet_switch_from_mode"),
        ),
        sa.CheckConstraint(
            "to_mode IN ('shared', 'separate')",
            name=op.f("ck_wallet_mode_switches_wallet_switch_to_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_wallet_mode_switches_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_staff_id"],
            ["staff_members.id"],
            name=op.f("fk_wallet_mode_switches_actor_staff_id_staff_members"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fallback_venue_id"],
            ["venues.id"],
            name=op.f("fk_wallet_mode_switches_fallback_venue_id_venues"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_mode_switches")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_wallet_mode_switches_idempotency_key")
        ),
    )
    op.create_index(
        "ix_wallet_mode_switches_completed",
        "wallet_mode_switches",
        ["completed_at", "id"],
        unique=False,
    )

    op.create_table(
        "wallet_transfers",
        sa.Column("switch_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("destination_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("debit_operation_id", sa.Uuid(), nullable=False),
        sa.Column("credit_operation_id", sa.Uuid(), nullable=False),
        sa.Column("points", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("points > 0", name=op.f("ck_wallet_transfers_positive_points")),
        sa.CheckConstraint(
            "source_wallet_id <> destination_wallet_id",
            name=op.f("ck_wallet_transfers_different_wallets"),
        ),
        sa.CheckConstraint(
            "debit_operation_id <> credit_operation_id",
            name=op.f("ck_wallet_transfers_different_operations"),
        ),
        sa.ForeignKeyConstraint(
            ["switch_id"],
            ["wallet_mode_switches.id"],
            name=op.f("fk_wallet_transfers_switch_id_wallet_mode_switches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_wallet_transfers_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_wallet_id"],
            ["loyalty_wallets.id"],
            name=op.f("fk_wallet_transfers_source_wallet_id_loyalty_wallets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_wallet_id"],
            ["loyalty_wallets.id"],
            name=op.f("fk_wallet_transfers_destination_wallet_id_loyalty_wallets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debit_operation_id"],
            ["loyalty_operations.id"],
            name=op.f("fk_wallet_transfers_debit_operation_id_loyalty_operations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credit_operation_id"],
            ["loyalty_operations.id"],
            name=op.f("fk_wallet_transfers_credit_operation_id_loyalty_operations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_transfers")),
        sa.UniqueConstraint(
            "switch_id",
            "source_wallet_id",
            "destination_wallet_id",
            name=op.f("uq_wallet_transfers_switch_wallet_pair"),
        ),
        sa.UniqueConstraint(
            "debit_operation_id", name=op.f("uq_wallet_transfers_debit_operation_id")
        ),
        sa.UniqueConstraint(
            "credit_operation_id", name=op.f("uq_wallet_transfers_credit_operation_id")
        ),
    )
    _create_route_table("point_lot_routes", "switch_id", "wallet_mode_switches")
    _create_route_table("account_merge_lot_routes", "customer_merge_id", "customer_merges")


def _create_route_table(table: str, receipt_column: str, receipt_table: str) -> None:
    prefix = "switch" if receipt_column == "switch_id" else "merge"
    op.create_table(
        table,
        sa.Column(receipt_column, sa.Uuid(), nullable=False),
        sa.Column("source_lot_id", sa.Uuid(), nullable=False),
        sa.Column("destination_wallet_id", sa.Uuid(), nullable=False),
        sa.Column("destination_lot_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "destination_lot_id IS NULL OR destination_lot_id <> source_lot_id",
            name=op.f(f"ck_{table}_different_destination_lot"),
        ),
        sa.ForeignKeyConstraint(
            [receipt_column],
            [f"{receipt_table}.id"],
            name=op.f(f"fk_{table}_{receipt_column}_{receipt_table}"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_lot_id"],
            ["point_lots.id"],
            name=op.f(f"fk_{table}_source_lot_id_point_lots"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_wallet_id"],
            ["loyalty_wallets.id"],
            name=op.f(f"fk_{table}_destination_wallet_id_loyalty_wallets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["destination_lot_id"],
            ["point_lots.id"],
            name=op.f(f"fk_{table}_destination_lot_id_point_lots"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint(
            receipt_column,
            "source_lot_id",
            name=op.f(f"uq_{table}_{prefix}_source_lot"),
        ),
    )
    index_name = (
        "ix_point_lot_routes_source_created"
        if table == "point_lot_routes"
        else "ix_account_merge_lot_routes_source"
    )
    op.create_index(
        index_name,
        table,
        ["source_lot_id", "created_at", "id"],
        unique=False,
    )


def _create_birthday_venue_table() -> None:
    op.create_table(
        "birthday_promotion_venues",
        sa.Column("settings_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["settings_id"],
            ["loyalty_settings.id"],
            name=op.f("fk_birthday_promotion_venues_settings_id_loyalty_settings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["venues.id"],
            name=op.f("fk_birthday_promotion_venues_venue_id_venues"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_birthday_promotion_venues")),
        sa.UniqueConstraint(
            "settings_id",
            "venue_id",
            name=op.f("uq_birthday_promotion_venues_settings_venue"),
        ),
    )


def _backfill_opening_wallets_and_lots() -> None:
    # Opening state predates lot-level expiry.  Deterministic UUIDs and a null
    # expiry make the compatibility decision explicit and reviewable.
    op.execute(
        sa.text(
            """
            INSERT INTO loyalty_wallets (
                id, user_id, venue_id, balance_points, version, created_at, updated_at
            )
            SELECT
                md5('loyalty-wallet:shared:' || state.user_id::text)::uuid,
                state.user_id,
                NULL,
                state.points_balance,
                1,
                state.created_at,
                state.updated_at
            FROM user_loyalty_states AS state
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO point_lots (
                id, wallet_id, source_operation_id, source_venue_id,
                transferred_from_lot_id, source_type, initial_points,
                remaining_points, earned_at, expires_at, expired_at,
                expiry_reminder_scheduled_at, created_at, updated_at
            )
            SELECT
                md5('point-lot:opening:' || state.user_id::text)::uuid,
                wallet.id,
                NULL,
                NULL,
                NULL,
                'opening_balance',
                state.points_balance,
                state.points_balance,
                state.created_at,
                NULL,
                NULL,
                NULL,
                state.created_at,
                state.updated_at
            FROM user_loyalty_states AS state
            JOIN loyalty_wallets AS wallet
              ON wallet.user_id = state.user_id AND wallet.venue_id IS NULL
            WHERE state.points_balance > 0
            """
        )
    )
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM user_loyalty_states AS state
                    LEFT JOIN (
                        SELECT user_id, SUM(balance_points)::bigint AS total
                        FROM loyalty_wallets GROUP BY user_id
                    ) AS wallets ON wallets.user_id = state.user_id
                    WHERE COALESCE(wallets.total, 0) <> state.points_balance
                ) THEN
                    RAISE EXCEPTION 'Loyalty V2 wallet backfill changed a balance';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM user_loyalty_states AS state
                    LEFT JOIN loyalty_wallets AS wallet ON wallet.user_id = state.user_id
                    GROUP BY state.user_id
                    HAVING COUNT(wallet.id) <> 1
                ) THEN
                    RAISE EXCEPTION 'Every loyalty state must have exactly one opening wallet';
                END IF;
                IF EXISTS (
                    SELECT 1
                    FROM loyalty_wallets AS wallet
                    LEFT JOIN (
                        SELECT wallet_id, SUM(remaining_points)::bigint AS total
                        FROM point_lots GROUP BY wallet_id
                    ) AS lots ON lots.wallet_id = wallet.id
                    WHERE COALESCE(lots.total, 0) <> wallet.balance_points
                ) THEN
                    RAISE EXCEPTION 'Opening lots do not match wallet balances';
                END IF;
            END $$;
            """
        )
    )


def _timestamp_and_id_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
    )


def _replace_enum_constraint(
    table_name: str,
    column_name: str,
    enum_name: str,
    values: tuple[str, ...],
) -> None:
    constraint_name = op.f(f"ck_{table_name}_{enum_name}")
    op.drop_constraint(constraint_name, table_name, type_="check")
    op.create_check_constraint(
        constraint_name,
        table_name,
        _in_values(column_name, values),
    )


def _in_values(column_name: str, values: tuple[str, ...]) -> str:
    allowed = ", ".join(f"'{value}'" for value in values)
    return f"{column_name} IN ({allowed})"


def downgrade() -> None:
    # Lot/allocation/route records become the immutable explanation for point
    # balances.  Removing them would make completed operations unauditable.
    raise RuntimeError("0011 downgrade is intentionally unsupported")

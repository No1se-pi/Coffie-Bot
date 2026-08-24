"""add immutable customer merge lineage and journal operation types

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_STATUSES = ("active", "blocked", "inactive", "anonymized", "merged")
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
)
PERMISSION_CODES = (
    "card.lookup",
    "customers.create",
    "points.accrue",
    "points.redeem",
    "visits.mark",
    "stamps.add",
    "rewards.redeem",
    "operations.reverse_own",
    "tip_profile.manage_own",
    "admin.users.read",
    "admin.users.manage",
    "admin.staff.manage",
    "admin.events.read",
    "admin.settings.manage",
    "admin.content.manage",
    "admin.broadcasts.manage",
    "admin.feedback.manage",
    "owner.admins.manage",
    "owner.export_data",
    "owner.critical_settings",
)


def upgrade() -> None:
    # SQLAlchemy persists these enums as VARCHAR + CHECK.  Alembic does not
    # reliably autogenerate value additions, so every complete allowed set is
    # replaced explicitly before application code can write the new values.
    _replace_enum_constraint("users", "status", "user_status", USER_STATUSES)
    _replace_enum_constraint(
        "loyalty_operations",
        "operation_type",
        "loyalty_operation_type",
        LOYALTY_OPERATION_TYPES,
    )
    # No merge-specific permission is introduced: the endpoint deliberately
    # reuses admin.users.manage. Rebuilding the current set keeps 0009's
    # customers.create value intact on installations upgraded from older code.
    _replace_enum_constraint(
        "staff_permissions",
        "permission",
        "permission_code",
        PERMISSION_CODES,
    )

    op.add_column("users", sa.Column("merged_into_user_id", sa.Uuid(), nullable=True))
    op.add_column("users", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_merged_into_user_id_users"),
        "users",
        "users",
        ["merged_into_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_users_valid_merge_state"),
        "users",
        "(status = 'merged' AND merged_into_user_id IS NOT NULL AND merged_at IS NOT NULL) "
        "OR (status <> 'merged' AND merged_into_user_id IS NULL AND merged_at IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_users_not_self_merged"),
        "users",
        "merged_into_user_id IS NULL OR merged_into_user_id <> id",
    )
    op.create_index(
        "ix_users_merged_into",
        "users",
        ["merged_into_user_id", "merged_at"],
        unique=False,
    )

    op.create_table(
        "customer_merges",
        sa.Column("source_user_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_staff_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("preview_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_points_operation_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_points_operation_id", sa.Uuid(), nullable=False),
        sa.Column("source_points_before", sa.BigInteger(), nullable=False),
        sa.Column("canonical_points_before", sa.BigInteger(), nullable=False),
        sa.Column("points_transferred", sa.BigInteger(), nullable=False),
        sa.Column("canonical_points_after", sa.BigInteger(), nullable=False),
        sa.Column("source_stamps_before", sa.Integer(), nullable=False),
        sa.Column("canonical_stamps_before", sa.Integer(), nullable=False),
        sa.Column("stamps_transferred", sa.Integer(), nullable=False),
        sa.Column("canonical_stamps_after", sa.Integer(), nullable=False),
        sa.Column("visit_snapshot_from_user_id", sa.Uuid(), nullable=True),
        sa.Column("identities_moved", sa.Integer(), nullable=False),
        sa.Column("rewards_moved", sa.Integer(), nullable=False),
        sa.Column("sessions_revoked", sa.Integer(), nullable=False),
        sa.Column("cards_revoked", sa.Integer(), nullable=False),
        sa.Column("source_staff_rebound", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "source_user_id <> canonical_user_id",
            name=op.f("ck_customer_merges_distinct_users"),
        ),
        sa.CheckConstraint(
            "points_transferred >= 0 AND source_points_before >= 0 "
            "AND canonical_points_before >= 0 AND canonical_points_after >= 0",
            name=op.f("ck_customer_merges_non_negative_point_totals"),
        ),
        sa.CheckConstraint(
            "stamps_transferred >= 0 AND source_stamps_before >= 0 "
            "AND canonical_stamps_before >= 0 AND canonical_stamps_after >= 0",
            name=op.f("ck_customer_merges_non_negative_stamp_totals"),
        ),
        sa.CheckConstraint(
            "identities_moved >= 0 AND rewards_moved >= 0 "
            "AND sessions_revoked >= 0 AND cards_revoked >= 0",
            name=op.f("ck_customer_merges_non_negative_merge_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["source_user_id"],
            ["users.id"],
            name=op.f("fk_customer_merges_source_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_user_id"],
            ["users.id"],
            name=op.f("fk_customer_merges_canonical_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_customer_merges_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_staff_id"],
            ["staff_members.id"],
            name=op.f("fk_customer_merges_actor_staff_id_staff_members"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_points_operation_id"],
            ["loyalty_operations.id"],
            name=op.f("fk_customer_merges_source_points_operation_id_loyalty_operations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_points_operation_id"],
            ["loyalty_operations.id"],
            name=op.f("fk_customer_merges_canonical_points_operation_id_loyalty_operations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visit_snapshot_from_user_id"],
            ["users.id"],
            name=op.f("fk_customer_merges_visit_snapshot_from_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_merges")),
        sa.UniqueConstraint(
            "source_user_id",
            name=op.f("uq_customer_merges_source_user_id"),
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name=op.f("uq_customer_merges_idempotency_key"),
        ),
        sa.UniqueConstraint(
            "source_points_operation_id",
            name=op.f("uq_customer_merges_source_points_operation_id"),
        ),
        sa.UniqueConstraint(
            "canonical_points_operation_id",
            name=op.f("uq_customer_merges_canonical_points_operation_id"),
        ),
    )
    op.create_index(
        "ix_customer_merges_canonical_created",
        "customer_merges",
        ["canonical_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_customer_merges_actor_created",
        "customer_merges",
        ["actor_staff_id", "created_at"],
        unique=False,
    )


def _replace_enum_constraint(
    table_name: str,
    column_name: str,
    enum_name: str,
    values: tuple[str, ...],
) -> None:
    constraint_name = op.f(f"ck_{table_name}_{enum_name}")
    op.drop_constraint(constraint_name, table_name, type_="check")
    allowed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(
        constraint_name,
        table_name,
        f"{column_name} IN ({allowed})",
    )


def downgrade() -> None:
    # Lineage plus paired immutable journals cannot be removed without making
    # completed merges inexplicable. Restore the pre-upgrade backup instead.
    raise RuntimeError("0010 downgrade is intentionally unsupported")

"""Add employee allowance policies, monthly lots and immutable allocations."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "staff_benefit_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "staff_id", sa.Uuid(), sa.ForeignKey("staff_members.id"), nullable=False, unique=True
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("monthly_points", sa.BigInteger(), nullable=False),
        sa.Column("minor_units_per_point", sa.BigInteger(), nullable=False),
        sa.Column("all_items", sa.Boolean(), nullable=False),
        sa.Column("item_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("monthly_points > 0", name="positive_monthly_points"),
        sa.CheckConstraint("minor_units_per_point > 0", name="positive_point_value"),
    )
    op.create_table(
        "staff_benefit_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("staff_id", sa.Uuid(), sa.ForeignKey("staff_members.id"), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("initial_points", sa.BigInteger(), nullable=False),
        sa.Column("remaining_points", sa.BigInteger(), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("staff_id", "period", name="staff_benefit_month"),
        sa.CheckConstraint("initial_points > 0", name="positive_initial_points"),
        sa.CheckConstraint("remaining_points BETWEEN 0 AND initial_points", name="valid_remaining"),
        sa.CheckConstraint("expires_at > earned_at", name="expiry_after_grant"),
    )
    op.create_index("ix_staff_benefit_grants_staff_id", "staff_benefit_grants", ["staff_id"])
    op.create_index("ix_staff_benefit_grants_expires_at", "staff_benefit_grants", ["expires_at"])
    op.create_table(
        "staff_benefit_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("staff_id", sa.Uuid(), sa.ForeignKey("staff_members.id"), nullable=False),
        sa.Column("grant_id", sa.Uuid(), sa.ForeignKey("staff_benefit_grants.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("reward_id", sa.Uuid(), sa.ForeignKey("rewards.id"), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("staff_id", "idempotency_key", name="staff_benefit_operation_key"),
        sa.CheckConstraint("kind IN ('grant', 'spend', 'expire')", name="valid_kind"),
        sa.CheckConstraint("balance_after >= 0", name="non_negative_balance"),
        sa.CheckConstraint(
            "(kind = 'grant' AND delta > 0) OR (kind <> 'grant' AND delta < 0)", name="valid_delta"
        ),
    )
    op.create_index(
        "ix_staff_benefit_operations_staff_id", "staff_benefit_operations", ["staff_id"]
    )
    op.create_index(
        "ix_staff_benefit_operations_grant_id", "staff_benefit_operations", ["grant_id"]
    )


def downgrade() -> None:
    raise RuntimeError("Staff benefit journals are immutable; restore a backup to roll back")

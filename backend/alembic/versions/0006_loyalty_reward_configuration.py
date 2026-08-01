"""configure visit and stamp rewards, including automatic point bonuses

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REWARD_TYPES = (
    "free_product",
    "percent_discount",
    "fixed_discount",
    "free_option",
    "text",
    "points",
)


def _replace_reward_type_constraint(
    table_name: str,
    column_name: str,
    *,
    constraint_suffix: str | None = None,
) -> None:
    constraint_name = op.f(f"ck_{table_name}_{constraint_suffix or column_name}")
    op.drop_constraint(constraint_name, table_name, type_="check")
    allowed = ", ".join(f"'{value}'" for value in REWARD_TYPES)
    op.create_check_constraint(
        constraint_name,
        table_name,
        f"{column_name} IN ({allowed})",
    )


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint(
        op.f("uq_audit_events_idempotency_key"),
        "audit_events",
        ["idempotency_key"],
    )

    op.add_column(
        "reward_templates",
        sa.Column("source_menu_item_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_reward_templates_source_menu_item_id_menu_items"),
        "reward_templates",
        "menu_items",
        ["source_menu_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_reward_templates_source_menu_item_id"),
        "reward_templates",
        ["source_menu_item_id"],
        unique=False,
    )

    _replace_reward_type_constraint("reward_templates", "reward_type")
    _replace_reward_type_constraint(
        "rewards",
        "reward_type",
        constraint_suffix="issued_reward_type",
    )
    op.drop_constraint(
        op.f("ck_reward_templates_non_negative_value"),
        "reward_templates",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_reward_templates_valid_value"),
        "reward_templates",
        "(value_int IS NULL OR value_int >= 0) AND (reward_type <> 'points' OR value_int > 0)",
    )

    op.add_column(
        "loyalty_operations",
        sa.Column(
            "reward_bonus_points",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_loyalty_operations_non_negative_reward_bonus_points"),
        "loyalty_operations",
        "reward_bonus_points >= 0",
    )


def downgrade() -> None:
    # Configured templates and immutable point-operation history may use these
    # fields. Removing them would either lose configuration or rewrite history.
    raise RuntimeError("0006 downgrade is intentionally unsupported")

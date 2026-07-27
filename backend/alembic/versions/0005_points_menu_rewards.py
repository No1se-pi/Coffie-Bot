"""add menu purchases for points and opaque reward QR codes

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPERATION_TYPES = (
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
)


def upgrade() -> None:
    op.add_column("menu_categories", sa.Column("icon_media_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_menu_categories_icon_media_id_media_files"),
        "menu_categories",
        "media_files",
        ["icon_media_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("menu_items", sa.Column("points_price", sa.BigInteger(), nullable=True))
    op.add_column(
        "menu_items",
        sa.Column("points_reward_template_id", sa.Uuid(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_menu_items_positive_points_price"),
        "menu_items",
        "points_price IS NULL OR points_price > 0",
    )
    op.create_foreign_key(
        op.f("fk_menu_items_points_reward_template_id_reward_templates"),
        "menu_items",
        "reward_templates",
        ["points_reward_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("rewards", sa.Column("qr_payload", sa.String(length=160), nullable=True))
    op.create_unique_constraint(op.f("uq_rewards_qr_payload"), "rewards", ["qr_payload"])

    op.drop_constraint(
        op.f("ck_loyalty_operations_loyalty_operation_type"),
        "loyalty_operations",
        type_="check",
    )
    allowed = ", ".join(f"'{value}'" for value in OPERATION_TYPES)
    op.create_check_constraint(
        op.f("ck_loyalty_operations_loyalty_operation_type"),
        "loyalty_operations",
        f"operation_type IN ({allowed})",
    )


def downgrade() -> None:
    # Point-purchase operations and issued rewards are immutable business history.
    # Removing their schema would require deleting that history, so downgrade is
    # intentionally non-destructive and unsupported.
    pass

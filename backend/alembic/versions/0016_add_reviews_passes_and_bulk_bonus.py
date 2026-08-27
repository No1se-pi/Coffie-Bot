"""add reviews passes and bulk bonus

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_loyalty_operations_loyalty_operation_type"),
        "loyalty_operations",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_loyalty_operations_loyalty_operation_type"),
        "loyalty_operations",
        "operation_type IN ('purchase_accrual', 'points_redemption', "
        "'points_product_purchase', 'welcome_bonus', 'admin_adjustment', "
        "'bulk_bonus', 'operation_reversal', 'points_expiration', 'visit_mark', "
        "'stamp_added', 'reward_created', 'reward_redeemed', 'reward_cancelled', "
        "'account_merge_debit', 'account_merge_credit', 'wallet_transfer_debit', "
        "'wallet_transfer_credit')",
    )
    op.drop_constraint(op.f("ck_point_lots_point_lot_source_type"), "point_lots", type_="check")
    op.create_check_constraint(
        op.f("ck_point_lots_point_lot_source_type"),
        "point_lots",
        "source_type IN ('opening_balance', 'accrual', 'welcome_bonus', "
        "'reward_bonus', 'admin_adjustment', 'bulk_bonus', 'reversal', "
        "'wallet_transfer', 'account_merge')",
    )
    op.create_table(
        "public_reviews",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("employee_staff_id", sa.Uuid(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("author_display_name", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "hidden",
                name="public_review_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("moderation_note", sa.Text(), nullable=True),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("moderated_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 5", name=op.f("ck_public_reviews_rating_between_1_and_5")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["customer_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["employee_staff_id"], ["staff_members.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["moderated_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "order_id", name="user_order_review"),
    )
    op.create_index("ix_public_reviews_public", "public_reviews", ["status", "created_at"])
    op.create_index("ix_public_reviews_user_created", "public_reviews", ["user_id", "created_at"])
    op.create_index("ix_public_reviews_venue_created", "public_reviews", ["venue_id", "created_at"])

    op.create_table(
        "pass_templates",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("image_media_id", sa.Uuid(), nullable=True),
        sa.Column("total_uses", sa.Integer(), nullable=False),
        sa.Column("validity_days", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by_staff_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("total_uses > 0", name=op.f("ck_pass_templates_positive_total_uses")),
        sa.CheckConstraint(
            "validity_days > 0", name=op.f("ck_pass_templates_positive_validity_days")
        ),
        sa.ForeignKeyConstraint(["image_media_id"], ["media_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pass_templates_active_created", "pass_templates", ["is_active", "created_at"]
    )
    for table_name, target_table, target_column in (
        ("pass_template_venues", "venues", "venue_id"),
        ("pass_template_categories", "menu_categories", "category_id"),
        ("pass_template_items", "menu_items", "item_id"),
    ):
        op.create_table(
            table_name,
            sa.Column("template_id", sa.Uuid(), nullable=False),
            sa.Column(target_column, sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(["template_id"], ["pass_templates.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint([target_column], [f"{target_table}.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("template_id", target_column),
        )

    op.create_table(
        "customer_passes",
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("description_snapshot", sa.Text(), nullable=False),
        sa.Column("image_media_id_snapshot", sa.Uuid(), nullable=True),
        sa.Column("total_uses", sa.Integer(), nullable=False),
        sa.Column("remaining_uses", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "exhausted",
                "expired",
                "cancelled",
                name="customer_pass_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by_staff_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancellation_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("cancellation_request_hash", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "total_uses > 0 AND remaining_uses >= 0 AND remaining_uses <= total_uses",
            name=op.f("ck_customer_passes_valid_use_balance"),
        ),
        sa.CheckConstraint(
            "expires_at > issued_at", name=op.f("ck_customer_passes_expiration_after_issue")
        ),
        sa.ForeignKeyConstraint(["template_id"], ["pass_templates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["image_media_id_snapshot"], ["media_files.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["issued_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["cancelled_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issued_by_staff_id", "idempotency_key", name="staff_pass_issue_key"),
        sa.UniqueConstraint(
            "cancelled_by_staff_id",
            "cancellation_idempotency_key",
            name="staff_pass_cancel_key",
        ),
    )
    op.create_index(
        "ix_customer_passes_user_status", "customer_passes", ["user_id", "status", "expires_at"]
    )
    op.create_table(
        "pass_usages",
        sa.Column("pass_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_staff_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("uses_before", sa.Integer(), nullable=False),
        sa.Column("uses_after", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "uses_before > uses_after AND uses_after >= 0",
            name=op.f("ck_pass_usages_decrements_once"),
        ),
        sa.ForeignKeyConstraint(["pass_id"], ["customer_passes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_staff_id"], ["staff_members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["item_id"], ["menu_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_staff_id", "idempotency_key", name="staff_pass_usage_key"),
    )
    op.create_index("ix_pass_usages_pass_created", "pass_usages", ["pass_id", "created_at"])

    op.create_table(
        "bulk_bonus_batches",
        sa.Column(
            "status",
            sa.Enum(
                "completed",
                name="bulk_bonus_status",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("points_per_user", sa.BigInteger(), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False),
        sa.Column("total_points", sa.BigInteger(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=True),
        sa.Column("audience_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_staff_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "points_per_user > 0", name=op.f("ck_bulk_bonus_batches_positive_points_per_user")
        ),
        sa.CheckConstraint(
            "recipient_count > 0", name=op.f("ck_bulk_bonus_batches_positive_recipient_count")
        ),
        sa.CheckConstraint(
            "total_points = points_per_user * recipient_count",
            name=op.f("ck_bulk_bonus_batches_valid_total"),
        ),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("created_by_staff_id", "idempotency_key", name="staff_bulk_bonus_key"),
    )
    op.create_table(
        "bulk_bonus_items",
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation_id", sa.Uuid(), nullable=False),
        sa.Column("points", sa.BigInteger(), nullable=False),
        sa.Column("balance_before", sa.BigInteger(), nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["bulk_bonus_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["operation_id"], ["loyalty_operations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "user_id", name="batch_user"),
        sa.UniqueConstraint("operation_id", name="operation"),
    )

    op.drop_constraint(
        op.f("ck_staff_permissions_permission_code"), "staff_permissions", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_staff_permissions_permission_code"),
        "staff_permissions",
        "permission IN ('card.lookup', 'customers.create', 'points.accrue', "
        "'points.redeem', 'visits.mark', 'stamps.add', 'rewards.redeem', "
        "'operations.reverse_own', 'tip_profile.manage_own', 'orders.read', "
        "'orders.manage', 'courier.orders.read', 'courier.orders.claim', "
        "'courier.orders.update', 'receipts.read', 'receipts.manage', "
        "'subscriptions.read', 'subscriptions.manage', 'admin.users.read', "
        "'admin.users.manage', 'admin.staff.manage', 'admin.events.read', "
        "'admin.settings.manage', 'admin.content.manage', 'admin.broadcasts.manage', "
        "'admin.feedback.manage', 'admin.reviews.manage', 'admin.bulk_bonus.manage', "
        "'admin.delivery.manage', 'owner.admins.manage', 'owner.export_data', "
        "'owner.critical_settings')",
    )


def downgrade() -> None:
    # Public moderation, pass usage, and bonus ledgers are business history.
    raise RuntimeError("0016 downgrade is intentionally unsupported")

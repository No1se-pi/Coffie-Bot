"""add location maps and delivery radius

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pass_templates",
        sa.Column("price_minor", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "pass_templates",
        sa.Column("purchase_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_pass_templates_non_negative_price"),
        "pass_templates",
        "price_minor >= 0",
    )
    op.create_table(
        "pass_purchases",
        sa.Column("number", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name_snapshot", sa.String(length=200), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column(
            "payment_method",
            sa.Enum(
                "cash",
                "card_on_receipt",
                name="pass_purchase_payment_method",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("customer_pass_id", sa.Uuid(), nullable=True),
        sa.Column("confirmed_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("price_minor >= 0", name=op.f("ck_pass_purchases_non_negative_price")),
        sa.CheckConstraint(
            "status IN ('pending', 'paid', 'cancelled')",
            name=op.f("ck_pass_purchases_valid_status"),
        ),
        sa.ForeignKeyConstraint(["template_id"], ["pass_templates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_pass_id"], ["customer_passes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["confirmed_by_staff_id"], ["staff_members.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number"),
        sa.UniqueConstraint("customer_pass_id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="user_pass_purchase_key"),
    )
    op.create_index(
        op.f("ix_pass_purchases_status_created"),
        "pass_purchases",
        ["status", "created_at"],
    )
    op.add_column("locations", sa.Column("image_media_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_locations_image_media_id_media_files"),
        "locations",
        "media_files",
        ["image_media_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("delivery_zones", sa.Column("location_id", sa.Uuid(), nullable=True))
    op.add_column("delivery_zones", sa.Column("radius_meters", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_delivery_zones_location_id_locations"),
        "delivery_zones",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_delivery_zones_positive_radius_meters"),
        "delivery_zones",
        "radius_meters IS NULL OR radius_meters > 0",
    )
    op.add_column(
        "customer_orders", sa.Column("delivery_latitude", sa.Numeric(9, 6), nullable=True)
    )
    op.add_column(
        "customer_orders", sa.Column("delivery_longitude", sa.Numeric(9, 6), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("customer_orders", "delivery_longitude")
    op.drop_column("customer_orders", "delivery_latitude")
    op.drop_constraint(
        op.f("ck_delivery_zones_positive_radius_meters"),
        "delivery_zones",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_delivery_zones_location_id_locations"),
        "delivery_zones",
        type_="foreignkey",
    )
    op.drop_column("delivery_zones", "radius_meters")
    op.drop_column("delivery_zones", "location_id")
    op.drop_constraint(
        op.f("fk_locations_image_media_id_media_files"),
        "locations",
        type_="foreignkey",
    )
    op.drop_column("locations", "image_media_id")
    op.drop_index(op.f("ix_pass_purchases_status_created"), table_name="pass_purchases")
    op.drop_table("pass_purchases")
    op.drop_constraint(
        op.f("ck_pass_templates_non_negative_price"), "pass_templates", type_="check"
    )
    op.drop_column("pass_templates", "purchase_enabled")
    op.drop_column("pass_templates", "price_minor")

"""add venue menu, generic modifiers, and practical pricing rules

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_VENUE_ID = UUID("00000000-0000-0000-0000-000000000008")


def upgrade() -> None:
    _ensure_content_has_a_venue()
    _attach_content_to_venues()
    _extend_promotions()
    _create_modifier_tables()
    _create_promotion_target_tables()


def _ensure_content_has_a_venue() -> None:
    # Upgraded V1 installations normally already have the neutral venue from
    # 0008.  The guarded insert also covers an unusual installation with menu
    # content but no physical locations, without adding a fake row on clean DBs.
    op.execute(
        sa.text(
            """
            INSERT INTO venues (
                id, slug, name, description, is_active, sort_order,
                loyalty_points_enabled, loyalty_accrual_basis_points,
                loyalty_rounding_mode
            )
            SELECT
                CAST(:venue_id AS uuid),
                'legacy-venue',
                'Основное заведение',
                'Автоматически создано для существующего меню.',
                true,
                0,
                true,
                1000,
                'floor'
            WHERE NOT EXISTS (SELECT 1 FROM venues)
              AND (
                  EXISTS (SELECT 1 FROM menu_categories)
                  OR EXISTS (SELECT 1 FROM menu_items)
                  OR EXISTS (SELECT 1 FROM promotions)
              )
            """
        ).bindparams(venue_id=str(LEGACY_VENUE_ID))
    )


def _attach_content_to_venues() -> None:
    for table_name in ("menu_categories", "menu_items", "promotions"):
        op.add_column(table_name, sa.Column("venue_id", sa.Uuid(), nullable=True))

    default_venue = """
        COALESCE(
            (
                SELECT location.venue_id
                FROM locations AS location
                WHERE location.is_default = true AND location.venue_id IS NOT NULL
                ORDER BY location.id
                LIMIT 1
            ),
            (
                SELECT venue.id
                FROM venues AS venue
                WHERE venue.archived_at IS NULL
                ORDER BY venue.sort_order, venue.id
                LIMIT 1
            )
        )
    """
    op.execute(sa.text(f"UPDATE menu_categories SET venue_id = {default_venue}"))
    op.execute(
        sa.text(
            """
            UPDATE menu_items AS item
            SET venue_id = category.venue_id
            FROM menu_categories AS category
            WHERE category.id = item.category_id
            """
        )
    )
    op.execute(sa.text(f"UPDATE promotions SET venue_id = {default_venue}"))

    for table_name in ("menu_categories", "menu_items", "promotions"):
        op.alter_column(table_name, "venue_id", existing_type=sa.Uuid(), nullable=False)
        op.create_foreign_key(
            op.f(f"fk_{table_name}_venue_id_venues"),
            table_name,
            "venues",
            ["venue_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.create_unique_constraint(
        op.f("uq_menu_categories_id_venue"),
        "menu_categories",
        ["id", "venue_id"],
    )
    op.create_unique_constraint(
        op.f("uq_menu_items_id_venue"),
        "menu_items",
        ["id", "venue_id"],
    )
    op.create_unique_constraint(
        op.f("uq_promotions_id_venue"),
        "promotions",
        ["id", "venue_id"],
    )
    op.drop_constraint(
        op.f("fk_menu_items_category_id_menu_categories"),
        "menu_items",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_menu_items_category_venue"),
        "menu_items",
        "menu_categories",
        ["category_id", "venue_id"],
        ["id", "venue_id"],
        ondelete="RESTRICT",
    )
    op.drop_index("ix_menu_categories_visible_sort", table_name="menu_categories")
    op.create_index(
        "ix_menu_categories_visible_sort",
        "menu_categories",
        ["venue_id", "is_visible", "sort_order"],
    )
    op.drop_index("ix_menu_items_category_visible_sort", table_name="menu_items")
    op.create_index(
        "ix_menu_items_category_visible_sort",
        "menu_items",
        ["venue_id", "category_id", "is_visible", "sort_order"],
    )


def _extend_promotions() -> None:
    columns = (
        sa.Column("pricing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "action_type",
            sa.Enum(
                "percent_discount",
                "fixed_discount",
                name="promotion_action_type",
                native_enum=False,
                create_constraint=True,
                length=24,
            ),
            nullable=True,
        ),
        sa.Column("discount_value", sa.BigInteger(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stackable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active_from_date", sa.Date(), nullable=True),
        sa.Column("active_to_date", sa.Date(), nullable=True),
        sa.Column("active_weekdays", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("active_time_from", sa.Time(), nullable=True),
        sa.Column("active_time_to", sa.Time(), nullable=True),
        sa.Column("fulfillment_modes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "customer_birthday_only", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("minimum_order_minor", sa.BigInteger(), nullable=False, server_default="0"),
    )
    for column in columns:
        op.add_column("promotions", column)

    op.create_check_constraint(
        op.f("ck_promotions_positive_discount_value"),
        "promotions",
        "discount_value IS NULL OR discount_value > 0",
    )
    op.create_check_constraint(
        op.f("ck_promotions_valid_percent_discount_value"),
        "promotions",
        "action_type <> 'percent_discount' OR discount_value <= 10000",
    )
    op.create_check_constraint(
        op.f("ck_promotions_complete_pricing_action"),
        "promotions",
        "NOT pricing_enabled OR (action_type IS NOT NULL AND discount_value IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_promotions_valid_pricing_date_window"),
        "promotions",
        "active_to_date IS NULL OR active_from_date IS NULL OR active_to_date >= active_from_date",
    )
    op.create_check_constraint(
        op.f("ck_promotions_non_negative_minimum_order"),
        "promotions",
        "minimum_order_minor >= 0",
    )
    op.create_index(
        "ix_promotions_venue_pricing",
        "promotions",
        ["venue_id", "pricing_enabled", "priority"],
    )


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def _create_modifier_tables() -> None:
    op.create_table(
        "modifier_groups",
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("min_selections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_selections", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "min_selections >= 0", name=op.f("ck_modifier_groups_non_negative_min_selections")
        ),
        sa.CheckConstraint(
            "max_selections >= min_selections",
            name=op.f("ck_modifier_groups_valid_selection_range"),
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["venues.id"],
            name=op.f("fk_modifier_groups_venue_id_venues"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_groups")),
        sa.UniqueConstraint("id", "venue_id", name=op.f("uq_modifier_groups_id_venue")),
    )
    op.create_index(
        "ix_modifier_groups_venue_sort",
        "modifier_groups",
        ["venue_id", "is_enabled", "sort_order"],
    )
    op.create_table(
        "modifier_options",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("price_delta_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("allows_quantity", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "price_delta_minor >= 0",
            name=op.f("ck_modifier_options_non_negative_price_delta"),
        ),
        sa.CheckConstraint(
            "max_quantity >= 1", name=op.f("ck_modifier_options_positive_max_quantity")
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["modifier_groups.id"],
            name=op.f("fk_modifier_options_group_id_modifier_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_options")),
    )
    op.create_index(
        "ix_modifier_options_group_sort",
        "modifier_options",
        ["group_id", "is_enabled", "sort_order"],
    )
    op.create_table(
        "menu_item_modifier_groups",
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("modifier_group_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["menu_item_id", "venue_id"],
            ["menu_items.id", "menu_items.venue_id"],
            name=op.f("fk_menu_item_modifier_groups_menu_item_id_venue_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["modifier_group_id", "venue_id"],
            ["modifier_groups.id", "modifier_groups.venue_id"],
            name=op.f("fk_menu_item_modifier_groups_modifier_group_id_venue_id_modifier_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "menu_item_id",
            "modifier_group_id",
            name=op.f("pk_menu_item_modifier_groups"),
        ),
    )


def _create_promotion_target_tables() -> None:
    op.create_table(
        "promotion_menu_categories",
        sa.Column("promotion_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promotion_id", "venue_id"],
            ["promotions.id", "promotions.venue_id"],
            name=op.f("fk_promotion_menu_categories_promotion_id_venue_id_promotions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "venue_id"],
            ["menu_categories.id", "menu_categories.venue_id"],
            name=op.f("fk_promotion_menu_categories_category_id_venue_id_menu_categories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "promotion_id", "category_id", name=op.f("pk_promotion_menu_categories")
        ),
    )
    op.create_table(
        "promotion_menu_items",
        sa.Column("promotion_id", sa.Uuid(), nullable=False),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("venue_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promotion_id", "venue_id"],
            ["promotions.id", "promotions.venue_id"],
            name=op.f("fk_promotion_menu_items_promotion_id_venue_id_promotions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id", "venue_id"],
            ["menu_items.id", "menu_items.venue_id"],
            name=op.f("fk_promotion_menu_items_menu_item_id_venue_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "promotion_id", "menu_item_id", name=op.f("pk_promotion_menu_items")
        ),
    )


def downgrade() -> None:
    # Published menu ownership and pricing references are order snapshot inputs.
    # Releases from 0012 use a full backup restore instead of lossy schema rollback.
    raise RuntimeError("0012 downgrade is intentionally unsupported")

"""add venue foundation and attach legacy locations

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A deterministic identifier makes the compatibility backfill easy to inspect
# in database snapshots.  The row is inserted only on installations that
# already contain locations, so a clean installation does not acquire a fake
# customer-facing brand before its seed is applied.
LEGACY_VENUE_ID = UUID("00000000-0000-0000-0000-000000000008")


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("website", sa.String(length=2048), nullable=True),
        sa.Column("telegram", sa.String(length=2048), nullable=True),
        sa.Column("logo_media_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["logo_media_id"],
            ["media_files.id"],
            name=op.f("fk_venues_logo_media_id_media_files"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venues")),
        sa.UniqueConstraint("slug", name=op.f("uq_venues_slug")),
    )
    op.create_index(
        "ix_venues_public_sort",
        "venues",
        ["is_active", "archived_at", "sort_order"],
        unique=False,
    )
    op.add_column("locations", sa.Column("venue_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_locations_venue_id_venues"),
        "locations",
        "venues",
        ["venue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_locations_venue_active_sort",
        "locations",
        ["venue_id", "is_active", "sort_order"],
        unique=False,
    )

    # Existing installations had physical locations but no brand owner.  A
    # neutral compatibility row preserves every location id and lets new code
    # rely on the relationship immediately; no client-specific brand is baked
    # into a reusable migration.
    op.execute(
        sa.text(
            """
            INSERT INTO venues (
                id, slug, name, description, is_active, sort_order
            )
            SELECT
                CAST(:venue_id AS uuid),
                'legacy-venue',
                'Основное заведение',
                'Автоматически создано при обновлении существующей установки.',
                true,
                0
            WHERE EXISTS (SELECT 1 FROM locations)
            """
        ).bindparams(venue_id=str(LEGACY_VENUE_ID))
    )
    op.execute(
        sa.text(
            """
            UPDATE locations
            SET venue_id = CAST(:venue_id AS uuid)
            WHERE venue_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM venues WHERE id = CAST(:venue_id AS uuid)
              )
            """
        ).bindparams(venue_id=str(LEGACY_VENUE_ID))
    )


def downgrade() -> None:
    # Removing Venue after V2 writes begin would silently detach configuration
    # and future ownership references.  Releases from 0008 onward therefore use
    # database backup/restore instead of pretending this schema is reversible.
    raise RuntimeError("0008 downgrade is intentionally unsupported")

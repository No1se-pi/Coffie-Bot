"""add manually drawn delivery zone polygons

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # JSON keeps the coordinate contract portable while PostgreSQL remains the
    # authoritative store. Existing radius zones receive an empty polygon.
    op.add_column(
        "delivery_zones",
        sa.Column(
            "polygon",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("delivery_zones", "polygon")

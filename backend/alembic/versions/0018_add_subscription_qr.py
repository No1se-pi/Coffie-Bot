"""add opaque QR payloads to issued subscriptions

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("customer_passes", sa.Column("qr_payload", sa.String(length=160)))
    # PostgreSQL provides gen_random_uuid() without an extension on supported
    # production versions. Existing passes receive opaque, non-identifying QR data.
    op.execute(
        "UPDATE customer_passes "
        "SET qr_payload = 'coffee-pass:v1:' || replace(gen_random_uuid()::text, '-', '') "
        "WHERE qr_payload IS NULL"
    )
    op.alter_column("customer_passes", "qr_payload", nullable=False)
    op.create_unique_constraint(
        op.f("uq_customer_passes_qr_payload"), "customer_passes", ["qr_payload"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_customer_passes_qr_payload"), "customer_passes", type_="unique")
    op.drop_column("customer_passes", "qr_payload")

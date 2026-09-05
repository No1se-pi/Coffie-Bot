"""allow verified customer-initiated phone profile merges

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Staff-driven merges keep this value populated. A NULL actor_staff_id is
    # reserved for the verified Telegram contact self-service flow.
    op.alter_column("customer_merges", "actor_staff_id", nullable=True)


def downgrade() -> None:
    # Downgrade is intentionally guarded: removing the feature must not erase
    # immutable merge receipts merely to restore the old constraint.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM customer_merges WHERE actor_staff_id IS NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade 0019 while customer-initiated merges exist';
            END IF;
        END
        $$
        """
    )
    op.alter_column("customer_merges", "actor_staff_id", nullable=False)

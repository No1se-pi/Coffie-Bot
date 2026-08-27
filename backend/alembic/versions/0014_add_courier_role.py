"""add courier role and fixed courier permissions

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Extend constrained string enums without rewriting historical migrations."""

    for table, constraint in (
        ("staff_members", "ck_staff_members_role"),
        ("staff_invites", "ck_staff_invites_invite_role"),
    ):
        op.drop_constraint(op.f(constraint), table, type_="check")
        op.create_check_constraint(
            op.f(constraint),
            table,
            "role IN ('customer', 'staff', 'courier', 'admin', 'owner')",
        )

    constraint = op.f("ck_staff_permissions_permission_code")
    op.drop_constraint(constraint, "staff_permissions", type_="check")
    op.create_check_constraint(
        constraint,
        "staff_permissions",
        "permission IN ('card.lookup', 'customers.create', 'points.accrue', "
        "'points.redeem', 'visits.mark', 'stamps.add', 'rewards.redeem', "
        "'operations.reverse_own', 'tip_profile.manage_own', 'orders.read', "
        "'orders.manage', 'courier.orders.read', 'courier.orders.claim', "
        "'courier.orders.update', 'admin.users.read', 'admin.users.manage', "
        "'admin.staff.manage', 'admin.events.read', 'admin.settings.manage', "
        "'admin.content.manage', 'admin.broadcasts.manage', "
        "'admin.feedback.manage', 'admin.delivery.manage', "
        "'owner.admins.manage', 'owner.export_data', 'owner.critical_settings')",
    )


def downgrade() -> None:
    # Courier rows cannot be represented by the previous role constraint.
    raise RuntimeError("0014 downgrade is intentionally unsupported")

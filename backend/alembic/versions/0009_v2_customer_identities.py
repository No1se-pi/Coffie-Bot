"""separate customer identities and allow phone-only profiles

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IDENTITY_PROVIDERS = ("telegram", "phone", "max")
PERMISSION_CODES = (
    "card.lookup",
    "customers.create",
    "points.accrue",
    "points.redeem",
    "visits.mark",
    "stamps.add",
    "rewards.redeem",
    "operations.reverse_own",
    "tip_profile.manage_own",
    "admin.users.read",
    "admin.users.manage",
    "admin.staff.manage",
    "admin.events.read",
    "admin.settings.manage",
    "admin.content.manage",
    "admin.broadcasts.manage",
    "admin.feedback.manage",
    "owner.admins.manage",
    "owner.export_data",
    "owner.critical_settings",
)


def upgrade() -> None:
    op.create_table(
        "customer_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                *IDENTITY_PROVIDERS,
                name="identity_provider",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_staff_id", sa.Uuid(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "provider_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_customer_identities_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_staff_id"],
            ["staff_members.id"],
            name=op.f("fk_customer_identities_verified_by_staff_id_staff_members"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_identities")),
    )

    # Keep every existing users.id stable. A Python-side UUID is intentionally
    # generated only for the new identity row; no customer/history FK is moved.
    connection = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.Uuid()),
        sa.column("telegram_id", sa.BigInteger()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    identities = sa.table(
        "customer_identities",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("provider", sa.String()),
        sa.column("subject", sa.String()),
        sa.column("is_verified", sa.Boolean()),
        sa.column("verified_at", sa.DateTime(timezone=True)),
        sa.column("last_used_at", sa.DateTime(timezone=True)),
        sa.column("provider_metadata", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    rows = connection.execute(
        sa.select(
            users.c.id,
            users.c.telegram_id,
            users.c.created_at,
            users.c.updated_at,
        ).where(users.c.telegram_id.is_not(None))
    ).mappings()
    for row in rows:
        connection.execute(
            identities.insert().values(
                id=uuid4(),
                user_id=row["id"],
                provider="telegram",
                subject=str(row["telegram_id"]),
                is_verified=True,
                verified_at=row["created_at"],
                last_used_at=row["updated_at"],
                provider_metadata={"migration_source": "users.telegram_id"},
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )

    missing_identities = connection.scalar(
        sa.select(sa.func.count())
        .select_from(users)
        .outerjoin(
            identities,
            sa.and_(
                identities.c.user_id == users.c.id,
                identities.c.provider == "telegram",
            ),
        )
        .where(users.c.telegram_id.is_not(None), identities.c.id.is_(None))
    )
    if missing_identities:
        raise RuntimeError("Telegram identity backfill is incomplete")

    # Build lookup constraints only after the bulk backfill has been verified.
    # This keeps the migration fail-fast without maintaining secondary indexes
    # for every inserted legacy row.
    op.create_unique_constraint(
        op.f("uq_customer_identities_provider_subject"),
        "customer_identities",
        ["provider", "subject"],
    )
    op.create_index(
        "ix_customer_identities_user_provider",
        "customer_identities",
        ["user_id", "provider"],
        unique=False,
    )
    op.create_index(
        "ix_customer_identities_last_used",
        "customer_identities",
        ["provider", "last_used_at"],
        unique=False,
    )

    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    _replace_permission_constraint()


def _replace_permission_constraint() -> None:
    constraint_name = op.f("ck_staff_permissions_permission_code")
    op.drop_constraint(constraint_name, "staff_permissions", type_="check")
    allowed = ", ".join(f"'{value}'" for value in PERMISSION_CODES)
    op.create_check_constraint(
        constraint_name,
        "staff_permissions",
        f"permission IN ({allowed})",
    )


def downgrade() -> None:
    # Phone-only rows cannot be represented by the old NOT NULL Telegram schema.
    # Production rollback therefore uses the documented pre-upgrade backup.
    raise RuntimeError("0009 downgrade is intentionally unsupported")

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.skip("Loyalty V2 migration tests require async PostgreSQL")
    return value


def _deterministic_uuid(value: str) -> UUID:
    digest = hashlib.md5(value.encode(), usedforsecurity=False).hexdigest()
    return UUID(digest)


async def _run_alembic(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        revision,
        cwd=BACKEND_DIR,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise AssertionError(f"Alembic upgrade to {revision} exceeded 30 seconds") from None
    assert process.returncode == 0, (
        f"Alembic upgrade to {revision} failed\n"
        f"stdout:\n{stdout.decode(errors='replace')}\n"
        f"stderr:\n{stderr.decode(errors='replace')}"
    )


async def _create_database(admin_engine: AsyncEngine, database_name: str) -> None:
    # The identifier is generated locally from a UUID and never includes user input.
    async with admin_engine.connect() as connection:
        await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')


async def _drop_database(admin_engine: AsyncEngine, database_name: str) -> None:
    # FORCE only affects connections to this test's unique, explicitly named database.
    async with admin_engine.connect() as connection:
        await connection.exec_driver_sql(f'DROP DATABASE "{database_name}" WITH (FORCE)')


@pytest.mark.asyncio
async def test_upgrade_0010_to_0011_preserves_opening_balances_and_timestamps() -> None:
    base_url = make_url(_database_url())
    database_name = f"coffie_migration_{uuid4().hex}"
    admin_url = base_url.set(database="postgres")
    migration_url = base_url.set(database=database_name)
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    migration_engine: AsyncEngine | None = None
    database_created = False

    positive_user_id = uuid4()
    zero_user_id = uuid4()
    positive_created_at = datetime(2024, 1, 31, 22, 15, 16, 123456, tzinfo=UTC)
    positive_updated_at = datetime(2025, 7, 1, 6, 5, 4, 654321, tzinfo=UTC)
    zero_created_at = datetime(2024, 2, 29, 1, 2, 3, 456789, tzinfo=UTC)
    zero_updated_at = datetime(2024, 3, 1, 4, 5, 6, 987654, tzinfo=UTC)

    try:
        await _create_database(admin_engine, database_name)
        database_created = True
        rendered_migration_url = migration_url.render_as_string(hide_password=False)
        await _run_alembic(rendered_migration_url, "0010")

        migration_engine = create_async_engine(migration_url)
        async with migration_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, telegram_id, first_name, status, created_at, updated_at
                    ) VALUES
                        (:positive_user_id, NULL, 'Positive legacy balance', 'active',
                         :positive_created_at, :positive_updated_at),
                        (:zero_user_id, NULL, 'Zero legacy balance', 'active',
                         :zero_created_at, :zero_updated_at)
                    """
                ),
                {
                    "positive_user_id": positive_user_id,
                    "positive_created_at": positive_created_at,
                    "positive_updated_at": positive_updated_at,
                    "zero_user_id": zero_user_id,
                    "zero_created_at": zero_created_at,
                    "zero_updated_at": zero_updated_at,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO user_loyalty_states (
                        id, user_id, points_balance, visit_streak,
                        allowed_misses_used, stamp_count, version,
                        created_at, updated_at
                    ) VALUES
                        (:positive_state_id, :positive_user_id, 137, 0, 0, 0, 3,
                         :positive_created_at, :positive_updated_at),
                        (:zero_state_id, :zero_user_id, 0, 0, 0, 0, 7,
                         :zero_created_at, :zero_updated_at)
                    """
                ),
                {
                    "positive_state_id": uuid4(),
                    "positive_user_id": positive_user_id,
                    "positive_created_at": positive_created_at,
                    "positive_updated_at": positive_updated_at,
                    "zero_state_id": uuid4(),
                    "zero_user_id": zero_user_id,
                    "zero_created_at": zero_created_at,
                    "zero_updated_at": zero_updated_at,
                },
            )
        await migration_engine.dispose()
        migration_engine = None

        # This regression test owns the 0010 -> 0011 boundary. Later migrations
        # have their own tests and must not change the expected revision here.
        await _run_alembic(rendered_migration_url, "0011")
        migration_engine = create_async_engine(migration_url)
        async with migration_engine.connect() as connection:
            revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
            state_rows = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT user_id, points_balance, version, created_at, updated_at
                        FROM user_loyalty_states
                        WHERE user_id IN (:positive_user_id, :zero_user_id)
                        """
                        ),
                        {
                            "positive_user_id": positive_user_id,
                            "zero_user_id": zero_user_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            wallet_rows = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT id, user_id, venue_id, balance_points, version,
                               created_at, updated_at
                        FROM loyalty_wallets
                        WHERE user_id IN (:positive_user_id, :zero_user_id)
                        """
                        ),
                        {
                            "positive_user_id": positive_user_id,
                            "zero_user_id": zero_user_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            lot_rows = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT id, wallet_id, source_operation_id, source_venue_id,
                               transferred_from_lot_id, source_type, initial_points,
                               remaining_points, earned_at, expires_at, expired_at,
                               expiry_reminder_scheduled_at, created_at, updated_at
                        FROM point_lots
                        WHERE wallet_id IN (
                            SELECT id FROM loyalty_wallets
                            WHERE user_id IN (:positive_user_id, :zero_user_id)
                        )
                        """
                        ),
                        {
                            "positive_user_id": positive_user_id,
                            "zero_user_id": zero_user_id,
                        },
                    )
                )
                .mappings()
                .all()
            )

        assert revision == "0011"
        states = {row["user_id"]: row for row in state_rows}
        assert set(states) == {positive_user_id, zero_user_id}
        assert (
            states[positive_user_id]["points_balance"],
            states[positive_user_id]["version"],
            states[positive_user_id]["created_at"],
            states[positive_user_id]["updated_at"],
        ) == (137, 3, positive_created_at, positive_updated_at)
        assert (
            states[zero_user_id]["points_balance"],
            states[zero_user_id]["version"],
            states[zero_user_id]["created_at"],
            states[zero_user_id]["updated_at"],
        ) == (0, 7, zero_created_at, zero_updated_at)

        wallets = {row["user_id"]: row for row in wallet_rows}
        assert set(wallets) == {positive_user_id, zero_user_id}
        assert (
            wallets[positive_user_id]["id"],
            wallets[positive_user_id]["venue_id"],
            wallets[positive_user_id]["balance_points"],
            wallets[positive_user_id]["version"],
            wallets[positive_user_id]["created_at"],
            wallets[positive_user_id]["updated_at"],
        ) == (
            _deterministic_uuid(f"loyalty-wallet:shared:{positive_user_id}"),
            None,
            137,
            1,
            positive_created_at,
            positive_updated_at,
        )
        assert (
            wallets[zero_user_id]["id"],
            wallets[zero_user_id]["venue_id"],
            wallets[zero_user_id]["balance_points"],
            wallets[zero_user_id]["version"],
            wallets[zero_user_id]["created_at"],
            wallets[zero_user_id]["updated_at"],
        ) == (
            _deterministic_uuid(f"loyalty-wallet:shared:{zero_user_id}"),
            None,
            0,
            1,
            zero_created_at,
            zero_updated_at,
        )

        assert len(lot_rows) == 1
        opening_lot = lot_rows[0]
        assert (
            opening_lot["id"],
            opening_lot["wallet_id"],
            opening_lot["source_operation_id"],
            opening_lot["source_venue_id"],
            opening_lot["transferred_from_lot_id"],
            opening_lot["source_type"],
            opening_lot["initial_points"],
            opening_lot["remaining_points"],
        ) == (
            _deterministic_uuid(f"point-lot:opening:{positive_user_id}"),
            wallets[positive_user_id]["id"],
            None,
            None,
            None,
            "opening_balance",
            137,
            137,
        )
        assert (
            opening_lot["earned_at"],
            opening_lot["expires_at"],
            opening_lot["expired_at"],
            opening_lot["expiry_reminder_scheduled_at"],
            opening_lot["created_at"],
            opening_lot["updated_at"],
        ) == (
            positive_created_at,
            None,
            None,
            None,
            positive_created_at,
            positive_updated_at,
        )
        assert sum(row["balance_points"] for row in wallet_rows) == 137
        assert sum(row["remaining_points"] for row in lot_rows) == 137
    finally:
        if migration_engine is not None:
            await migration_engine.dispose()
        if database_created:
            await _drop_database(admin_engine, database_name)
        await admin_engine.dispose()

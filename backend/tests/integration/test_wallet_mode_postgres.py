from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.models.access import StaffMember, User
from app.models.content import Venue
from app.models.enums import (
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointLotSourceType,
    Role,
    UserStatus,
    WalletMode,
)
from app.models.loyalty import LoyaltyOperation, LoyaltySettings, PointTransaction, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointLot, PointLotRoute, WalletTransfer
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.security.rbac import Actor
from app.services.wallet_mode import WalletModeService

BACKEND_DIR = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("DATABASE_URL with async PostgreSQL is required")
    return value


async def _run_alembic(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        "upgrade",
        "head",
        cwd=BACKEND_DIR,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, (
        f"alembic failed\n{stdout.decode(errors='replace')}\n{stderr.decode(errors='replace')}"
    )


@pytest.mark.asyncio
async def test_mode_switch_conserves_on_postgres_and_routes_inverse_with_same_clock() -> None:
    base_url = make_url(_database_url())
    database_name = f"coffie_mode_{uuid4().hex}"
    admin_engine = create_async_engine(
        base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    database_url = base_url.set(database=database_name)
    engine: AsyncEngine | None = None
    created = False
    try:
        async with admin_engine.connect() as connection:
            await connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created = True
        rendered = database_url.render_as_string(hide_password=False)
        await _run_alembic(rendered)
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        owner_user_id = uuid4()
        owner_staff_id = uuid4()
        customer_id = uuid4()
        master_id = uuid4()
        venue_id = uuid4()
        fallback_id = uuid4()
        attributed_lot_id = uuid4()
        opening_lot_id = uuid4()
        async with sessions() as session, session.begin():
            session.add_all(
                [
                    User(
                        id=owner_user_id,
                        telegram_id=1,
                        first_name="Owner",
                        status=UserStatus.ACTIVE,
                    ),
                    User(
                        id=customer_id,
                        telegram_id=None,
                        first_name="Customer",
                        status=UserStatus.ACTIVE,
                    ),
                    Venue(id=venue_id, slug="venue", name="Venue", is_active=True),
                    Venue(id=fallback_id, slug="fallback", name="Fallback", is_active=True),
                ]
            )
            await session.flush()
            seeded_settings = await session.scalar(
                select(LoyaltySettings).where(LoyaltySettings.singleton_key == "default")
            )
            assert seeded_settings is not None
            seeded_settings.wallet_mode = WalletMode.SHARED
            seeded_settings.welcome_bonus_points = 0
            session.add(
                StaffMember(
                    id=owner_staff_id,
                    user_id=owner_user_id,
                    role=Role.OWNER,
                    is_active=True,
                )
            )
            source = LoyaltyOperation(
                id=uuid4(),
                user_id=customer_id,
                operation_type=LoyaltyOperationType.PURCHASE_ACCRUAL,
                status=OperationStatus.COMMITTED,
                idempotency_key=f"mode-source:{customer_id}",
                request_hash="a" * 64,
                points_delta=30,
                balance_before=0,
                balance_after=30,
                occurred_at=NOW - timedelta(days=30),
            )
            session.add_all(
                [
                    UserLoyaltyState(
                        id=uuid4(),
                        user_id=customer_id,
                        points_balance=50,
                        visit_streak=0,
                        allowed_misses_used=0,
                        stamp_count=0,
                        version=1,
                    ),
                    LoyaltyWallet(
                        id=master_id,
                        user_id=customer_id,
                        venue_id=None,
                        balance_points=50,
                        version=1,
                    ),
                    source,
                ]
            )
            await session.flush()
            session.add_all(
                [
                    PointLot(
                        id=attributed_lot_id,
                        wallet_id=master_id,
                        source_operation_id=source.id,
                        source_venue_id=venue_id,
                        source_type=PointLotSourceType.ACCRUAL,
                        initial_points=30,
                        remaining_points=30,
                        earned_at=NOW - timedelta(days=30),
                        expires_at=NOW + timedelta(days=30),
                        expiry_reminder_scheduled_at=NOW - timedelta(days=1),
                    ),
                    PointLot(
                        id=opening_lot_id,
                        wallet_id=master_id,
                        source_operation_id=None,
                        source_venue_id=None,
                        source_type=PointLotSourceType.OPENING_BALANCE,
                        initial_points=20,
                        remaining_points=20,
                        earned_at=NOW - timedelta(days=60),
                        expires_at=None,
                    ),
                ]
            )

        actor = Actor(
            user_id=owner_user_id,
            telegram_id=1,
            session_id=uuid4(),
            role=Role.OWNER,
            staff_member_id=owner_staff_id,
            permissions=frozenset({PermissionCode.OWNER_CRITICAL_SETTINGS}),
        )
        async with sessions() as session:
            service = WalletModeService(PointLedgerRepository(session))
            preview = await service.preview(
                actor,
                target_mode=WalletMode.SEPARATE,
                fallback_venue_id=fallback_id,
            )
            first = await service.confirm(
                actor,
                target_mode=WalletMode.SEPARATE,
                fallback_venue_id=fallback_id,
                preview_hash=preview.preview_hash,
                reason="Разделение кошельков",
                idempotency_key="mode-separate",
                now=NOW,
            )
            replay = await service.confirm(
                actor,
                target_mode=WalletMode.SEPARATE,
                fallback_venue_id=fallback_id,
                preview_hash=preview.preview_hash,
                reason="Разделение кошельков",
                idempotency_key="mode-separate",
                now=NOW,
            )
        assert first.total_balance_points == 50
        assert replay.idempotent_replay is True

        async with sessions() as session:
            service = WalletModeService(PointLedgerRepository(session))
            inverse_preview = await service.preview(
                actor,
                target_mode=WalletMode.SHARED,
                fallback_venue_id=None,
            )
            inverse = await service.confirm(
                actor,
                target_mode=WalletMode.SHARED,
                fallback_venue_id=None,
                preview_hash=inverse_preview.preview_hash,
                reason="Общий кошелёк",
                idempotency_key="mode-shared",
                now=NOW,
            )
        assert inverse.total_balance_points == 50

        async with sessions() as session:
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == customer_id)
            )
            settings = await session.scalar(
                select(LoyaltySettings).where(LoyaltySettings.singleton_key == "default")
            )
            master = await session.get(LoyaltyWallet, master_id)
            wallet_sum = await session.scalar(
                select(func.sum(LoyaltyWallet.balance_points)).where(
                    LoyaltyWallet.user_id == customer_id
                )
            )
            transfer_count = await session.scalar(select(func.count()).select_from(WalletTransfer))
            route_count = await session.scalar(select(func.count()).select_from(PointLotRoute))
            transfer_transaction_count = await session.scalar(
                select(func.count())
                .select_from(PointTransaction)
                .join(LoyaltyOperation, LoyaltyOperation.id == PointTransaction.operation_id)
                .where(
                    LoyaltyOperation.operation_type.in_(
                        [
                            LoyaltyOperationType.WALLET_TRANSFER_DEBIT,
                            LoyaltyOperationType.WALLET_TRANSFER_CREDIT,
                        ]
                    )
                )
            )
            copied = await session.scalar(
                select(PointLot).where(PointLot.transferred_from_lot_id == attributed_lot_id)
            )
            terminal = await PointLedgerRepository(session).latest_route(opening_lot_id)
        assert state is not None
        assert (state.points_balance, state.version) == (50, 3)
        assert settings is not None
        assert settings.wallet_mode is WalletMode.SHARED
        assert master is not None
        assert master.balance_points == 50
        assert wallet_sum == 50
        assert transfer_count == 4
        assert route_count == 4
        assert transfer_transaction_count == 0
        assert copied is not None
        assert copied.expiry_reminder_scheduled_at == NOW - timedelta(days=1)
        assert terminal is not None
        assert terminal.wallet_id == master_id
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin_engine.connect() as connection:
                await connection.exec_driver_sql(f'DROP DATABASE "{database_name}" WITH (FORCE)')
        await admin_engine.dispose()

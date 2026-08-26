from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    LoyaltyOperationType,
    OperationStatus,
    PointAllocationType,
    PointLotSourceType,
    UserStatus,
)
from app.models.loyalty import LoyaltyOperation, PointTransaction, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointAllocation, PointLot
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.services.point_expiry import PointExpiryService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("DATABASE_URL with async PostgreSQL is required")
    return value


@pytest.mark.asyncio
async def test_expiry_service_materializes_once_and_increments_state_version() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid4()
    wallet_id = uuid4()
    lot_id = uuid4()
    source_operation_id = uuid4()
    try:
        async with sessions() as session, session.begin():
            session.add(
                User(
                    id=user_id,
                    telegram_id=None,
                    first_name="Expiry PG fixture",
                    status=UserStatus.ACTIVE,
                )
            )
            await session.flush()
            session.add_all(
                [
                    UserLoyaltyState(
                        id=uuid4(),
                        user_id=user_id,
                        points_balance=37,
                        visit_streak=0,
                        allowed_misses_used=0,
                        stamp_count=0,
                        version=7,
                    ),
                    LoyaltyWallet(
                        id=wallet_id,
                        user_id=user_id,
                        venue_id=None,
                        balance_points=37,
                        version=3,
                    ),
                    LoyaltyOperation(
                        id=source_operation_id,
                        user_id=user_id,
                        operation_type=LoyaltyOperationType.PURCHASE_ACCRUAL,
                        status=OperationStatus.COMMITTED,
                        idempotency_key=f"expiry-source:{user_id}",
                        request_hash="a" * 64,
                        points_delta=37,
                        balance_before=0,
                        balance_after=37,
                        occurred_at=NOW - timedelta(days=30),
                    ),
                ]
            )
            await session.flush()
            session.add(
                PointLot(
                    id=lot_id,
                    wallet_id=wallet_id,
                    source_operation_id=source_operation_id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=37,
                    remaining_points=37,
                    earned_at=NOW - timedelta(days=30),
                    expires_at=NOW,
                )
            )

        async with sessions() as session:
            first = await PointExpiryService(PointLedgerRepository(session)).process_batch(
                limit=100,
                now=NOW,
            )
            replay = await PointExpiryService(PointLedgerRepository(session)).process_batch(
                limit=100,
                now=NOW,
            )

        async with sessions() as session:
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            wallet = await session.get(LoyaltyWallet, wallet_id)
            lot = await session.get(PointLot, lot_id)
            expiry_operations = list(
                await session.scalars(
                    select(LoyaltyOperation).where(
                        LoyaltyOperation.user_id == user_id,
                        LoyaltyOperation.operation_type == LoyaltyOperationType.POINTS_EXPIRATION,
                    )
                )
            )
            allocation = await session.scalar(
                select(PointAllocation).where(
                    PointAllocation.lot_id == lot_id,
                    PointAllocation.allocation_type == PointAllocationType.EXPIRY,
                )
            )
            outboxes = list(
                await session.scalars(
                    select(NotificationOutbox).where(NotificationOutbox.user_id == user_id)
                )
            )

        assert first.expired == 1
        assert replay.expired == 0
        assert state is not None
        assert (state.points_balance, state.version) == (0, 8)
        assert wallet is not None
        assert (wallet.balance_points, wallet.version) == (0, 4)
        assert lot is not None
        assert (lot.remaining_points, lot.expired_at) == (0, NOW)
        assert len(expiry_operations) == 1
        assert (expiry_operations[0].points_delta, expiry_operations[0].balance_after) == (-37, 0)
        assert allocation is not None
        assert allocation.points == 37
        assert outboxes == []
    finally:
        async with sessions() as session, session.begin():
            operation_ids = list(
                await session.scalars(
                    select(LoyaltyOperation.id).where(LoyaltyOperation.user_id == user_id)
                )
            )
            await session.execute(
                delete(PointAllocation).where(PointAllocation.operation_id.in_(operation_ids))
            )
            await session.execute(
                delete(PointTransaction).where(PointTransaction.operation_id.in_(operation_ids))
            )
            await session.execute(delete(PointLot).where(PointLot.wallet_id == wallet_id))
            await session.execute(delete(AuditEvent).where(AuditEvent.subject_user_id == user_id))
            await session.execute(
                delete(NotificationOutbox).where(NotificationOutbox.user_id == user_id)
            )
            await session.execute(
                delete(LoyaltyOperation).where(LoyaltyOperation.id.in_(operation_ids))
            )
            await session.execute(delete(LoyaltyWallet).where(LoyaltyWallet.id == wallet_id))
            await session.execute(
                delete(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            await session.execute(delete(UserCard).where(UserCard.user_id == user_id))
            await session.execute(delete(User).where(User.id == user_id))
        await engine.dispose()

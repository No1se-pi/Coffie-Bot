"""Real PostgreSQL regressions for journal-preserving Loyalty V2 reversals."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import Location, Venue
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    CardStatus,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointAllocationType,
    PointLotSourceType,
    Role,
    RoundingMode,
    UserStatus,
)
from app.models.loyalty import LoyaltyOperation, PointTransaction, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointAllocation, PointLot
from app.repositories.loyalty import LoyaltyRepository
from app.security.rbac import Actor
from app.services.loyalty import LoyaltyService

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


def _operation(
    user_id: UUID,
    operation_type: LoyaltyOperationType,
    *,
    delta: int,
    marker: str,
) -> LoyaltyOperation:
    return LoyaltyOperation(
        id=uuid4(),
        user_id=user_id,
        operation_type=operation_type,
        status=OperationStatus.COMMITTED,
        idempotency_key=f"reversal-pg:{marker}:{uuid4()}",
        request_hash=uuid4().hex + uuid4().hex,
        points_delta=delta,
        balance_before=None,
        balance_after=None,
        occurred_at=NOW - timedelta(minutes=5),
    )


async def _seed_actor(session_maker: async_sessionmaker) -> Actor:  # type: ignore[type-arg]
    actor_user_id = uuid4()
    actor_staff_id = uuid4()
    async with session_maker() as session, session.begin():
        session.add(
            User(
                id=actor_user_id,
                telegram_id=None,
                first_name="Reversal integration admin",
                status=UserStatus.ACTIVE,
            )
        )
        await session.flush()
        session.add(
            StaffMember(
                id=actor_staff_id,
                user_id=actor_user_id,
                role=Role.ADMIN,
                is_active=True,
            )
        )
    return Actor(
        user_id=actor_user_id,
        telegram_id=1,
        session_id=uuid4(),
        role=Role.ADMIN,
        staff_member_id=actor_staff_id,
        permissions=frozenset({PermissionCode.ADMIN_USERS_MANAGE}),
    )


async def _seed_active_customer(
    session_maker: async_sessionmaker,  # type: ignore[type-arg]
    *,
    balance: int,
) -> tuple[UUID, UUID]:
    user_id = uuid4()
    wallet_id = uuid4()
    async with session_maker() as session, session.begin():
        session.add(
            User(
                id=user_id,
                telegram_id=None,
                first_name="Reversal integration customer",
                status=UserStatus.ACTIVE,
            )
        )
        await session.flush()
        session.add_all(
            [
                UserCard(
                    id=uuid4(),
                    user_id=user_id,
                    qr_token=f"reversal:{uuid4().hex}",
                    short_code=uuid4().hex[:10].upper(),
                    status=CardStatus.ACTIVE,
                ),
                UserLoyaltyState(
                    id=uuid4(),
                    user_id=user_id,
                    points_balance=balance,
                    visit_streak=0,
                    allowed_misses_used=0,
                    stamp_count=0,
                    version=1,
                ),
                LoyaltyWallet(
                    id=wallet_id,
                    user_id=user_id,
                    venue_id=None,
                    balance_points=balance,
                    version=1,
                ),
            ]
        )
    return user_id, wallet_id


@pytest.mark.asyncio
async def test_credit_reversal_follows_merge_lineage_to_canonical_wallet() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = await _seed_actor(sessions)
    canonical_user_id, canonical_wallet_id = await _seed_active_customer(sessions, balance=40)
    source_user_id = uuid4()
    source_wallet_id = uuid4()
    source_lot_id = uuid4()
    canonical_lot_id = uuid4()
    original = _operation(
        source_user_id,
        LoyaltyOperationType.PURCHASE_ACCRUAL,
        delta=40,
        marker="merged-credit",
    )
    async with sessions() as session, session.begin():
        session.add(
            User(
                id=source_user_id,
                telegram_id=None,
                first_name="Merged reversal source",
                status=UserStatus.MERGED,
                merged_into_user_id=canonical_user_id,
                merged_at=NOW - timedelta(minutes=1),
            )
        )
        await session.flush()
        session.add_all(
            [
                UserLoyaltyState(
                    id=uuid4(),
                    user_id=source_user_id,
                    points_balance=0,
                    visit_streak=0,
                    allowed_misses_used=0,
                    stamp_count=0,
                    version=2,
                ),
                LoyaltyWallet(
                    id=source_wallet_id,
                    user_id=source_user_id,
                    venue_id=None,
                    balance_points=0,
                    version=2,
                ),
                original,
            ]
        )
        await session.flush()
        session.add(
            PointLot(
                id=source_lot_id,
                wallet_id=source_wallet_id,
                source_operation_id=original.id,
                source_venue_id=None,
                source_type=PointLotSourceType.ACCRUAL,
                initial_points=40,
                remaining_points=0,
                earned_at=NOW - timedelta(days=2),
                expires_at=NOW + timedelta(days=30),
            )
        )
        await session.flush()
        session.add(
            PointLot(
                id=canonical_lot_id,
                wallet_id=canonical_wallet_id,
                source_operation_id=original.id,
                source_venue_id=None,
                transferred_from_lot_id=source_lot_id,
                source_type=PointLotSourceType.ACCOUNT_MERGE,
                initial_points=40,
                remaining_points=40,
                earned_at=NOW - timedelta(days=2),
                expires_at=NOW + timedelta(days=30),
            )
        )

    try:
        async with sessions() as session:
            outcome = await LoyaltyService(LoyaltyRepository(session)).reverse_operation(
                actor,
                operation_id=original.id,
                reason="Duplicate profile correction",
                idempotency_key=str(uuid4()),
                now=NOW,
            )

        async with sessions() as session:
            source_operation = await session.get(LoyaltyOperation, original.id)
            reversal = await session.get(LoyaltyOperation, outcome.operation_id)
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == canonical_user_id)
            )
            wallet = await session.get(LoyaltyWallet, canonical_wallet_id)
            lot = await session.get(PointLot, canonical_lot_id)
            allocation = await session.scalar(
                select(PointAllocation).where(PointAllocation.operation_id == outcome.operation_id)
            )
            transaction = await session.scalar(
                select(PointTransaction).where(
                    PointTransaction.operation_id == outcome.operation_id
                )
            )

        assert source_operation is not None
        assert source_operation.status is OperationStatus.REVERSED
        assert reversal is not None
        assert (reversal.user_id, reversal.points_delta) == (canonical_user_id, -40)
        assert state is not None
        assert (state.points_balance, state.version) == (0, 2)
        assert wallet is not None
        assert (wallet.balance_points, wallet.version) == (0, 2)
        assert lot is not None
        assert lot.remaining_points == 0
        assert allocation is not None
        assert allocation.allocation_type is PointAllocationType.REVERSAL_DEBIT
        assert transaction is not None
        assert transaction.user_id == canonical_user_id
    finally:
        await _cleanup(
            engine,
            actor_user_id=actor.user_id,
            customer_user_ids={source_user_id, canonical_user_id},
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_spend_reversal_restores_exact_allocation_as_linked_lot() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = await _seed_actor(sessions)
    user_id, wallet_id = await _seed_active_customer(sessions, balance=20)
    source_credit = _operation(
        user_id,
        LoyaltyOperationType.PURCHASE_ACCRUAL,
        delta=70,
        marker="spend-source",
    )
    spend = _operation(
        user_id,
        LoyaltyOperationType.POINTS_REDEMPTION,
        delta=-50,
        marker="spend",
    )
    source_lot_id = uuid4()
    spend_allocation_id = uuid4()
    async with sessions() as session, session.begin():
        session.add_all([source_credit, spend])
        await session.flush()
        session.add(
            PointLot(
                id=source_lot_id,
                wallet_id=wallet_id,
                source_operation_id=source_credit.id,
                source_venue_id=None,
                source_type=PointLotSourceType.ACCRUAL,
                initial_points=70,
                remaining_points=20,
                earned_at=NOW - timedelta(days=3),
                expires_at=NOW + timedelta(days=20),
            )
        )
        await session.flush()
        session.add(
            PointAllocation(
                id=spend_allocation_id,
                operation_id=spend.id,
                lot_id=source_lot_id,
                allocation_type=PointAllocationType.SPEND,
                points=50,
                created_at=NOW - timedelta(minutes=5),
            )
        )

    try:
        async with sessions() as session:
            outcome = await LoyaltyService(LoyaltyRepository(session)).reverse_operation(
                actor,
                operation_id=spend.id,
                reason="Cashier corrected redemption",
                idempotency_key=str(uuid4()),
                now=NOW,
            )

        async with sessions() as session:
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            wallet = await session.get(LoyaltyWallet, wallet_id)
            restored_lot = await session.scalar(
                select(PointLot).where(PointLot.source_operation_id == outcome.operation_id)
            )
            restored = await session.scalar(
                select(PointAllocation).where(PointAllocation.operation_id == outcome.operation_id)
            )

        assert (outcome.points_delta, outcome.balance_before, outcome.balance_after) == (
            50,
            20,
            70,
        )
        assert state is not None
        assert (state.points_balance, state.version) == (70, 2)
        assert wallet is not None
        assert (wallet.balance_points, wallet.version) == (70, 2)
        assert restored_lot is not None
        assert (
            restored_lot.transferred_from_lot_id,
            restored_lot.initial_points,
            restored_lot.remaining_points,
        ) == (source_lot_id, 50, 50)
        assert restored is not None
        assert (
            restored.allocation_type,
            restored.reverses_allocation_id,
            restored.points,
        ) == (PointAllocationType.REVERSAL_RESTORE, spend_allocation_id, 50)
    finally:
        await _cleanup(
            engine,
            actor_user_id=actor.user_id,
            customer_user_ids={user_id},
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_pre_v2_credit_without_lot_fails_closed_without_side_effects() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = await _seed_actor(sessions)
    user_id, wallet_id = await _seed_active_customer(sessions, balance=10)
    legacy = _operation(
        user_id,
        LoyaltyOperationType.PURCHASE_ACCRUAL,
        delta=10,
        marker="legacy-no-lot",
    )
    async with sessions() as session, session.begin():
        session.add(legacy)

    try:
        async with sessions() as session:
            with pytest.raises(AppError) as raised:
                await LoyaltyService(LoyaltyRepository(session)).reverse_operation(
                    actor,
                    operation_id=legacy.id,
                    reason="Legacy correction must be reviewed",
                    idempotency_key=str(uuid4()),
                    now=NOW,
                )
        assert raised.value.code == "reversal_lot_missing"
        assert raised.value.status_code == 409

        async with sessions() as session:
            operation = await session.get(LoyaltyOperation, legacy.id)
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            wallet = await session.get(LoyaltyWallet, wallet_id)
            reversals = list(
                await session.scalars(
                    select(LoyaltyOperation).where(LoyaltyOperation.reversal_of_id == legacy.id)
                )
            )

        assert operation is not None
        assert operation.status is OperationStatus.COMMITTED
        assert state is not None
        assert (state.points_balance, state.version) == (10, 1)
        assert wallet is not None
        assert (wallet.balance_points, wallet.version) == (10, 1)
        assert reversals == []
    finally:
        await _cleanup(
            engine,
            actor_user_id=actor.user_id,
            customer_user_ids={user_id},
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_accrual_uses_one_trusted_location_venue_for_rate_and_provenance() -> None:
    """A forged/stale venue cannot diverge calculation from persisted origin."""

    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor = await _seed_actor(sessions)
    actor = Actor(
        user_id=actor.user_id,
        telegram_id=actor.telegram_id,
        session_id=actor.session_id,
        role=actor.role,
        staff_member_id=actor.staff_member_id,
        permissions=frozenset({PermissionCode.ADMIN_USERS_MANAGE, PermissionCode.POINTS_ACCRUE}),
    )
    user_id, wallet_id = await _seed_active_customer(sessions, balance=0)
    venue_id = uuid4()
    location_id = uuid4()
    async with sessions() as session, session.begin():
        session.add(
            Venue(
                id=venue_id,
                slug=f"trusted-venue-{venue_id.hex}",
                name="Trusted seven percent venue",
                is_active=True,
                loyalty_points_enabled=True,
                loyalty_accrual_basis_points=700,
                loyalty_rounding_mode=RoundingMode.FLOOR,
            )
        )
        await session.flush()
        session.add(
            Location(
                id=location_id,
                venue_id=venue_id,
                slug=f"trusted-location-{location_id.hex}",
                name="Trusted physical location",
                address="Synthetic test address",
                timezone="Europe/Moscow",
                opening_hours={},
                is_default=False,
                is_active=True,
                sort_order=0,
            )
        )

    try:
        async with sessions() as session:
            outcome = await LoyaltyService(LoyaltyRepository(session)).confirm_accrual(
                actor,
                user_id=user_id,
                purchase_amount_minor=10_000,
                location_id=location_id,
                idempotency_key=str(uuid4()),
                now=NOW,
            )

        async with sessions() as session:
            operation = await session.get(LoyaltyOperation, outcome.operation_id)
            lot = await session.scalar(
                select(PointLot).where(PointLot.source_operation_id == outcome.operation_id)
            )
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            wallet = await session.get(LoyaltyWallet, wallet_id)

        assert outcome.points_delta == 7
        assert operation is not None
        assert operation.location_id == location_id
        assert lot is not None
        assert lot.source_venue_id == venue_id
        assert state is not None
        assert state.points_balance == 7
        assert wallet is not None
        assert wallet.balance_points == 7

        async with sessions() as session, session.begin():
            venue = await session.get(Venue, venue_id, with_for_update=True)
            assert venue is not None
            venue.archived_at = NOW
            venue.is_active = False

        async with sessions() as session:
            with pytest.raises(AppError) as raised:
                await LoyaltyService(LoyaltyRepository(session)).confirm_accrual(
                    actor,
                    user_id=user_id,
                    purchase_amount_minor=10_000,
                    location_id=location_id,
                    idempotency_key=str(uuid4()),
                    now=NOW,
                )
        assert raised.value.code == "venue_unavailable"
        assert raised.value.status_code == 422
    finally:
        await _cleanup(
            engine,
            actor_user_id=actor.user_id,
            customer_user_ids={user_id},
        )
        async with engine.begin() as connection:
            await connection.execute(delete(Location).where(Location.id == location_id))
            await connection.execute(delete(Venue).where(Venue.id == venue_id))
        await engine.dispose()


async def _cleanup(
    engine: AsyncEngine,
    *,
    actor_user_id: UUID,
    customer_user_ids: set[UUID],
) -> None:
    """Delete only random aggregates created by this integration module."""

    all_user_ids = customer_user_ids | {actor_user_id}
    operation_ids = select(LoyaltyOperation.id).where(
        LoyaltyOperation.user_id.in_(customer_user_ids)
    )
    wallet_ids = select(LoyaltyWallet.id).where(LoyaltyWallet.user_id.in_(customer_user_ids))
    async with engine.begin() as connection:
        await connection.execute(
            delete(PointAllocation).where(PointAllocation.operation_id.in_(operation_ids))
        )
        await connection.execute(
            delete(PointTransaction).where(PointTransaction.operation_id.in_(operation_ids))
        )
        await connection.execute(delete(PointLot).where(PointLot.wallet_id.in_(wallet_ids)))
        await connection.execute(
            delete(NotificationOutbox).where(NotificationOutbox.user_id.in_(customer_user_ids))
        )
        await connection.execute(
            delete(AuditEvent).where(
                (AuditEvent.actor_user_id == actor_user_id)
                | (AuditEvent.subject_user_id.in_(customer_user_ids))
            )
        )
        await connection.execute(
            delete(LoyaltyOperation).where(LoyaltyOperation.user_id.in_(customer_user_ids))
        )
        await connection.execute(
            delete(LoyaltyWallet).where(LoyaltyWallet.user_id.in_(customer_user_ids))
        )
        await connection.execute(delete(UserCard).where(UserCard.user_id.in_(customer_user_ids)))
        await connection.execute(
            delete(UserLoyaltyState).where(UserLoyaltyState.user_id.in_(customer_user_ids))
        )
        await connection.execute(delete(StaffMember).where(StaffMember.user_id == actor_user_id))
        await connection.execute(delete(User).where(User.id.in_(all_user_ids)))

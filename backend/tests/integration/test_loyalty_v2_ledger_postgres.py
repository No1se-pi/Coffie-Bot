from __future__ import annotations

import asyncio
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
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    CardStatus,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    PointAllocationType,
    PointLotSourceType,
    Role,
    UserStatus,
)
from app.models.loyalty import LoyaltyOperation, PointTransaction, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointAllocation, PointLot
from app.repositories.loyalty import LoyaltyRepository
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.security.rbac import Actor
from app.services.loyalty import LoyaltyService
from app.services.loyalty_calculations import LoyaltyRuleViolation
from app.services.point_ledger import PointLedger

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    if not value.startswith("postgresql+asyncpg://"):
        pytest.skip("Loyalty V2 integration tests require async PostgreSQL")
    return value


def _operation(
    user_id: UUID,
    operation_type: LoyaltyOperationType,
    *,
    delta: int,
    marker: str,
    occurred_at: datetime = NOW,
) -> LoyaltyOperation:
    return LoyaltyOperation(
        id=uuid4(),
        user_id=user_id,
        operation_type=operation_type,
        status=OperationStatus.COMMITTED,
        idempotency_key=f"v2-ledger-test:{marker}:{uuid4()}",
        request_hash=uuid4().hex + uuid4().hex,
        points_delta=delta,
        balance_before=None,
        balance_after=None,
        occurred_at=occurred_at,
    )


async def _seed_wallet(
    engine: AsyncEngine,
    *,
    due_points: int,
    active_points: int,
) -> tuple[UUID, UUID, UUID, UUID]:
    """Commit one isolated aggregate for genuine multi-session lock tests."""

    user_id = uuid4()
    wallet_id = uuid4()
    due_lot_id = uuid4()
    active_lot_id = uuid4()
    source = _operation(
        user_id,
        LoyaltyOperationType.PURCHASE_ACCRUAL,
        delta=due_points + active_points,
        marker="source",
        occurred_at=NOW - timedelta(days=10),
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
        session.add(
            User(
                id=user_id,
                telegram_id=None,
                first_name="Loyalty V2 concurrency fixture",
                status=UserStatus.ACTIVE,
            )
        )
        await session.flush()
        session.add_all(
            [
                UserLoyaltyState(
                    id=uuid4(),
                    user_id=user_id,
                    points_balance=due_points + active_points,
                    visit_streak=0,
                    allowed_misses_used=0,
                    stamp_count=0,
                    version=1,
                ),
                LoyaltyWallet(
                    id=wallet_id,
                    user_id=user_id,
                    venue_id=None,
                    balance_points=due_points + active_points,
                    version=1,
                ),
                source,
            ]
        )
        await session.flush()
        session.add_all(
            [
                PointLot(
                    id=due_lot_id,
                    wallet_id=wallet_id,
                    source_operation_id=source.id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=due_points,
                    remaining_points=due_points,
                    earned_at=NOW - timedelta(days=10),
                    expires_at=NOW,
                ),
                PointLot(
                    id=active_lot_id,
                    wallet_id=wallet_id,
                    source_operation_id=source.id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=active_points,
                    remaining_points=active_points,
                    earned_at=NOW - timedelta(days=5),
                    expires_at=NOW + timedelta(days=5),
                ),
            ]
        )

    return user_id, wallet_id, due_lot_id, active_lot_id


async def _seed_active_wallet(
    engine: AsyncEngine,
    *,
    points: int,
) -> tuple[UUID, UUID, UUID]:
    """Commit one unexpired lot for two-writer spend contention."""

    user_id = uuid4()
    wallet_id = uuid4()
    lot_id = uuid4()
    source = _operation(
        user_id,
        LoyaltyOperationType.PURCHASE_ACCRUAL,
        delta=points,
        marker="active-source",
        occurred_at=NOW - timedelta(days=10),
    )
    async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
        session.add(
            User(
                id=user_id,
                telegram_id=None,
                first_name="Loyalty V2 concurrent spend fixture",
                status=UserStatus.ACTIVE,
            )
        )
        await session.flush()
        session.add_all(
            [
                UserLoyaltyState(
                    id=uuid4(),
                    user_id=user_id,
                    points_balance=points,
                    visit_streak=0,
                    allowed_misses_used=0,
                    stamp_count=0,
                    version=1,
                ),
                LoyaltyWallet(
                    id=wallet_id,
                    user_id=user_id,
                    venue_id=None,
                    balance_points=points,
                    version=1,
                ),
                source,
            ]
        )
        await session.flush()
        session.add(
            PointLot(
                id=lot_id,
                wallet_id=wallet_id,
                source_operation_id=source.id,
                source_venue_id=None,
                source_type=PointLotSourceType.ACCRUAL,
                initial_points=points,
                remaining_points=points,
                earned_at=NOW - timedelta(days=10),
                expires_at=NOW + timedelta(days=10),
            )
        )

    return user_id, wallet_id, lot_id


async def _seed_admin_adjustment_fixture(
    engine: AsyncEngine,
) -> tuple[Actor, UUID, UUID]:
    """Commit an admin plus an active zero-balance customer aggregate."""

    actor_user_id = uuid4()
    actor_staff_id = uuid4()
    target_user_id = uuid4()
    target_wallet_id = uuid4()
    async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
        session.add_all(
            [
                User(
                    id=actor_user_id,
                    telegram_id=None,
                    first_name="Loyalty V2 idempotency admin",
                    status=UserStatus.ACTIVE,
                ),
                User(
                    id=target_user_id,
                    telegram_id=None,
                    first_name="Loyalty V2 idempotency customer",
                    status=UserStatus.ACTIVE,
                ),
            ]
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
        await session.flush()
        session.add_all(
            [
                UserCard(
                    id=uuid4(),
                    user_id=target_user_id,
                    qr_token=f"v2-idempotency:{uuid4().hex}",
                    short_code=uuid4().hex[:10].upper(),
                    status=CardStatus.ACTIVE,
                ),
                UserLoyaltyState(
                    id=uuid4(),
                    user_id=target_user_id,
                    points_balance=0,
                    visit_streak=0,
                    allowed_misses_used=0,
                    stamp_count=0,
                    version=1,
                ),
                LoyaltyWallet(
                    id=target_wallet_id,
                    user_id=target_user_id,
                    venue_id=None,
                    balance_points=0,
                    version=1,
                ),
            ]
        )

    actor = Actor(
        user_id=actor_user_id,
        telegram_id=1,
        session_id=uuid4(),
        role=Role.ADMIN,
        staff_member_id=actor_staff_id,
        permissions=frozenset({PermissionCode.ADMIN_USERS_MANAGE}),
    )
    return actor, target_user_id, target_wallet_id


@pytest.mark.asyncio
async def test_fifo_uses_earned_at_and_id_after_filtering_expired_lots() -> None:
    engine = create_async_engine(_database_url())
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )()
    try:
        user_id = uuid4()
        wallet_id = uuid4()
        tied_lot_ids = sorted((uuid4(), uuid4()))
        due_lot_id = uuid4()
        newer_lot_id = uuid4()
        source = _operation(
            user_id,
            LoyaltyOperationType.PURCHASE_ACCRUAL,
            delta=90,
            marker="fifo-source",
            occurred_at=NOW - timedelta(days=30),
        )
        session.add(
            User(
                id=user_id,
                telegram_id=None,
                first_name="Loyalty V2 FIFO fixture",
                status=UserStatus.ACTIVE,
            )
        )
        await session.flush()
        state = UserLoyaltyState(
            id=uuid4(),
            user_id=user_id,
            points_balance=90,
            visit_streak=0,
            allowed_misses_used=0,
            stamp_count=0,
            version=1,
        )
        wallet = LoyaltyWallet(
            id=wallet_id,
            user_id=user_id,
            venue_id=None,
            balance_points=90,
            version=1,
        )
        session.add_all([state, wallet, source])
        await session.flush()
        session.add_all(
            [
                # This is oldest but unavailable at the exact expiry boundary.
                PointLot(
                    id=due_lot_id,
                    wallet_id=wallet_id,
                    source_operation_id=source.id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=10,
                    remaining_points=10,
                    earned_at=NOW - timedelta(days=30),
                    expires_at=NOW,
                ),
                PointLot(
                    id=tied_lot_ids[1],
                    wallet_id=wallet_id,
                    source_operation_id=source.id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=20,
                    remaining_points=20,
                    earned_at=NOW - timedelta(days=20),
                    expires_at=NOW + timedelta(days=2),
                ),
                PointLot(
                    id=tied_lot_ids[0],
                    wallet_id=wallet_id,
                    source_operation_id=source.id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=30,
                    remaining_points=30,
                    earned_at=NOW - timedelta(days=20),
                    # Expiry order deliberately conflicts with FIFO order.
                    expires_at=NOW + timedelta(days=20),
                ),
                PointLot(
                    id=newer_lot_id,
                    wallet_id=wallet_id,
                    source_operation_id=source.id,
                    source_venue_id=None,
                    source_type=PointLotSourceType.ACCRUAL,
                    initial_points=30,
                    remaining_points=30,
                    earned_at=NOW - timedelta(days=10),
                    expires_at=NOW + timedelta(days=1),
                ),
            ]
        )
        await session.flush()

        repository = PointLedgerRepository(session)
        settings = await repository.get_settings(lock_mode="share")
        locked = await repository.lock_user_state(user_id)
        assert settings is not None
        assert locked is not None
        debit = _operation(
            user_id,
            LoyaltyOperationType.POINTS_REDEMPTION,
            delta=-45,
            marker="fifo-debit",
        )
        session.add(debit)
        await session.flush()

        mutation = await PointLedger(repository).debit_fifo(
            state=locked[1],
            settings=settings,
            operation=debit,
            points=45,
            venue_id=None,
            now=NOW,
        )
        await PointLedger(repository).assert_invariants(locked[1])

        allocations = list(
            await session.scalars(
                select(PointAllocation).where(PointAllocation.operation_id == debit.id)
            )
        )
        by_lot = {allocation.lot_id: allocation.points for allocation in allocations}
        assert by_lot == {tied_lot_ids[0]: 30, tied_lot_ids[1]: 15}
        assert due_lot_id not in by_lot
        assert newer_lot_id not in by_lot
        assert mutation.global_balance_after == 45
        assert wallet.balance_points == 45
        assert locked[1].points_balance == 45
    finally:
        await session.close()
        if outer_transaction.is_active:
            await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_spend_and_expiry_serialize_without_double_consumption() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, wallet_id, due_lot_id, active_lot_id = await _seed_wallet(
        engine,
        due_points=40,
        active_points=40,
    )
    spend_id = uuid4()
    expiry_id = uuid4()

    async def spend() -> None:
        async with sessions() as session, session.begin():
            repository = PointLedgerRepository(session)
            settings = await repository.get_settings(lock_mode="share")
            locked = await repository.lock_user_state(user_id)
            assert settings is not None
            assert locked is not None
            operation = _operation(
                user_id,
                LoyaltyOperationType.POINTS_REDEMPTION,
                delta=-40,
                marker="concurrent-spend",
            )
            operation.id = spend_id
            session.add(operation)
            await session.flush()
            await PointLedger(repository).debit_fifo(
                state=locked[1],
                settings=settings,
                operation=operation,
                points=40,
                venue_id=None,
                now=NOW,
            )
            await PointLedger(repository).assert_invariants(locked[1])

    async def expire() -> None:
        async with sessions() as session, session.begin():
            repository = PointLedgerRepository(session)
            settings = await repository.get_settings(lock_mode="share")
            assert settings is not None
            owner = await repository.lock_lot_owner(due_lot_id)
            assert owner is not None
            operation = _operation(
                user_id,
                LoyaltyOperationType.POINTS_EXPIRATION,
                delta=-40,
                marker="concurrent-expiry",
            )
            operation.id = expiry_id
            session.add(operation)
            await session.flush()
            await PointLedger(repository).expire_lot(
                state=owner.state,
                wallet=owner.wallet,
                lot=owner.lot,
                operation=operation,
                now=NOW,
            )
            await PointLedger(repository).assert_invariants(owner.state)

    try:
        await asyncio.wait_for(asyncio.gather(spend(), expire()), timeout=5)

        async with sessions() as session:
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            wallet = await session.get(LoyaltyWallet, wallet_id)
            due = await session.get(PointLot, due_lot_id)
            active = await session.get(PointLot, active_lot_id)
            allocations = list(
                await session.scalars(
                    select(PointAllocation).where(
                        PointAllocation.operation_id.in_([spend_id, expiry_id])
                    )
                )
            )
            transactions = list(
                await session.scalars(
                    select(PointTransaction).where(
                        PointTransaction.operation_id.in_([spend_id, expiry_id])
                    )
                )
            )
        assert state is not None
        assert state.points_balance == 0
        assert wallet is not None
        assert wallet.balance_points == 0
        assert due is not None
        assert (due.remaining_points, due.expired_at) == (0, NOW)
        assert active is not None
        assert active.remaining_points == 0
        assert {(item.operation_id, item.lot_id, item.allocation_type) for item in allocations} == {
            (spend_id, active_lot_id, PointAllocationType.SPEND),
            (expiry_id, due_lot_id, PointAllocationType.EXPIRY),
        }
        assert len(transactions) == 2
        assert sum(item.delta for item in transactions) == -80
    finally:
        await _cleanup_user(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_admin_adjustment_is_idempotent_and_rejects_hash_reuse() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    actor, target_user_id, target_wallet_id = await _seed_admin_adjustment_fixture(engine)
    idempotency_key = str(uuid4())

    async def adjust(*, delta_points: int, reason: str):  # type: ignore[no-untyped-def]
        async with sessions() as session:
            return await LoyaltyService(LoyaltyRepository(session)).admin_adjust_points(
                actor,
                user_id=target_user_id,
                delta_points=delta_points,
                reason=reason,
                idempotency_key=idempotency_key,
                now=NOW,
            )

    try:
        first, second = await asyncio.wait_for(
            asyncio.gather(
                adjust(delta_points=10, reason="Idempotency regression"),
                adjust(delta_points=10, reason="Idempotency regression"),
            ),
            timeout=5,
        )
        assert first.operation_id == second.operation_id
        assert {first.idempotent_replay, second.idempotent_replay} == {False, True}
        assert (first.balance_before, first.balance_after, first.points_delta) == (0, 10, 10)
        assert (second.balance_before, second.balance_after, second.points_delta) == (0, 10, 10)

        with pytest.raises(AppError) as conflict:
            await asyncio.wait_for(
                adjust(delta_points=11, reason="Idempotency regression changed"),
                timeout=5,
            )
        assert conflict.value.code == "idempotency_conflict"
        assert conflict.value.status_code == 409

        async with sessions() as session:
            operations = list(
                await session.scalars(
                    select(LoyaltyOperation).where(
                        LoyaltyOperation.operation_type == LoyaltyOperationType.ADMIN_ADJUSTMENT,
                        LoyaltyOperation.idempotency_key == idempotency_key,
                    )
                )
            )
            transactions = list(
                await session.scalars(
                    select(PointTransaction).where(
                        PointTransaction.operation_id == first.operation_id
                    )
                )
            )
            lots = list(
                await session.scalars(
                    select(PointLot).where(PointLot.source_operation_id == first.operation_id)
                )
            )
            allocations = list(
                await session.scalars(
                    select(PointAllocation).where(
                        PointAllocation.operation_id == first.operation_id
                    )
                )
            )
            audits = list(
                await session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.object_type == "loyalty_operation",
                        AuditEvent.object_id == first.operation_id,
                    )
                )
            )
            outbox = list(
                await session.scalars(
                    select(NotificationOutbox).where(
                        NotificationOutbox.idempotency_key == f"operation:{first.operation_id}"
                    )
                )
            )
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == target_user_id)
            )
            wallet = await session.get(LoyaltyWallet, target_wallet_id)

        assert len(operations) == 1
        assert (
            operations[0].points_delta,
            operations[0].balance_before,
            operations[0].balance_after,
        ) == (10, 0, 10)
        assert len(transactions) == 1
        assert (
            transactions[0].delta,
            transactions[0].balance_before,
            transactions[0].balance_after,
        ) == (10, 0, 10)
        assert len(lots) == 1
        assert (
            lots[0].source_type,
            lots[0].initial_points,
            lots[0].remaining_points,
        ) == (PointLotSourceType.ADMIN_ADJUSTMENT, 10, 10)
        assert allocations == []
        assert len(audits) == 1
        assert len(outbox) == 1
        assert state is not None
        assert state.points_balance == 10
        assert wallet is not None
        assert wallet.balance_points == 10
    finally:
        await _cleanup_admin_adjustment_fixture(
            engine,
            actor_user_id=actor.user_id,
            target_user_id=target_user_id,
        )
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_spends_commit_once_without_negative_totals() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id, wallet_id, lot_id = await _seed_active_wallet(engine, points=70)
    spend_ids = (uuid4(), uuid4())

    async def spend(operation_id: UUID) -> UUID:
        async with sessions() as session, session.begin():
            repository = PointLedgerRepository(session)
            settings = await repository.get_settings(lock_mode="share")
            locked = await repository.lock_user_state(user_id)
            assert settings is not None
            assert locked is not None
            operation = _operation(
                user_id,
                LoyaltyOperationType.POINTS_REDEMPTION,
                delta=-50,
                marker="concurrent-spend",
            )
            operation.id = operation_id
            session.add(operation)
            await session.flush()
            mutation = await PointLedger(repository).debit_fifo(
                state=locked[1],
                settings=settings,
                operation=operation,
                points=50,
                venue_id=None,
                now=NOW,
            )
            operation.balance_before = mutation.global_balance_before
            operation.balance_after = mutation.global_balance_after
            await PointLedger(repository).assert_invariants(locked[1])
            return operation_id

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(spend(operation_id) for operation_id in spend_ids),
                return_exceptions=True,
            ),
            timeout=5,
        )
        successes = [result for result in results if isinstance(result, UUID)]
        failures = [result for result in results if isinstance(result, BaseException)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], LoyaltyRuleViolation)
        assert failures[0].code == "insufficient_points"

        async with sessions() as session:
            state = await session.scalar(
                select(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
            )
            wallet = await session.get(LoyaltyWallet, wallet_id)
            lot = await session.get(PointLot, lot_id)
            operations = list(
                await session.scalars(
                    select(LoyaltyOperation).where(LoyaltyOperation.id.in_(spend_ids))
                )
            )
            transactions = list(
                await session.scalars(
                    select(PointTransaction).where(PointTransaction.operation_id.in_(spend_ids))
                )
            )
            allocations = list(
                await session.scalars(
                    select(PointAllocation).where(PointAllocation.operation_id.in_(spend_ids))
                )
            )

        assert state is not None
        assert state.points_balance == 20
        assert wallet is not None
        assert wallet.balance_points == 20
        assert lot is not None
        assert lot.remaining_points == 20
        assert len(operations) == 1
        assert (
            operations[0].id,
            operations[0].points_delta,
            operations[0].balance_before,
            operations[0].balance_after,
        ) == (successes[0], -50, 70, 20)
        assert len(transactions) == 1
        assert (
            transactions[0].operation_id,
            transactions[0].delta,
            transactions[0].balance_before,
            transactions[0].balance_after,
        ) == (successes[0], -50, 70, 20)
        assert len(allocations) == 1
        assert (
            allocations[0].operation_id,
            allocations[0].lot_id,
            allocations[0].allocation_type,
            allocations[0].points,
        ) == (successes[0], lot_id, PointAllocationType.SPEND, 50)
    finally:
        await _cleanup_user(engine, user_id)
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_share_locks_overlap_and_exclude_mode_update() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first = sessions()
    second = sessions()
    updater = sessions()
    first_tx = await first.begin()
    second_tx = await second.begin()
    updater_tx = await updater.begin()
    update_task: asyncio.Task[object] | None = None
    try:
        assert await PointLedgerRepository(first).get_settings(lock_mode="share") is not None
        # A second ordinary user mutation must not wait on the first one.
        assert (
            await asyncio.wait_for(
                PointLedgerRepository(second).get_settings(lock_mode="share"),
                timeout=1,
            )
            is not None
        )

        update_task = asyncio.create_task(
            PointLedgerRepository(updater).get_settings(lock_mode="update")
        )
        done, _pending = await asyncio.wait({update_task}, timeout=0.1)
        assert not done, "FOR UPDATE must wait while ordinary mutations hold FOR SHARE"

        await first_tx.rollback()
        await second_tx.rollback()
        assert await asyncio.wait_for(update_task, timeout=2) is not None
    finally:
        if update_task is not None and not update_task.done():
            update_task.cancel()
            await asyncio.gather(update_task, return_exceptions=True)
        if first_tx.is_active:
            await first_tx.rollback()
        if second_tx.is_active:
            await second_tx.rollback()
        if updater_tx.is_active:
            await updater_tx.rollback()
        await first.close()
        await second.close()
        await updater.close()
        await engine.dispose()


async def _cleanup_user(engine: AsyncEngine, user_id: UUID) -> None:
    """Delete only rows owned by this test's random user aggregate."""

    operation_ids = select(LoyaltyOperation.id).where(LoyaltyOperation.user_id == user_id)
    wallet_ids = select(LoyaltyWallet.id).where(LoyaltyWallet.user_id == user_id)
    async with engine.begin() as connection:
        await connection.execute(
            delete(PointAllocation).where(PointAllocation.operation_id.in_(operation_ids))
        )
        await connection.execute(
            delete(PointTransaction).where(PointTransaction.operation_id.in_(operation_ids))
        )
        await connection.execute(delete(PointLot).where(PointLot.wallet_id.in_(wallet_ids)))
        await connection.execute(delete(LoyaltyWallet).where(LoyaltyWallet.user_id == user_id))
        await connection.execute(
            delete(LoyaltyOperation).where(LoyaltyOperation.user_id == user_id)
        )
        await connection.execute(
            delete(UserLoyaltyState).where(UserLoyaltyState.user_id == user_id)
        )
        await connection.execute(delete(User).where(User.id == user_id))


async def _cleanup_admin_adjustment_fixture(
    engine: AsyncEngine,
    *,
    actor_user_id: UUID,
    target_user_id: UUID,
) -> None:
    operation_ids = select(LoyaltyOperation.id).where(LoyaltyOperation.user_id == target_user_id)
    wallet_ids = select(LoyaltyWallet.id).where(LoyaltyWallet.user_id == target_user_id)
    async with engine.begin() as connection:
        await connection.execute(
            delete(PointAllocation).where(PointAllocation.operation_id.in_(operation_ids))
        )
        await connection.execute(
            delete(PointTransaction).where(PointTransaction.operation_id.in_(operation_ids))
        )
        await connection.execute(delete(PointLot).where(PointLot.wallet_id.in_(wallet_ids)))
        await connection.execute(
            delete(LoyaltyWallet).where(LoyaltyWallet.user_id == target_user_id)
        )
        await connection.execute(
            delete(NotificationOutbox).where(NotificationOutbox.user_id == target_user_id)
        )
        await connection.execute(
            delete(AuditEvent).where(
                (AuditEvent.actor_user_id == actor_user_id)
                | (AuditEvent.subject_user_id == target_user_id)
            )
        )
        await connection.execute(
            delete(LoyaltyOperation).where(LoyaltyOperation.user_id == target_user_id)
        )
        await connection.execute(delete(UserCard).where(UserCard.user_id == target_user_id))
        await connection.execute(
            delete(UserLoyaltyState).where(UserLoyaltyState.user_id == target_user_id)
        )
        await connection.execute(delete(StaffMember).where(StaffMember.user_id == actor_user_id))
        await connection.execute(delete(User).where(User.id.in_([actor_user_id, target_user_id])))

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.core.errors import AppError
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.enums import (
    CardStatus,
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    Role,
    RoundingMode,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    UserLoyaltyState,
)
from app.repositories.loyalty import LoyaltyContext, OperationArtifacts
from app.security.rbac import Actor
from app.services.loyalty import LoyaltyRepositoryPort, LoyaltyService


class FakeTransaction:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.repository.release_current_lock()


class FakeRepository:
    def __init__(self, context: LoyaltyContext) -> None:
        self.context = context
        self.operations: dict[tuple[LoyaltyOperationType, str], LoyaltyOperation] = {}
        self.audits: dict[UUID, AuditEvent] = {}
        self.point_transactions: list[PointTransaction] = []
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._held_locks: dict[asyncio.Task[object], asyncio.Lock] = {}

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        lock = self._locks.setdefault((namespace, key), asyncio.Lock())
        await lock.acquire()
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("test must run in an asyncio task")
        self._held_locks[cast(asyncio.Task[object], task)] = lock

    def release_current_lock(self) -> None:
        task = asyncio.current_task()
        if task is None:
            return
        lock = self._held_locks.pop(cast(asyncio.Task[object], task), None)
        if lock is not None:
            lock.release()

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None:
        return self.operations.get((operation_type, idempotency_key))

    async def get_context(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> LoyaltyContext | None:
        assert for_update
        return self.context if self.context.user.id == user_id else None

    async def accrued_points_between(
        self,
        *,
        user_id: UUID,
        started_at: object,
        ended_at: object,
    ) -> int:
        assert user_id == self.context.user.id
        assert started_at != ended_at
        return 0

    def add_all(self, objects: list[object]) -> None:
        for item in objects:
            if isinstance(item, LoyaltyOperation):
                self.operations[(item.operation_type, item.idempotency_key)] = item
            elif isinstance(item, PointTransaction):
                self.point_transactions.append(item)
            elif isinstance(item, AuditEvent) and item.object_id is not None:
                self.audits[item.object_id] = item

    async def flush(self) -> None:
        return None

    async def get_operation_artifacts(self, operation_id: UUID) -> OperationArtifacts:
        return OperationArtifacts(
            visit=None,
            stamp=None,
            rewards=(),
            audit_event=self.audits.get(operation_id),
        )


def loyalty_context(*, large_operation_requires_approval: bool = False) -> LoyaltyContext:
    user_id = uuid4()
    user = User(
        id=user_id,
        telegram_id=1001,
        first_name="Клиент",
        last_name="Тестовый",
        status=UserStatus.ACTIVE,
    )
    card = UserCard(
        id=uuid4(),
        user_id=user_id,
        qr_token="opaque-card-token-for-test",
        short_code="TEST1234",
        status=CardStatus.ACTIVE,
    )
    state = UserLoyaltyState(
        id=uuid4(),
        user_id=user_id,
        points_balance=10,
        visit_streak=0,
        allowed_misses_used=0,
        stamp_count=0,
        version=1,
    )
    settings = LoyaltySettings(
        id=uuid4(),
        singleton_key="default",
        points_enabled=True,
        minor_units_per_point=1_000,
        minimum_purchase_minor=0,
        maximum_purchase_minor=1_000_000,
        rounding_mode=RoundingMode.FLOOR,
        daily_accrual_limit_points=None,
        operation_accrual_limit_points=None,
        large_operation_threshold_minor=(20_000 if large_operation_requires_approval else None),
        large_operation_requires_approval=large_operation_requires_approval,
        timezone="Europe/Moscow",
        business_day_boundary_minutes=240,
    )
    return LoyaltyContext(user=user, card=card, state=state, settings=settings)


def staff_actor(*permissions: PermissionCode) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=9001,
        session_id=uuid4(),
        role=Role.STAFF,
        staff_member_id=uuid4(),
        permissions=frozenset(permissions),
    )


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_without_second_balance_change() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)
    key = str(uuid4())

    first = await service.confirm_accrual(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )
    replay = await service.confirm_accrual(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )

    assert first.operation_id == replay.operation_id
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert context.state.points_balance == 30
    assert len(repository.point_transactions) == 1


@pytest.mark.asyncio
async def test_same_key_with_different_payload_is_conflict() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)
    key = str(uuid4())
    await service.confirm_accrual(
        actor,
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )

    with pytest.raises(AppError) as error:
        await service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=21_000,
            idempotency_key=key,
        )

    assert error.value.status_code == 409
    assert error.value.code == "idempotency_conflict"
    assert context.state.points_balance == 30


@pytest.mark.asyncio
async def test_large_pending_operation_does_not_mutate_snapshot_or_ledger() -> None:
    context = loyalty_context(large_operation_requires_approval=True)
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    result = await service.confirm_accrual(
        staff_actor(PermissionCode.POINTS_ACCRUE),
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=str(uuid4()),
    )

    assert result.operation_status is OperationStatus.PENDING
    assert result.balance_after is None
    assert context.state.points_balance == 10
    assert context.state.version == 1
    assert repository.point_transactions == []


@pytest.mark.asyncio
async def test_concurrent_same_key_is_serialized_to_one_commit() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    actor = staff_actor(PermissionCode.POINTS_ACCRUE)
    key = str(uuid4())

    results = await asyncio.gather(
        service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=key,
        ),
        service.confirm_accrual(
            actor,
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=key,
        ),
    )

    assert {item.idempotent_replay for item in results} == {False, True}
    assert results[0].operation_id == results[1].operation_id
    assert context.state.points_balance == 30
    assert len(repository.point_transactions) == 1


@pytest.mark.asyncio
async def test_idempotency_key_is_scoped_to_actor_and_payload() -> None:
    context = loyalty_context()
    repository = FakeRepository(context)
    service = LoyaltyService(cast(LoyaltyRepositoryPort, repository))
    key = str(uuid4())
    await service.confirm_accrual(
        staff_actor(PermissionCode.POINTS_ACCRUE),
        user_id=context.user.id,
        purchase_amount_minor=20_000,
        idempotency_key=key,
    )

    with pytest.raises(AppError) as error:
        await service.confirm_accrual(
            staff_actor(PermissionCode.POINTS_ACCRUE),
            user_id=context.user.id,
            purchase_amount_minor=20_000,
            idempotency_key=key,
        )

    assert error.value.code == "idempotency_conflict"

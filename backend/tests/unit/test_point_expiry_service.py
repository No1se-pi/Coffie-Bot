from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import pytest

from app.models.access import User
from app.models.audit import AuditEvent
from app.models.delivery import NotificationOutbox
from app.models.enums import LoyaltyOperationType, UserStatus, WalletMode
from app.models.loyalty import LoyaltyOperation, LoyaltySettings, UserLoyaltyState
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.repositories.loyalty_v2 import LockedLotOwner, LotRouteDestination
from app.services.point_expiry import PointExpiryService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class FakeExpiryRepository:
    def __init__(self, *, telegram: bool = True) -> None:
        self.settings = LoyaltySettings(
            id=uuid4(),
            singleton_key="default",
            wallet_mode=WalletMode.SHARED,
            expiry_reminder_days=14,
            points_expiry_months=6,
        )
        self.user = User(
            id=uuid4(),
            telegram_id=(42 if telegram else None),
            first_name="Клиент",
            status=UserStatus.ACTIVE,
        )
        self.state = UserLoyaltyState(
            id=uuid4(),
            user_id=self.user.id,
            points_balance=100,
            visit_streak=0,
            allowed_misses_used=0,
            stamp_count=0,
            version=1,
        )
        self.wallet = LoyaltyWallet(
            id=uuid4(),
            user_id=self.user.id,
            venue_id=None,
            balance_points=100,
            version=1,
        )
        self.due = _lot(self.wallet.id, points=40, expires_at=NOW)
        self.future = _lot(self.wallet.id, points=60, expires_at=NOW + timedelta(days=7))
        self.lots = {self.due.id: self.due, self.future.id: self.future}
        self.operations: dict[tuple[LoyaltyOperationType, str], LoyaltyOperation] = {}
        self.added: list[object] = []
        self.verified = telegram

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None:
        return self.settings

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        assert namespace == "point-expiry"
        assert key.startswith("point-expiry:")

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None:
        return self.operations.get((operation_type, idempotency_key))

    async def due_expiry_lot_ids(self, *, now: datetime, limit: int) -> list[UUID]:
        return [
            lot.id
            for lot in self.lots.values()
            if lot.remaining_points > 0 and lot.expires_at is not None and lot.expires_at <= now
        ][:limit]

    async def due_reminder_lot_ids(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
        limit: int,
    ) -> list[UUID]:
        return [
            lot.id
            for lot in self.lots.values()
            if lot.remaining_points > 0
            and lot.expires_at is not None
            and starts_at < lot.expires_at <= ends_at
            and lot.expiry_reminder_scheduled_at is None
        ][:limit]

    async def lock_lot_owner(self, lot_id: UUID) -> LockedLotOwner | None:
        lot = self.lots.get(lot_id)
        if lot is None:
            return None
        return LockedLotOwner(
            user=self.user,
            state=self.state,
            wallet=self.wallet,
            lot=lot,
        )

    async def has_verified_telegram_identity(self, user_id: UUID) -> bool:
        assert user_id == self.user.id
        return self.verified

    async def wallet_total(self, user_id: UUID) -> int:
        assert user_id == self.user.id
        return self.wallet.balance_points

    async def lot_total(self, wallet_id: UUID) -> int:
        assert wallet_id == self.wallet.id
        return sum(lot.remaining_points for lot in self.lots.values())

    async def list_wallets(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> list[LoyaltyWallet]:
        assert user_id == self.user.id
        return [self.wallet]

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, LoyaltyOperation):
            self.operations[(value.operation_type, value.idempotency_key)] = value

    def add_all(self, values: list[object]) -> None:
        for value in values:
            self.add(value)

    async def flush(self) -> None:
        return None

    # The remaining PointLedger port methods are unused by expiry_lot but keep
    # the fake structurally compatible with the production service boundary.
    async def get_wallet(
        self,
        *,
        user_id: UUID,
        venue_id: UUID | None,
        for_update: bool,
    ) -> LoyaltyWallet | None:
        return self.wallet

    async def get_wallet_by_id(
        self,
        *,
        user_id: UUID,
        wallet_id: UUID,
        for_update: bool,
    ) -> LoyaltyWallet | None:
        return self.wallet

    async def lock_wallets_by_ids(
        self,
        *,
        user_id: UUID,
        wallet_ids: set[UUID],
    ) -> list[LoyaltyWallet]:
        return [self.wallet]

    async def get_lot(self, lot_id: UUID, *, for_update: bool) -> PointLot | None:
        return self.lots.get(lot_id)

    async def list_lots(
        self,
        wallet_id: UUID,
        *,
        for_update: bool,
        remaining_only: bool = False,
    ) -> list[PointLot]:
        return list(self.lots.values())

    async def list_source_lots(
        self,
        operation_id: UUID,
        *,
        for_update: bool,
    ) -> list[PointLot]:
        return []

    async def list_lot_lineage(
        self,
        root_lot_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[PointLot]:
        return []

    async def lock_lots_by_ids(self, lot_ids: set[UUID]) -> list[PointLot]:
        return []

    async def list_operation_allocations(self, operation_id: UUID) -> list[object]:
        return []

    async def latest_route(self, source_lot_id: UUID) -> LotRouteDestination | None:
        return None


def _lot(wallet_id: UUID, *, points: int, expires_at: datetime) -> PointLot:
    return PointLot(
        id=uuid4(),
        wallet_id=wallet_id,
        source_operation_id=uuid4(),
        source_venue_id=None,
        source_type="accrual",
        initial_points=points,
        remaining_points=points,
        earned_at=NOW - timedelta(days=30),
        expires_at=expires_at,
    )


@pytest.mark.asyncio
async def test_expiry_and_reminder_are_atomic_bounded_and_replay_safe() -> None:
    repository = FakeExpiryRepository()
    service = PointExpiryService(repository)

    first = await service.process_batch(limit=10, now=NOW)
    replay = await service.process_batch(limit=10, now=NOW)

    assert (first.expired, first.reminders_scheduled, first.skipped) == (1, 1, 0)
    assert replay.candidates == 0
    assert repository.state.points_balance == 60
    assert repository.state.version == 2
    assert repository.wallet.balance_points == 60
    assert repository.due.remaining_points == 0
    assert repository.due.expired_at == NOW
    assert repository.future.expiry_reminder_scheduled_at == NOW
    operation = next(item for item in repository.added if isinstance(item, LoyaltyOperation))
    assert operation.points_delta == -40
    assert (operation.balance_before, operation.balance_after) == (100, 60)
    assert len([item for item in repository.added if isinstance(item, AuditEvent)]) == 1
    outboxes = [item for item in repository.added if isinstance(item, NotificationOutbox)]
    assert {item.event_type for item in outboxes} == {"points.expired", "points.expiring"}


@pytest.mark.asyncio
async def test_phone_only_expiry_commits_without_creating_retrying_outbox() -> None:
    repository = FakeExpiryRepository(telegram=False)

    result = await PointExpiryService(repository).process_batch(limit=10, now=NOW)

    assert result.expired == 1
    assert result.reminders_scheduled == 1
    assert repository.state.points_balance == 60
    assert not any(isinstance(item, NotificationOutbox) for item in repository.added)

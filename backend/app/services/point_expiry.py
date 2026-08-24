"""Bounded, idempotent point-expiry maintenance for the worker."""

from __future__ import annotations

import hashlib
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.models.audit import AuditEvent
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    AuditSeverity,
    LoyaltyOperationType,
    OperationStatus,
    OutboxStatus,
)
from app.models.loyalty import LoyaltyOperation, LoyaltySettings
from app.repositories.loyalty_v2 import LockedLotOwner
from app.services.point_ledger import PointLedger, PointLedgerRepositoryPort


class PointExpiryRepositoryPort(PointLedgerRepositoryPort, Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None: ...

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None: ...

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None: ...

    async def due_expiry_lot_ids(self, *, now: datetime, limit: int) -> list[UUID]: ...

    async def due_reminder_lot_ids(
        self,
        *,
        starts_at: datetime,
        ends_at: datetime,
        limit: int,
    ) -> list[UUID]: ...

    async def lock_lot_owner(self, lot_id: UUID) -> LockedLotOwner | None: ...

    async def has_verified_telegram_identity(self, user_id: UUID) -> bool: ...


@dataclass(slots=True)
class ExpiryBatchResult:
    candidates: int = 0
    expired: int = 0
    reminders_scheduled: int = 0
    skipped: int = 0


class PointExpiryService:
    """Materialize due lots and notification reminders in bounded batches.

    Candidate reads use the partial due indexes and never scan every customer.
    Each lot is rechecked under the global settings→user/state→wallet→lot lock
    order.  A deterministic operation key makes competing worker processes
    converge on one immutable expiry journal.
    """

    def __init__(self, repository: PointExpiryRepositoryPort) -> None:
        self._repository = repository
        self._ledger = PointLedger(repository)

    async def process_batch(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> ExpiryBatchResult:
        if limit <= 0:
            raise ValueError("expiry batch limit must be positive")
        current_time = _aware_now(now)
        async with self._repository.transaction():
            settings = await self._required_settings(lock_mode="share")
            due_ids = await self._repository.due_expiry_lot_ids(
                now=current_time,
                limit=limit,
            )
            reminder_ids = (
                await self._repository.due_reminder_lot_ids(
                    starts_at=current_time,
                    ends_at=current_time + timedelta(days=settings.expiry_reminder_days),
                    limit=limit,
                )
                if settings.expiry_reminder_days > 0
                else []
            )

        result = ExpiryBatchResult(candidates=len(due_ids) + len(reminder_ids))
        for lot_id in due_ids:
            if await self._expire_one(lot_id, now=current_time):
                result.expired += 1
            else:
                result.skipped += 1
        for lot_id in reminder_ids:
            if await self._schedule_reminder(lot_id, now=current_time):
                result.reminders_scheduled += 1
            else:
                result.skipped += 1
        return result

    async def _expire_one(self, lot_id: UUID, *, now: datetime) -> bool:
        idempotency_key = f"point-expiry:{lot_id}"
        async with self._repository.transaction():
            await self._required_settings(lock_mode="share")
            await self._repository.acquire_idempotency_lock("point-expiry", idempotency_key)
            replay = await self._repository.get_operation_by_idempotency(
                operation_type=LoyaltyOperationType.POINTS_EXPIRATION,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                return False
            owner = await self._repository.lock_lot_owner(lot_id)
            if (
                owner is None
                or owner.lot.remaining_points <= 0
                or owner.lot.expires_at is None
                or owner.lot.expires_at > now
            ):
                return False
            points = owner.lot.remaining_points
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=owner.user.id,
                actor_user_id=None,
                actor_staff_id=None,
                operation_type=LoyaltyOperationType.POINTS_EXPIRATION,
                status=OperationStatus.COMMITTED,
                idempotency_key=idempotency_key,
                request_hash=_event_hash("point-expiry", owner.lot.id, owner.lot.expires_at),
                points_delta=0,
                balance_before=owner.state.points_balance,
                balance_after=owner.state.points_balance,
                reason="Автоматическое сгорание баллов",
                occurred_at=now,
            )
            self._repository.add(operation)
            mutation = await self._ledger.expire_lot(
                state=owner.state,
                wallet=owner.wallet,
                lot=owner.lot,
                operation=operation,
                now=now,
            )
            operation.points_delta = mutation.points_changed
            operation.balance_before = mutation.global_balance_before
            operation.balance_after = mutation.global_balance_after
            owner.state.version += 1
            self._repository.add(
                AuditEvent(
                    id=uuid4(),
                    event_type="points.expired",
                    actor_user_id=None,
                    actor_staff_id=None,
                    subject_user_id=owner.user.id,
                    object_type="point_lot",
                    object_id=owner.lot.id,
                    idempotency_key=f"point-expiry-audit:{owner.lot.id}",
                    event_metadata={
                        "points": points,
                        "operation_id": str(operation.id),
                    },
                    severity=AuditSeverity.INFO,
                    is_suspicious=False,
                )
            )
            if await self._can_notify(owner):
                self._repository.add(
                    _notification(
                        user_id=owner.user.id,
                        event_type="points.expired",
                        idempotency_key=f"point-expired:{owner.lot.id}",
                        payload={
                            "points": points,
                            "operation_id": str(operation.id),
                        },
                    )
                )
            await self._ledger.assert_invariants(owner.state)
            return True

    async def _schedule_reminder(self, lot_id: UUID, *, now: datetime) -> bool:
        async with self._repository.transaction():
            settings = await self._required_settings(lock_mode="share")
            if settings.expiry_reminder_days <= 0:
                return False
            owner = await self._repository.lock_lot_owner(lot_id)
            if (
                owner is None
                or owner.lot.remaining_points <= 0
                or owner.lot.expires_at is None
                or owner.lot.expires_at <= now
                or owner.lot.expires_at > now + timedelta(days=settings.expiry_reminder_days)
                or owner.lot.expiry_reminder_scheduled_at is not None
            ):
                return False
            owner.lot.expiry_reminder_scheduled_at = now
            if await self._can_notify(owner):
                self._repository.add(
                    _notification(
                        user_id=owner.user.id,
                        event_type="points.expiring",
                        idempotency_key=f"point-expiring:{owner.lot.id}",
                        payload={
                            "points": owner.lot.remaining_points,
                            "expires_at": owner.lot.expires_at.isoformat(),
                        },
                    )
                )
            await self._repository.flush()
            return True

    async def _can_notify(self, owner: LockedLotOwner) -> bool:
        # Identity-first delivery avoids creating retrying Telegram jobs for
        # phone-only profiles.  The legacy projection is also required because
        # the existing delivery adapter addresses Telegram through User.
        return (
            owner.user.telegram_id is not None
            and await self._repository.has_verified_telegram_identity(owner.user.id)
        )

    async def _required_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"],
    ) -> LoyaltySettings:
        settings = await self._repository.get_settings(lock_mode=lock_mode)
        if settings is None:
            raise RuntimeError("Loyalty settings are not initialized")
        return settings


def _notification(
    *,
    user_id: UUID,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, object],
) -> NotificationOutbox:
    return NotificationOutbox(
        id=uuid4(),
        user_id=user_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        status=OutboxStatus.PENDING,
        attempts=0,
    )


def _event_hash(namespace: str, lot_id: UUID, expires_at: datetime) -> str:
    return hashlib.sha256(f"{namespace}:{lot_id}:{expires_at.isoformat()}".encode()).hexdigest()


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current

"""Preview/confirm bulk bonus with one immutable point operation per customer."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.delivery import NotificationOutbox
from app.models.engagement import BulkBonusBatch, BulkBonusItem
from app.models.enums import (
    AuditSeverity,
    BulkBonusStatus,
    LoyaltyOperationType,
    OperationStatus,
    OutboxStatus,
    PermissionCode,
    PointLotSourceType,
    WalletMode,
)
from app.models.loyalty import LoyaltyOperation
from app.repositories.bulk_bonus import BulkBonusRepository
from app.security.rbac import Actor
from app.services.point_ledger import PointLedger


@dataclass(frozen=True, slots=True)
class BulkBonusCommand:
    customer_ids: frozenset[UUID]
    points_per_user: int
    reason: str
    venue_id: UUID | None


@dataclass(frozen=True, slots=True)
class BulkBonusPreview:
    customer_ids: tuple[UUID, ...]
    recipient_count: int
    points_per_user: int
    total_points: int
    reason: str
    venue_id: UUID | None
    preview_hash: str


@dataclass(frozen=True, slots=True)
class BulkBonusOutcome:
    batch: BulkBonusBatch
    items: tuple[BulkBonusItem, ...]
    replay: bool


class BulkBonusService:
    def __init__(self, repository: BulkBonusRepository) -> None:
        self._repository = repository
        self._ledger = PointLedger(repository.point_ledger_repository)

    async def preview(self, actor: Actor, command: BulkBonusCommand) -> BulkBonusPreview:
        _require(actor)
        normalized = _validate(command)
        audience = await self._repository.audience(normalized.customer_ids)
        if normalized.customer_ids and len(audience) != len(normalized.customer_ids):
            _validation("bulk_bonus_customer_unavailable", "Некоторые клиенты недоступны")
        if not audience:
            _validation("bulk_bonus_empty_audience", "Не найдено подходящих клиентов")
        return _preview(normalized, audience)

    async def confirm(
        self,
        actor: Actor,
        command: BulkBonusCommand,
        *,
        preview_hash: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> BulkBonusOutcome:
        _require(actor)
        normalized = _validate(command)
        current_time = now or datetime.now(UTC)
        staff_id = _staff_id(actor)
        request_hash = _request_hash(normalized, preview_hash)
        async with self._repository.transaction():
            await self._repository.acquire_lock(staff_id, idempotency_key)
            existing = await self._repository.find_batch(staff_id, idempotency_key)
            if existing is not None:
                if not hmac.compare_digest(existing.request_hash, request_hash):
                    _conflict("idempotency_key_reused", "Ключ уже использован с другими данными")
                return BulkBonusOutcome(
                    existing,
                    tuple(await self._repository.list_items(existing.id)),
                    True,
                )
            audience = await self._repository.audience(normalized.customer_ids)
            locked = await self._repository.lock_audience(audience)
            if [user.id for user, _state in locked] != audience:
                _conflict(
                    "bulk_bonus_audience_changed", "Список клиентов изменился; повторите preview"
                )
            actual_preview = _preview(normalized, audience)
            if not hmac.compare_digest(actual_preview.preview_hash, preview_hash):
                _conflict("bulk_bonus_preview_stale", "Preview устарел; пересчитайте начисление")
            settings = await self._repository.point_ledger_repository.get_settings(
                lock_mode="share"
            )
            if settings is None or not settings.points_enabled:
                _conflict("points_program_disabled", "Балльная программа отключена")
            venue = None
            if normalized.venue_id is not None:
                venue = await self._repository.point_ledger_repository.get_venue(
                    normalized.venue_id
                )
                if venue is None or venue.archived_at is not None or not venue.is_active:
                    _validation("bulk_bonus_venue_unavailable", "Заведение недоступно")
            if settings.wallet_mode is WalletMode.SEPARATE and venue is None:
                _validation(
                    "bulk_bonus_venue_required", "Для раздельных кошельков выберите заведение"
                )
            batch = BulkBonusBatch(
                id=uuid4(),
                status=BulkBonusStatus.COMPLETED,
                reason=normalized.reason,
                points_per_user=normalized.points_per_user,
                recipient_count=len(audience),
                total_points=len(audience) * normalized.points_per_user,
                venue_id=normalized.venue_id,
                audience_hash=_audience_hash(audience),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                created_by_staff_id=staff_id,
            )
            # Persist parent rows explicitly because these append-only models do
            # not expose ORM relationships solely for flush ordering.
            self._repository.add_all([batch])
            await self._repository.flush()
            objects: list[object] = []
            items: list[BulkBonusItem] = []
            for user, state in locked:
                operation = LoyaltyOperation(
                    id=uuid4(),
                    user_id=user.id,
                    actor_user_id=actor.user_id,
                    actor_staff_id=staff_id,
                    operation_type=LoyaltyOperationType.BULK_BONUS,
                    status=OperationStatus.COMMITTED,
                    idempotency_key=f"{idempotency_key}:{user.id}",
                    request_hash=request_hash,
                    points_delta=normalized.points_per_user,
                    balance_before=state.points_balance,
                    balance_after=state.points_balance + normalized.points_per_user,
                    reason=normalized.reason,
                    occurred_at=current_time,
                )
                self._repository.add_all([operation])
                await self._repository.flush()
                mutation = await self._ledger.credit(
                    state=state,
                    settings=settings,
                    operation=operation,
                    points=normalized.points_per_user,
                    source_type=PointLotSourceType.BULK_BONUS,
                    source_venue_id=normalized.venue_id,
                    now=current_time,
                )
                operation.balance_before = mutation.global_balance_before
                operation.balance_after = mutation.global_balance_after
                state.version += 1
                await self._ledger.assert_invariants(state)
                item = BulkBonusItem(
                    id=uuid4(),
                    batch_id=batch.id,
                    user_id=user.id,
                    operation_id=operation.id,
                    points=normalized.points_per_user,
                    balance_before=mutation.global_balance_before,
                    balance_after=mutation.global_balance_after,
                    created_at=current_time,
                )
                items.append(item)
                objects.extend(
                    [
                        item,
                        NotificationOutbox(
                            id=uuid4(),
                            user_id=user.id,
                            event_type="points.bulk_bonus",
                            payload={
                                "operation_id": str(operation.id),
                                "points": normalized.points_per_user,
                                "reason": normalized.reason,
                            },
                            idempotency_key=f"operation:{operation.id}",
                            status=OutboxStatus.PENDING,
                            attempts=0,
                        ),
                    ]
                )
            objects.append(
                AuditEvent(
                    id=uuid4(),
                    event_type="points.bulk_bonus",
                    actor_user_id=actor.user_id,
                    actor_staff_id=staff_id,
                    object_type="bulk_bonus_batch",
                    object_id=batch.id,
                    event_metadata={
                        "recipient_count": batch.recipient_count,
                        "points_per_user": batch.points_per_user,
                        "total_points": batch.total_points,
                    },
                    severity=AuditSeverity.INFO,
                    is_suspicious=False,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return BulkBonusOutcome(batch, tuple(items), False)


def _validate(command: BulkBonusCommand) -> BulkBonusCommand:
    if not 1 <= command.points_per_user <= 1_000_000:
        _validation("invalid_bulk_bonus_points", "Баллы должны быть в диапазоне 1..1000000")
    reason = " ".join(command.reason.split())
    if len(reason) < 3:
        _validation("invalid_bulk_bonus_reason", "Укажите причину начисления")
    if len(command.customer_ids) > 10_000:
        _validation("bulk_bonus_audience_too_large", "Список превышает 10000 клиентов")
    return BulkBonusCommand(command.customer_ids, command.points_per_user, reason, command.venue_id)


def _preview(command: BulkBonusCommand, audience: list[UUID]) -> BulkBonusPreview:
    payload = {
        "customer_ids": [str(value) for value in audience],
        "points_per_user": command.points_per_user,
        "reason": command.reason,
        "venue_id": str(command.venue_id) if command.venue_id else None,
    }
    return BulkBonusPreview(
        customer_ids=tuple(audience),
        recipient_count=len(audience),
        points_per_user=command.points_per_user,
        total_points=len(audience) * command.points_per_user,
        reason=command.reason,
        venue_id=command.venue_id,
        preview_hash=hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
    )


def _audience_hash(audience: list[UUID]) -> str:
    return hashlib.sha256("\n".join(str(value) for value in audience).encode()).hexdigest()


def _request_hash(command: BulkBonusCommand, preview_hash: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "customer_ids": sorted(str(value) for value in command.customer_ids),
                "points": command.points_per_user,
                "reason": command.reason,
                "venue_id": str(command.venue_id) if command.venue_id else None,
                "preview_hash": preview_hash,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _require(actor: Actor) -> None:
    if not actor.can(PermissionCode.ADMIN_BULK_BONUS_MANAGE):
        _forbidden()


def _staff_id(actor: Actor) -> UUID:
    if actor.staff_member_id is None:
        _forbidden()
    return actor.staff_member_id


def _forbidden() -> NoReturn:
    raise AppError(code="forbidden", message="Insufficient permissions", status_code=403)


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)

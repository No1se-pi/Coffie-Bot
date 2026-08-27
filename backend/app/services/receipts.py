"""Fast manual receipt workflow with immutable metadata history and risk signals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.enums import (
    AuditSeverity,
    MediaStatus,
    PermissionCode,
    ReceiptSource,
    ReceiptStatus,
    Role,
    UserStatus,
)
from app.models.receipts import Receipt, ReceiptRevision, ReceiptRiskFlag
from app.repositories.receipts import ReceiptRepository
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class ReceiptCreateCommand:
    user_id: UUID
    venue_id: UUID
    amount_minor: int
    image_media_id: UUID
    receipt_number: str | None = None
    external_id: str | None = None
    fiscal_data: dict[str, Any] | None = None
    note: str | None = None
    source: ReceiptSource = ReceiptSource.MANUAL


@dataclass(frozen=True, slots=True)
class ReceiptEditCommand:
    image_media_id: UUID | None
    receipt_number: str | None
    external_id: str | None
    fiscal_data: dict[str, Any]
    note: str | None


@dataclass(frozen=True, slots=True)
class ReceiptView:
    receipt: Receipt
    customer_name: str
    venue_name: str
    revisions: tuple[ReceiptRevision, ...]
    flags: tuple[ReceiptRiskFlag, ...]
    idempotent_replay: bool = False


class ReceiptService:
    def __init__(self, repository: ReceiptRepository) -> None:
        self._repository = repository

    async def create(
        self,
        actor: Actor,
        command: ReceiptCreateCommand,
        *,
        idempotency_key: str,
    ) -> ReceiptView:
        staff_id = _require_staff(actor, PermissionCode.RECEIPTS_MANAGE)
        if command.amount_minor <= 0:
            _validation("invalid_receipt_amount", "Сумма чека должна быть больше нуля")
        request_hash = _hash(command)
        async with self._repository.transaction():
            await self._repository.acquire_idempotency_lock(staff_id, idempotency_key)
            existing = await self._repository.get_by_idempotency(staff_id, idempotency_key)
            if existing is not None:
                if existing.request_hash != request_hash:
                    _conflict("idempotency_mismatch", "Ключ уже использован с другими данными")
                return await self._view(existing, actor=actor, replay=True)
            customer = await self._repository.get_user(command.user_id)
            if customer is None or customer.status is not UserStatus.ACTIVE:
                _validation("invalid_customer", "Активный клиент не найден")
            venue = await self._repository.get_venue(command.venue_id)
            if venue is None or not venue.is_active:
                _validation("invalid_venue", "Активное заведение не найдено")
            await self._validate_image(command.image_media_id, actor.user_id)
            now = datetime.now(UTC)
            receipt = Receipt(
                id=uuid4(),
                user_id=customer.id,
                venue_id=venue.id,
                amount_minor=command.amount_minor,
                image_media_id=command.image_media_id,
                source=command.source,
                external_id=_clean(command.external_id),
                receipt_number=_clean(command.receipt_number),
                fiscal_data=command.fiscal_data or {},
                note=_clean(command.note),
                status=ReceiptStatus.ACTIVE,
                current_revision=1,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                created_by_staff_id=staff_id,
            )
            revision = self._revision(
                receipt,
                staff_id,
                revision=1,
                key=f"receipt-create:{receipt.id}",
                request_hash=request_hash,
                changes={"created": True},
                now=now,
            )
            self._repository.add_all(
                [receipt, revision, self._audit(actor, receipt, "receipt.created")]
            )
            await self._repository.flush()
            await self._add_risk_flags(receipt, staff_id=staff_id, now=now)
            await self._repository.flush()
            return await self._view(receipt, actor=actor)

    async def edit(
        self,
        actor: Actor,
        receipt_id: UUID,
        command: ReceiptEditCommand,
        *,
        idempotency_key: str,
    ) -> ReceiptView:
        staff_id = _require_staff(actor, PermissionCode.RECEIPTS_MANAGE)
        request_hash = _hash(command)
        revision_key = f"receipt-edit:{actor.user_id}:{idempotency_key}"
        async with self._repository.transaction():
            receipt = await self._repository.get(receipt_id, for_update=True)
            if receipt is None:
                _not_found()
            replay = await self._repository.get_revision_by_key(revision_key)
            if replay is not None:
                if replay.receipt_id != receipt.id or replay.request_hash != request_hash:
                    _conflict("idempotency_mismatch", "Ключ уже использован с другими данными")
                return await self._view(receipt, actor=actor, replay=True)
            if receipt.status is ReceiptStatus.CANCELLED:
                _conflict("receipt_cancelled", "Отменённый чек нельзя изменять")
            if (
                command.image_media_id is not None
                and command.image_media_id != receipt.image_media_id
            ):
                await self._validate_image(command.image_media_id, actor.user_id)
            changes = _changes(receipt, command)
            if not changes:
                _validation("receipt_unchanged", "Данные чека не изменились")
            receipt.image_media_id = command.image_media_id
            receipt.receipt_number = _clean(command.receipt_number)
            receipt.external_id = _clean(command.external_id)
            receipt.fiscal_data = command.fiscal_data
            receipt.note = _clean(command.note)
            receipt.current_revision += 1
            now = datetime.now(UTC)
            self._repository.add_all(
                [
                    self._revision(
                        receipt,
                        staff_id,
                        revision=receipt.current_revision,
                        key=revision_key,
                        request_hash=request_hash,
                        changes=changes,
                        now=now,
                    ),
                    self._audit(
                        actor, receipt, "receipt.edited", metadata={"fields": sorted(changes)}
                    ),
                ]
            )
            if receipt.receipt_number and await self._repository.count_number(
                receipt.receipt_number, excluding_id=receipt.id
            ):
                existing_codes = {
                    flag.code for flag in await self._repository.list_flags(receipt.id)
                }
                if "duplicate_receipt_number" not in existing_codes:
                    self._repository.add(
                        ReceiptRiskFlag(
                            id=uuid4(),
                            receipt_id=receipt.id,
                            code="duplicate_receipt_number",
                            details={},
                        )
                    )
            await self._repository.flush()
            return await self._view(receipt, actor=actor)

    async def cancel(self, actor: Actor, receipt_id: UUID, *, idempotency_key: str) -> ReceiptView:
        staff_id = _require_staff(actor, PermissionCode.RECEIPTS_MANAGE)
        audit_key = f"receipt-cancel:{actor.user_id}:{idempotency_key}"
        async with self._repository.transaction():
            receipt = await self._repository.get(receipt_id, for_update=True)
            if receipt is None:
                _not_found()
            replay = await self._repository.get_audit_by_key(audit_key)
            if replay is not None:
                if replay.object_id != receipt.id:
                    _conflict("idempotency_mismatch", "Ключ уже использован для другого чека")
                return await self._view(receipt, actor=actor, replay=True)
            if receipt.status is ReceiptStatus.CANCELLED:
                _conflict("receipt_cancelled", "Чек уже отменён")
            receipt.status = ReceiptStatus.CANCELLED
            receipt.cancelled_at = datetime.now(UTC)
            receipt.cancelled_by_staff_id = staff_id
            audit = self._audit(actor, receipt, "receipt.cancelled")
            audit.idempotency_key = audit_key
            self._repository.add(audit)
            await self._repository.flush()
            settings = await self._repository.settings()
            cancellations = await self._repository.count_staff_cancellations(
                staff_id, since=datetime.now(UTC) - timedelta(days=1)
            )
            if cancellations >= settings.staff_cancel_day_limit:
                self._repository.add(
                    ReceiptRiskFlag(
                        id=uuid4(),
                        receipt_id=receipt.id,
                        code="frequent_staff_cancellations",
                        details={"limit": settings.staff_cancel_day_limit},
                    )
                )
                await self._repository.flush()
            return await self._view(receipt, actor=actor)

    async def list(self, actor: Actor, *, limit: int) -> list[ReceiptView]:
        _require_staff(actor, PermissionCode.RECEIPTS_READ)
        return [
            await self._view(value, actor=actor)
            for value in await self._repository.list_receipts(limit=limit)
        ]

    async def get(self, actor: Actor, receipt_id: UUID) -> ReceiptView:
        _require_staff(actor, PermissionCode.RECEIPTS_READ)
        receipt = await self._repository.get(receipt_id)
        if receipt is None:
            _not_found()
        return await self._view(receipt, actor=actor)

    async def _validate_image(self, media_id: UUID, actor_user_id: UUID) -> None:
        media = await self._repository.get_media(media_id)
        if (
            media is None
            or media.status is not MediaStatus.ACTIVE
            or media.kind != "receipt"
            or media.uploaded_by_user_id != actor_user_id
        ):
            _validation("invalid_receipt_image", "Загрузите фотографию чека заново")

    async def _add_risk_flags(self, receipt: Receipt, *, staff_id: UUID, now: datetime) -> None:
        settings = await self._repository.settings()
        signals: list[tuple[str, dict[str, Any]]] = []
        if receipt.amount_minor >= settings.high_amount_minor:
            signals.append(("high_amount", {"threshold_minor": settings.high_amount_minor}))
        if (
            await self._repository.count_since(since=now - timedelta(hours=1), staff_id=staff_id)
            >= settings.staff_hour_limit
        ):
            signals.append(("staff_hour_volume", {"limit": settings.staff_hour_limit}))
        if (
            await self._repository.count_since(
                since=now - timedelta(days=1), amount_minor=receipt.amount_minor
            )
            >= settings.same_amount_day_limit
        ):
            signals.append(("repeated_amount", {"limit": settings.same_amount_day_limit}))
        if (
            await self._repository.count_since(
                since=now - timedelta(days=1), user_id=receipt.user_id
            )
            >= settings.customer_day_limit
        ):
            signals.append(("customer_day_volume", {"limit": settings.customer_day_limit}))
        if receipt.receipt_number and await self._repository.count_number(
            receipt.receipt_number, excluding_id=receipt.id
        ):
            signals.append(("duplicate_receipt_number", {}))
        if settings.photo_required and receipt.image_media_id is None:
            signals.append(("missing_photo", {}))
        self._repository.add_all(
            [
                ReceiptRiskFlag(id=uuid4(), receipt_id=receipt.id, code=code, details=details)
                for code, details in signals
            ]
        )

    async def _view(self, receipt: Receipt, *, actor: Actor, replay: bool = False) -> ReceiptView:
        customer = await self._repository.get_user(receipt.user_id)
        venue = await self._repository.get_venue(receipt.venue_id)
        if customer is None or venue is None:
            raise RuntimeError("Receipt references missing customer or venue")
        return ReceiptView(
            receipt=receipt,
            customer_name=" ".join(
                part for part in (customer.first_name, customer.last_name) if part
            ),
            venue_name=venue.name,
            revisions=tuple(await self._repository.list_revisions(receipt.id)),
            flags=(
                tuple(await self._repository.list_flags(receipt.id))
                if actor.role in {Role.ADMIN, Role.OWNER}
                else ()
            ),
            idempotent_replay=replay,
        )

    @staticmethod
    def _revision(
        receipt: Receipt,
        staff_id: UUID,
        *,
        revision: int,
        key: str,
        request_hash: str,
        changes: dict[str, Any],
        now: datetime,
    ) -> ReceiptRevision:
        return ReceiptRevision(
            id=uuid4(),
            receipt_id=receipt.id,
            revision=revision,
            edited_by_staff_id=staff_id,
            image_media_id=receipt.image_media_id,
            receipt_number=receipt.receipt_number,
            external_id=receipt.external_id,
            fiscal_data=receipt.fiscal_data,
            note=receipt.note,
            change_summary=changes,
            idempotency_key=key,
            request_hash=request_hash,
            created_at=now,
        )

    @staticmethod
    def _audit(
        actor: Actor,
        receipt: Receipt,
        event_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        return AuditEvent(
            id=uuid4(),
            event_type=event_type,
            actor_user_id=actor.user_id,
            actor_staff_id=actor.staff_member_id,
            subject_user_id=receipt.user_id,
            object_type="receipt",
            object_id=receipt.id,
            event_metadata={"venue_id": str(receipt.venue_id), **(metadata or {})},
            severity=AuditSeverity.INFO,
            is_suspicious=False,
        )


def _changes(receipt: Receipt, command: ReceiptEditCommand) -> dict[str, Any]:
    values = {
        "image_media_id": command.image_media_id,
        "receipt_number": _clean(command.receipt_number),
        "external_id": _clean(command.external_id),
        "fiscal_data": command.fiscal_data,
        "note": _clean(command.note),
    }
    return {
        field: {"from": str(getattr(receipt, field)), "to": str(value)}
        for field, value in values.items()
        if getattr(receipt, field) != value
    }


def _hash(command: ReceiptCreateCommand | ReceiptEditCommand) -> str:
    payload = asdict(command)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _clean(value: str | None) -> str | None:
    normalized = " ".join((value or "").split()).strip()
    return normalized or None


def _require_staff(actor: Actor, permission: PermissionCode) -> UUID:
    if actor.staff_member_id is None or not actor.can(permission):
        raise AppError(code="forbidden", message="Недостаточно прав", status_code=403)
    return actor.staff_member_id


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _not_found() -> NoReturn:
    raise AppError(code="not_found", message="Чек не найден", status_code=404)

"""Reusable pass issuance and concurrency-safe one-use redemption."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.engagement import (
    CustomerPass,
    PassPurchase,
    PassTemplate,
    PassTemplateCategory,
    PassTemplateItem,
    PassTemplateVenue,
    PassUsage,
)
from app.models.enums import AuditSeverity, PassStatus, PaymentMethod, PermissionCode, Role
from app.repositories.subscriptions import PassRecord, SubscriptionRepository, TemplateAccess
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class TemplateCreateCommand:
    name: str
    description: str
    total_uses: int
    validity_days: int
    price_minor: int
    purchase_enabled: bool
    image_media_id: UUID | None
    venue_ids: frozenset[UUID]
    category_ids: frozenset[UUID]
    item_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class PassOutcome:
    value: CustomerPass
    replay: bool


@dataclass(frozen=True, slots=True)
class UsageOutcome:
    value: PassUsage
    customer_pass: CustomerPass
    replay: bool


class SubscriptionService:
    def __init__(self, repository: SubscriptionRepository) -> None:
        self._repository = repository

    async def create_template(self, actor: Actor, command: TemplateCreateCommand) -> TemplateAccess:
        _require_admin(actor)
        name = _clean(command.name)
        description = _clean(command.description)
        if not name or not description:
            _validation("invalid_pass_template", "Название и описание обязательны")
        existing = await self._repository.existing_entity_ids(
            venue_ids=set(command.venue_ids),
            category_ids=set(command.category_ids),
            item_ids=set(command.item_ids),
        )
        if existing != (set(command.venue_ids), set(command.category_ids), set(command.item_ids)):
            _validation("invalid_pass_scope", "В ограничениях есть неизвестные объекты")
        async with self._repository.transaction():
            template = PassTemplate(
                id=uuid4(),
                name=name,
                description=description,
                image_media_id=command.image_media_id,
                total_uses=command.total_uses,
                validity_days=command.validity_days,
                price_minor=command.price_minor,
                purchase_enabled=command.purchase_enabled,
                is_active=True,
                created_by_staff_id=_staff_id(actor),
            )
            scopes: list[object] = [
                *(
                    PassTemplateVenue(template_id=template.id, venue_id=value)
                    for value in command.venue_ids
                ),
                *(
                    PassTemplateCategory(template_id=template.id, category_id=value)
                    for value in command.category_ids
                ),
                *(
                    PassTemplateItem(template_id=template.id, item_id=value)
                    for value in command.item_ids
                ),
            ]
            self._repository.add_all(
                [
                    template,
                    *scopes,
                    _audit(actor, "subscription.template_created", "pass_template", template.id),
                ]
            )
            await self._repository.flush()
            return TemplateAccess(
                template, command.venue_ids, command.category_ids, command.item_ids
            )

    async def list_templates(self, actor: Actor, *, active_only: bool) -> list[TemplateAccess]:
        if actor.role not in {Role.ADMIN, Role.OWNER, Role.STAFF}:
            _forbidden()
        return await self._repository.list_templates(active_only=active_only)

    async def update_template(
        self, actor: Actor, template_id: UUID, command: TemplateCreateCommand
    ) -> TemplateAccess:
        _require_admin(actor)
        name = _clean(command.name)
        description = _clean(command.description)
        if not name or not description:
            _validation("invalid_pass_template", "Название и описание обязательны")
        expected = (set(command.venue_ids), set(command.category_ids), set(command.item_ids))
        if (
            await self._repository.existing_entity_ids(
                venue_ids=expected[0], category_ids=expected[1], item_ids=expected[2]
            )
            != expected
        ):
            _validation("invalid_pass_scope", "В ограничениях есть неизвестные объекты")
        async with self._repository.transaction():
            template = await self._repository.get_template(template_id, for_update=True)
            if template is None:
                _not_found("Шаблон не найден")
            template.name = name
            template.description = description
            template.image_media_id = command.image_media_id
            template.total_uses = command.total_uses
            template.validity_days = command.validity_days
            template.price_minor = command.price_minor
            template.purchase_enabled = command.purchase_enabled
            await self._repository.replace_template_scopes(
                template.id,
                venue_ids=command.venue_ids,
                category_ids=command.category_ids,
                item_ids=command.item_ids,
            )
            self._repository.add_all(
                [_audit(actor, "subscription.template_updated", "pass_template", template.id)]
            )
            await self._repository.flush()
            return await self._repository.template_access(template)

    async def list_storefront(self, _actor: Actor) -> list[TemplateAccess]:
        values = await self._repository.list_templates(active_only=True)
        return [
            value
            for value in values
            if value.template.purchase_enabled and value.template.price_minor >= 0
        ]

    async def purchase(
        self,
        actor: Actor,
        *,
        template_id: UUID,
        payment_method: PaymentMethod,
        idempotency_key: str,
    ) -> PassPurchase:
        request_hash = _hash({"template_id": template_id, "payment_method": payment_method.value})
        async with self._repository.transaction():
            await self._repository.acquire_lock(
                "pass-purchase", f"{actor.user_id}:{idempotency_key}"
            )
            existing = await self._repository.find_purchase(actor.user_id, idempotency_key)
            if existing is not None:
                _check_hash(existing.request_hash, request_hash)
                return existing
            template = await self._repository.get_template(template_id, for_update=True)
            if template is None or not template.is_active or not template.purchase_enabled:
                _not_found("Абонемент недоступен для покупки")
            purchase = PassPurchase(
                id=uuid4(),
                template_id=template.id,
                user_id=actor.user_id,
                name_snapshot=template.name,
                price_minor=template.price_minor,
                payment_method=payment_method,
                status="pending",
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            self._repository.add_all(
                [
                    purchase,
                    _audit(
                        actor,
                        "subscription.purchase_created",
                        "pass_purchase",
                        purchase.id,
                        subject=actor.user_id,
                    ),
                ]
            )
            await self._repository.flush()
            return purchase

    async def list_my_purchases(self, actor: Actor) -> list[PassPurchase]:
        return await self._repository.list_purchases(user_id=actor.user_id)

    async def list_pending_purchases(self, actor: Actor) -> list[PassPurchase]:
        if not actor.can(PermissionCode.SUBSCRIPTIONS_MANAGE):
            _forbidden()
        return await self._repository.list_purchases(status="pending")

    async def confirm_purchase(
        self, actor: Actor, purchase_id: UUID, *, now: datetime | None = None
    ) -> PassPurchase:
        if not actor.can(PermissionCode.SUBSCRIPTIONS_MANAGE):
            _forbidden()
        current_time = now or datetime.now(UTC)
        staff_id = _staff_id(actor)
        async with self._repository.transaction():
            purchase = await self._repository.get_purchase(purchase_id, for_update=True)
            if purchase is None:
                _not_found("Покупка абонемента не найдена")
            if purchase.status == "paid":
                return purchase
            if purchase.status != "pending":
                _conflict("pass_purchase_unavailable", "Покупку уже нельзя подтвердить")
            template = await self._repository.get_template(purchase.template_id)
            if template is None:
                raise RuntimeError("Pass purchase references a missing template")
            customer_pass = CustomerPass(
                id=uuid4(),
                template_id=template.id,
                user_id=purchase.user_id,
                name_snapshot=purchase.name_snapshot,
                description_snapshot=template.description,
                image_media_id_snapshot=template.image_media_id,
                total_uses=template.total_uses,
                remaining_uses=template.total_uses,
                status=PassStatus.ACTIVE,
                issued_at=current_time,
                expires_at=current_time + timedelta(days=template.validity_days),
                issued_by_staff_id=staff_id,
                idempotency_key=f"purchase:{purchase.id}",
                request_hash=purchase.request_hash,
            )
            self._repository.add_all([customer_pass])
            await self._repository.flush()
            purchase.status = "paid"
            purchase.customer_pass_id = customer_pass.id
            purchase.confirmed_by_staff_id = staff_id
            purchase.paid_at = current_time
            self._repository.add_all(
                [
                    _audit(
                        actor,
                        "subscription.purchase_confirmed",
                        "pass_purchase",
                        purchase.id,
                        subject=purchase.user_id,
                    )
                ]
            )
            await self._repository.flush()
            return purchase

    async def archive_template(self, actor: Actor, template_id: UUID) -> TemplateAccess:
        _require_admin(actor)
        async with self._repository.transaction():
            template = await self._repository.get_template(template_id, for_update=True)
            if template is None:
                _not_found("Шаблон не найден")
            template.is_active = False
            self._repository.add_all(
                [_audit(actor, "subscription.template_archived", "pass_template", template.id)]
            )
            await self._repository.flush()
            return await self._repository.template_access(template)

    async def restore_template(self, actor: Actor, template_id: UUID) -> TemplateAccess:
        _require_admin(actor)
        async with self._repository.transaction():
            template = await self._repository.get_template(template_id, for_update=True)
            if template is None:
                _not_found("Шаблон не найден")
            template.is_active = True
            self._repository.add_all(
                [_audit(actor, "subscription.template_restored", "pass_template", template.id)]
            )
            await self._repository.flush()
            return await self._repository.template_access(template)

    async def issue(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        template_id: UUID,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> PassOutcome:
        _require_admin(actor)
        current_time = now or datetime.now(UTC)
        request_hash = _hash({"user_id": user_id, "template_id": template_id})
        staff_id = _staff_id(actor)
        async with self._repository.transaction():
            await self._repository.acquire_lock("pass-issue", f"{staff_id}:{idempotency_key}")
            existing = await self._repository.find_issue(staff_id, idempotency_key)
            if existing is not None:
                _check_hash(existing.request_hash, request_hash)
                return PassOutcome(existing, True)
            template = await self._repository.get_template(template_id, for_update=True)
            user = await self._repository.active_user(user_id)
            if template is None or not template.is_active or user is None:
                _not_found("Клиент или шаблон не найден")
            value = CustomerPass(
                id=uuid4(),
                template_id=template.id,
                user_id=user_id,
                name_snapshot=template.name,
                description_snapshot=template.description,
                image_media_id_snapshot=template.image_media_id,
                total_uses=template.total_uses,
                remaining_uses=template.total_uses,
                status=PassStatus.ACTIVE,
                issued_at=current_time,
                expires_at=current_time + timedelta(days=template.validity_days),
                issued_by_staff_id=staff_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
            self._repository.add_all(
                [
                    value,
                    _audit(
                        actor, "subscription.issued", "customer_pass", value.id, subject=user_id
                    ),
                ]
            )
            await self._repository.flush()
            return PassOutcome(value, False)

    async def cancel(
        self,
        actor: Actor,
        pass_id: UUID,
        *,
        reason: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> CustomerPass:
        _require_admin(actor)
        current_time = now or datetime.now(UTC)
        staff_id = _staff_id(actor)
        normalized_reason = _clean(reason)
        request_hash = _hash({"pass_id": pass_id, "reason": normalized_reason})
        async with self._repository.transaction():
            await self._repository.acquire_lock("pass-cancel", f"{staff_id}:{idempotency_key}")
            existing = await self._repository.find_cancellation(staff_id, idempotency_key)
            if existing is not None:
                _check_hash(existing.cancellation_request_hash or "", request_hash)
                return existing
            value = await self._repository.get_pass(pass_id, for_update=True)
            if value is None:
                _not_found("Абонемент не найден")
            if value.status is PassStatus.CANCELLED:
                return value
            if value.status is PassStatus.EXHAUSTED:
                _conflict("pass_exhausted", "Использованный абонемент нельзя отменить")
            value.status = PassStatus.CANCELLED
            value.cancelled_at = current_time
            value.cancelled_by_staff_id = staff_id
            value.cancellation_reason = normalized_reason
            value.cancellation_idempotency_key = idempotency_key
            value.cancellation_request_hash = request_hash
            self._repository.add_all(
                [
                    _audit(
                        actor,
                        "subscription.cancelled",
                        "customer_pass",
                        value.id,
                        subject=value.user_id,
                    )
                ]
            )
            await self._repository.flush()
            return value

    async def list_mine(self, actor: Actor) -> list[PassRecord]:
        return await self._repository.list_passes(user_id=actor.user_id)

    async def list_customer(self, actor: Actor, user_id: UUID) -> list[PassRecord]:
        if not actor.can(PermissionCode.SUBSCRIPTIONS_READ):
            _forbidden()
        return await self._repository.list_passes(user_id=user_id)

    async def use(
        self,
        actor: Actor,
        *,
        pass_id: UUID,
        venue_id: UUID,
        item_id: UUID,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> UsageOutcome:
        if not actor.can(PermissionCode.SUBSCRIPTIONS_MANAGE):
            _forbidden()
        current_time = now or datetime.now(UTC)
        staff_id = _staff_id(actor)
        request_hash = _hash({"pass_id": pass_id, "venue_id": venue_id, "item_id": item_id})
        async with self._repository.transaction():
            await self._repository.acquire_lock("pass-use", f"{staff_id}:{idempotency_key}")
            existing = await self._repository.find_usage(staff_id, idempotency_key)
            if existing is not None:
                _check_hash(existing.request_hash, request_hash)
                used_pass = await self._repository.get_pass(existing.pass_id)
                if used_pass is None:
                    raise RuntimeError("Pass usage references a missing pass")
                return UsageOutcome(existing, used_pass, True)
            value = await self._repository.get_pass(pass_id, for_update=True)
            if value is None:
                _not_found("Абонемент не найден")
            if value.status is PassStatus.ACTIVE and value.expires_at <= current_time:
                value.status = PassStatus.EXPIRED
            if value.status is not PassStatus.ACTIVE or value.remaining_uses <= 0:
                _conflict("pass_unavailable", "Абонемент недоступен")
            template = await self._repository.get_template(value.template_id)
            if template is None:
                raise RuntimeError("Issued pass references a missing template")
            access = await self._repository.template_access(template)
            item = await self._repository.get_item(item_id)
            venue = await self._repository.get_venue(venue_id)
            if item is None or venue is None or item.venue_id != venue_id:
                _validation("invalid_pass_item", "Товар не принадлежит выбранному заведению")
            if access.venue_ids and venue_id not in access.venue_ids:
                _conflict("pass_venue_not_allowed", "Абонемент не действует в этом заведении")
            if access.item_ids or access.category_ids:
                if item_id not in access.item_ids and item.category_id not in access.category_ids:
                    _conflict("pass_item_not_allowed", "Товар не входит в абонемент")
            before = value.remaining_uses
            value.remaining_uses -= 1
            if value.remaining_uses == 0:
                value.status = PassStatus.EXHAUSTED
            usage = PassUsage(
                id=uuid4(),
                pass_id=value.id,
                user_id=value.user_id,
                actor_staff_id=staff_id,
                venue_id=venue_id,
                item_id=item_id,
                uses_before=before,
                uses_after=value.remaining_uses,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                created_at=current_time,
            )
            self._repository.add_all(
                [
                    usage,
                    _audit(
                        actor, "subscription.used", "pass_usage", usage.id, subject=value.user_id
                    ),
                ]
            )
            await self._repository.flush()
            return UsageOutcome(usage, value, False)


def _audit(
    actor: Actor, event: str, object_type: str, object_id: UUID, *, subject: UUID | None = None
) -> AuditEvent:
    return AuditEvent(
        id=uuid4(),
        event_type=event,
        actor_user_id=actor.user_id,
        actor_staff_id=actor.staff_member_id,
        subject_user_id=subject,
        object_type=object_type,
        object_id=object_id,
        event_metadata={},
        severity=AuditSeverity.INFO,
        is_suspicious=False,
    )


def _hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps({key: str(value) for key, value in payload.items()}, sort_keys=True).encode()
    ).hexdigest()


def _check_hash(actual: str, expected: str) -> None:
    if actual != expected:
        _conflict("idempotency_key_reused", "Idempotency-Key уже использован с другими данными")


def _staff_id(actor: Actor) -> UUID:
    if actor.staff_member_id is None:
        _forbidden()
    return actor.staff_member_id


def _require_admin(actor: Actor) -> None:
    if actor.role not in {Role.ADMIN, Role.OWNER}:
        _forbidden()


def _clean(value: str) -> str:
    return " ".join(value.split())


def _forbidden() -> NoReturn:
    raise AppError(code="forbidden", message="Insufficient permissions", status_code=403)


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _not_found(message: str) -> NoReturn:
    raise AppError(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND)

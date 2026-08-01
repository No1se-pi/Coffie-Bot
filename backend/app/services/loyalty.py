"""Transactional loyalty use cases shared by HTTP and future bot workflows."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, NoReturn, Protocol
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import MenuItem
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    AuditSeverity,
    CardStatus,
    LoyaltyOperationType,
    LoyaltyProgram,
    OperationStatus,
    OutboxStatus,
    PermissionCode,
    RewardStatus,
    RewardType,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    Reward,
    RewardTemplate,
    StampTransaction,
    Visit,
)
from app.repositories.loyalty import (
    AuditEventPage,
    LoyaltyContext,
    OperationArtifacts,
    OperationPage,
    PostPurchaseRecord,
    RewardPage,
    RewardQrRecord,
    UserPage,
)
from app.security.rbac import Actor
from app.services.audit_formatter import format_audit_event
from app.services.loyalty_calculations import (
    AccrualPolicy,
    AccrualResult,
    LoyaltyRuleViolation,
    RedemptionPolicy,
    RedemptionResult,
    StampProgress,
    VisitProgress,
    advance_stamps,
    advance_visit_streak,
    business_date_for,
    business_day_bounds_utc,
    calculate_accrual,
    calculate_redemption,
)

SHORT_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SHORT_CODE_LENGTH = 10
OWN_REVERSAL_WINDOW = timedelta(minutes=10)


class LoyaltyRepositoryPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[Any]: ...

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None: ...

    async def lookup_card(
        self,
        *,
        qr_token: str | None,
        short_code: str | None,
    ) -> LoyaltyContext | None: ...

    async def get_context(
        self,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> LoyaltyContext | None: ...

    async def accrued_points_between(
        self,
        *,
        user_id: UUID,
        started_at: datetime,
        ended_at: datetime,
    ) -> int: ...

    async def count_visits(self, *, user_id: UUID, business_date: date) -> int: ...

    async def get_operation_by_idempotency(
        self,
        *,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
    ) -> LoyaltyOperation | None: ...

    async def get_operation(
        self,
        operation_id: UUID,
        *,
        for_update: bool,
    ) -> LoyaltyOperation | None: ...

    async def get_reversal(self, operation_id: UUID) -> LoyaltyOperation | None: ...

    async def get_operation_artifacts(self, operation_id: UUID) -> OperationArtifacts: ...

    async def get_reward_template(self, template_id: UUID) -> RewardTemplate | None: ...

    async def get_reward(self, reward_id: UUID, *, for_update: bool) -> Reward | None: ...

    async def get_reward_by_source_operation(self, operation_id: UUID) -> Reward | None: ...

    async def get_reward_by_qr(self, qr_payload: str) -> RewardQrRecord | None: ...

    async def get_menu_item(self, item_id: UUID, *, for_update: bool) -> MenuItem | None: ...

    async def get_post_purchase(
        self, *, operation_id: UUID, user_id: UUID
    ) -> PostPurchaseRecord | None: ...

    async def get_outbox_by_key(self, idempotency_key: str) -> NotificationOutbox | None: ...

    async def get_card(self, card_id: UUID) -> UserCard | None: ...

    async def revoke_user_sessions(
        self,
        *,
        user_id: UUID,
        now: datetime,
        reason: str,
    ) -> None: ...

    async def list_operations(
        self,
        *,
        user_id: UUID | None,
        actor_staff_id: UUID | None,
        page: int,
        page_size: int,
    ) -> OperationPage: ...

    async def list_rewards(
        self,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPage: ...

    async def list_users(
        self,
        *,
        query: str | None,
        user_status: UserStatus | None,
        page: int,
        page_size: int,
    ) -> UserPage: ...

    async def list_audit_events(
        self,
        *,
        started_at: datetime | None,
        ended_at: datetime | None,
        actor_user_id: UUID | None,
        subject_user_id: UUID | None,
        event_type: str | None,
        severity: AuditSeverity | None,
        suspicious: bool | None,
        adjustments: bool | None,
        reversed_operations: bool | None,
        page: int,
        page_size: int,
    ) -> AuditEventPage: ...

    def add_all(self, objects: list[object]) -> None: ...

    async def flush(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


EMPTY_REQUEST_METADATA = RequestMetadata()


@dataclass(frozen=True, slots=True)
class CardLookupView:
    user_id: UUID
    card_id: UUID
    display_name: str
    short_code: str
    user_status: UserStatus
    points_balance: int
    visit_streak: int
    visit_goal: int
    stamp_count: int
    stamp_goal: int
    currency_name: str
    active_rewards: tuple[Reward, ...]
    recent_operations: tuple[LoyaltyOperation, ...]


@dataclass(frozen=True, slots=True)
class AccrualPreviewView:
    user_id: UUID
    purchase_amount_minor: int
    raw_points: int
    awarded_points: int
    balance_before: int
    projected_balance_after: int
    limited_by_operation: bool
    limited_by_daily_total: bool
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class PurchasePreviewView:
    user_id: UUID
    purchase_amount_minor: int
    raw_points: int
    awarded_points: int
    balance_before: int
    projected_balance_after: int
    limited_by_operation: bool
    limited_by_daily_total: bool
    stamps_to_add: int
    stamps_before: int
    projected_stamps_after: int
    stamp_rewards_earned: int
    reward_bonus_points: int
    visit_will_be_recorded: bool
    visit_already_counted: bool
    projected_visit_streak: int
    requires_approval: bool


@dataclass(frozen=True, slots=True)
class RedemptionPreviewView:
    user_id: UUID
    purchase_amount_minor: int
    requested_points: int
    discount_minor: int
    maximum_points_for_purchase: int
    balance_before: int
    projected_balance_after: int


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    operation_id: UUID
    user_id: UUID
    operation_type: LoyaltyOperationType
    operation_status: OperationStatus
    points_delta: int
    balance_before: int | None
    balance_after: int | None
    purchase_amount_minor: int | None
    occurred_at: datetime
    business_date: date | None = None
    visit_ordinal: int | None = None
    streak_after: int | None = None
    stamps_after: int | None = None
    reward_ids: tuple[UUID, ...] = ()
    idempotent_replay: bool = False
    audit_message: str = ""


@dataclass(frozen=True, slots=True)
class UserStatusOutcome:
    user_id: UUID
    user_status: UserStatus
    idempotent_replay: bool
    audit_message: str


@dataclass(frozen=True, slots=True)
class CardReissueOutcome:
    user_id: UUID
    card_id: UUID
    qr_payload: str
    short_code: str
    idempotent_replay: bool
    audit_message: str


@dataclass(frozen=True, slots=True)
class PointsMenuPurchaseOutcome:
    operation_id: UUID
    reward_id: UUID
    item_id: UUID
    item_name: str
    points_spent: int
    balance_after: int
    qr_payload: str
    expires_at: datetime | None
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class RewardQrLookupView:
    reward_id: UUID
    customer_name: str
    reward_name: str
    description: str
    terms: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class PostPurchaseView:
    operation_id: UUID
    barista_name: str
    position: str
    photo_media_id: UUID | None
    tip_url: str | None
    tip_qr_media_id: UUID | None


class LoyaltyService:
    def __init__(self, repository: LoyaltyRepositoryPort) -> None:
        self._repository = repository

    async def lookup_card(
        self,
        actor: Actor,
        *,
        qr_token: str | None,
        short_code: str | None,
    ) -> CardLookupView:
        _require_permission(actor, PermissionCode.CARD_LOOKUP)
        if (qr_token is None) == (short_code is None):
            _raise_validation("card_identifier_required", "Укажите QR или короткий код")
        context = await self._repository.lookup_card(
            qr_token=qr_token,
            short_code=short_code,
        )
        if context is None or context.user.status in {
            UserStatus.INACTIVE,
            UserStatus.ANONYMIZED,
        }:
            _raise_not_found("Активная карта не найдена")
        rewards = await self._repository.list_rewards(
            user_id=context.user.id,
            reward_status=RewardStatus.ACTIVE,
            page=1,
            page_size=20,
        )
        operations = await self._repository.list_operations(
            user_id=context.user.id,
            actor_staff_id=None,
            page=1,
            page_size=5,
        )
        return CardLookupView(
            user_id=context.user.id,
            card_id=context.card.id,
            display_name=_display_name(context.user),
            short_code=context.card.short_code,
            user_status=context.user.status,
            points_balance=context.state.points_balance,
            visit_streak=context.state.visit_streak,
            visit_goal=context.settings.visit_required_count,
            stamp_count=context.state.stamp_count,
            stamp_goal=context.settings.stamp_required_count,
            currency_name=context.settings.currency_name,
            active_rewards=tuple(rewards.items),
            recent_operations=tuple(operations.items),
        )

    async def purchase_menu_item_with_points(
        self,
        actor: Actor,
        *,
        item_id: UUID,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> PointsMenuPurchaseOutcome:
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.POINTS_PRODUCT_PURCHASE
        request_hash = _request_hash(operation_type, actor, {"item_id": item_id})
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type, idempotency_key, request_hash
            )
            if existing is not None:
                reward = await self._repository.get_reward_by_source_operation(existing.id)
                if reward is None or reward.qr_payload is None:
                    _raise_conflict("reward_missing", "Награда операции не найдена")
                return PointsMenuPurchaseOutcome(
                    operation_id=existing.id,
                    reward_id=reward.id,
                    item_id=item_id,
                    item_name=reward.name,
                    points_spent=-existing.points_delta,
                    balance_after=existing.balance_after or 0,
                    qr_payload=reward.qr_payload,
                    expires_at=reward.expires_at,
                    idempotent_replay=True,
                )

            context = await self._require_context(actor.user_id, for_update=True)
            item = await self._repository.get_menu_item(item_id, for_update=True)
            if (
                item is None
                or item.archived_at is not None
                or not item.is_visible
                or not item.is_available
                or item.points_price is None
                or item.points_reward_template_id is None
            ):
                _raise_not_found("Товар за баллы недоступен")
            if not context.settings.points_enabled:
                _raise_conflict("points_program_disabled", "Программа баллов отключена")
            template = await self._repository.get_reward_template(item.points_reward_template_id)
            if template is None or not template.is_active:
                _raise_conflict("reward_template_inactive", "Награда для товара не настроена")

            points_price = item.points_price
            balance_before = context.state.points_balance
            if balance_before < points_price:
                _raise_conflict("insufficient_points", "Недостаточно баллов")
            balance_after = balance_before - points_price
            context.state.points_balance = balance_after
            context.state.version += 1
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=actor.user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=None,
                operation_type=operation_type,
                status=OperationStatus.COMMITTED,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                points_delta=-points_price,
                balance_before=balance_before,
                balance_after=balance_after,
                reason=f"Покупка за баллы: {item.name}",
                occurred_at=current_time,
            )
            transaction = PointTransaction(
                id=uuid4(),
                operation_id=operation.id,
                user_id=actor.user_id,
                delta=-points_price,
                balance_before=balance_before,
                balance_after=balance_after,
                created_at=current_time,
            )
            reward = _new_reward(
                template,
                user_id=actor.user_id,
                source_operation_id=operation.id,
                validity_days=None,
                now=current_time,
            )
            reward.qr_payload = f"coffee-reward:v1:{secrets.token_urlsafe(32)}"
            objects: list[object] = [operation, transaction, reward]
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="points.product_purchased",
                    event_metadata={
                        "customer_name": _display_name(context.user),
                        "item_id": str(item.id),
                        "item_name": item.name,
                        "points_spent": points_price,
                        "reward_id": str(reward.id),
                    },
                    metadata=metadata,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return PointsMenuPurchaseOutcome(
                operation_id=operation.id,
                reward_id=reward.id,
                item_id=item.id,
                item_name=item.name,
                points_spent=points_price,
                balance_after=balance_after,
                qr_payload=reward.qr_payload,
                expires_at=reward.expires_at,
                idempotent_replay=False,
            )

    async def lookup_reward_qr(self, actor: Actor, *, qr_payload: str) -> RewardQrLookupView:
        _require_permission(actor, PermissionCode.REWARDS_REDEEM)
        if not qr_payload.startswith("coffee-reward:v1:"):
            _raise_not_found("Активная награда не найдена")
        record = await self._repository.get_reward_by_qr(qr_payload)
        current_time = datetime.now(UTC)
        if (
            record is None
            or record.reward.status is not RewardStatus.ACTIVE
            or (record.reward.expires_at is not None and record.reward.expires_at <= current_time)
            or record.user.status is not UserStatus.ACTIVE
        ):
            _raise_not_found("Активная награда не найдена")
        return RewardQrLookupView(
            reward_id=record.reward.id,
            customer_name=_display_name(record.user),
            reward_name=record.reward.name,
            description=record.reward.description,
            terms=record.reward.terms,
            expires_at=record.reward.expires_at,
        )

    async def get_post_purchase(self, actor: Actor, *, operation_id: UUID) -> PostPurchaseView:
        record = await self._repository.get_post_purchase(
            operation_id=operation_id,
            user_id=actor.user_id,
        )
        if record is None:
            _raise_not_found("Операция не найдена")
        profile = record.tip_profile
        return PostPurchaseView(
            operation_id=record.operation.id,
            barista_name=(
                profile.published_name
                if profile is not None and profile.published_name
                else record.staff.display_name or record.staff_user.first_name
            ),
            position=record.staff.position or "Бариста",
            photo_media_id=(profile.published_photo_media_id if profile else None),
            tip_url=(profile.published_tip_url if profile else None),
            tip_qr_media_id=(profile.published_tip_qr_media_id if profile else None),
        )

    async def preview_accrual(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        purchase_amount_minor: int,
        now: datetime | None = None,
    ) -> AccrualPreviewView:
        _require_permission(actor, PermissionCode.POINTS_ACCRUE)
        current_time = _aware_now(now)
        context = await self._require_context(user_id, for_update=False)
        _require_not_self(actor, user_id)
        result = await self._calculate_accrual(
            context,
            purchase_amount_minor=purchase_amount_minor,
            now=current_time,
        )
        return _accrual_preview(context, result)

    async def confirm_accrual(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        purchase_amount_minor: int,
        idempotency_key: str,
        location_id: UUID | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.POINTS_ACCRUE)
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.PURCHASE_ACCRUAL
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "purchase_amount_minor": purchase_amount_minor,
                "location_id": location_id,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)

            context = await self._require_context(user_id, for_update=True)
            _require_not_self(actor, user_id)
            result = await self._calculate_accrual(
                context,
                purchase_amount_minor=purchase_amount_minor,
                now=current_time,
            )
            committed = not result.requires_approval
            balance_before = context.state.points_balance
            balance_after = balance_before + result.awarded_points if committed else None
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                location_id=location_id,
                operation_type=operation_type,
                status=(OperationStatus.COMMITTED if committed else OperationStatus.PENDING),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                purchase_amount_minor=purchase_amount_minor,
                points_delta=result.awarded_points,
                balance_before=balance_before,
                balance_after=balance_after,
                occurred_at=current_time,
            )
            objects: list[object] = [operation]
            if committed:
                context.state.points_balance = balance_after or 0
                context.state.version += 1
                objects.append(
                    PointTransaction(
                        id=uuid4(),
                        operation_id=operation.id,
                        user_id=user_id,
                        delta=result.awarded_points,
                        balance_before=balance_before,
                        balance_after=context.state.points_balance,
                        purchase_amount_minor=purchase_amount_minor,
                        created_at=current_time,
                    )
                )
            event_type = "points.accrued" if committed else "points.accrual_pending"
            event_metadata = {
                "customer_name": _display_name(context.user),
                "points": result.awarded_points,
                "purchase_amount_minor": purchase_amount_minor,
                "status": operation.status.value,
            }
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type=event_type,
                    event_metadata=event_metadata,
                    metadata=metadata,
                    severity=(AuditSeverity.INFO if committed else AuditSeverity.WARNING),
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def preview_purchase(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        purchase_amount_minor: int,
        stamps_to_add: int,
        now: datetime | None = None,
    ) -> PurchasePreviewView:
        _require_permission(actor, PermissionCode.POINTS_ACCRUE)
        if stamps_to_add > 0:
            _require_permission(actor, PermissionCode.STAMPS_ADD)
        current_time = _aware_now(now)
        context = await self._require_context(user_id, for_update=False)
        _require_not_self(actor, user_id)
        accrual = await self._calculate_accrual(
            context,
            purchase_amount_minor=purchase_amount_minor,
            now=current_time,
        )
        stamp_progress = self._purchase_stamp_progress(
            context,
            stamps_to_add=stamps_to_add,
        )
        business_date = _business_date(context.settings, current_time)
        visit_count = await self._repository.count_visits(
            user_id=user_id,
            business_date=business_date,
        )
        visit_progress = self._purchase_visit_progress(
            context,
            business_date=business_date,
            visit_count=visit_count,
        )
        visit_template = None
        if visit_progress is not None and visit_progress.reward_earned:
            visit_template = await self._required_template(
                context.settings.visit_reward_template_id,
                "visit_reward_template_missing",
                expected_program=LoyaltyProgram.VISITS,
            )
        stamp_template = None
        if stamp_progress is not None and stamp_progress.rewards_earned:
            stamp_template = await self._required_template(
                context.settings.stamp_reward_template_id,
                "stamp_reward_template_missing",
                expected_program=LoyaltyProgram.STAMPS,
            )
        reward_bonus_points = _template_point_bonus(
            visit_template,
            points_enabled=context.settings.points_enabled,
        ) + _template_point_bonus(
            stamp_template,
            points_enabled=context.settings.points_enabled,
            occurrences=stamp_progress.rewards_earned if stamp_progress is not None else 0,
        )
        return PurchasePreviewView(
            user_id=user_id,
            purchase_amount_minor=purchase_amount_minor,
            raw_points=accrual.raw_points,
            awarded_points=accrual.awarded_points,
            balance_before=context.state.points_balance,
            projected_balance_after=(
                context.state.points_balance + accrual.awarded_points + reward_bonus_points
            ),
            limited_by_operation=accrual.limited_by_operation,
            limited_by_daily_total=accrual.limited_by_daily_total,
            stamps_to_add=stamps_to_add,
            stamps_before=context.state.stamp_count,
            projected_stamps_after=(
                stamp_progress.stamps_after if stamp_progress else context.state.stamp_count
            ),
            stamp_rewards_earned=(stamp_progress.rewards_earned if stamp_progress else 0),
            reward_bonus_points=reward_bonus_points,
            visit_will_be_recorded=visit_progress is not None,
            visit_already_counted=(
                context.settings.visits_enabled
                and visit_count >= context.settings.visit_daily_limit
            ),
            projected_visit_streak=(
                visit_progress.streak_after if visit_progress else context.state.visit_streak
            ),
            requires_approval=accrual.requires_approval,
        )

    async def confirm_purchase(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        purchase_amount_minor: int,
        stamps_to_add: int,
        idempotency_key: str,
        location_id: UUID | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.POINTS_ACCRUE)
        if stamps_to_add > 0:
            _require_permission(actor, PermissionCode.STAMPS_ADD)
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.PURCHASE_ACCRUAL
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "purchase_amount_minor": purchase_amount_minor,
                "stamps_to_add": stamps_to_add,
                "location_id": location_id,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)

            context = await self._require_context(user_id, for_update=True)
            _require_not_self(actor, user_id)
            accrual = await self._calculate_accrual(
                context,
                purchase_amount_minor=purchase_amount_minor,
                now=current_time,
            )
            stamp_progress = self._purchase_stamp_progress(
                context,
                stamps_to_add=stamps_to_add,
            )
            business_date = _business_date(context.settings, current_time)
            visit_count = await self._repository.count_visits(
                user_id=user_id,
                business_date=business_date,
            )
            visit_progress = self._purchase_visit_progress(
                context,
                business_date=business_date,
                visit_count=visit_count,
            )

            committed = not accrual.requires_approval
            visit_template = None
            stamp_template = None
            reward_bonus_points = 0
            if committed:
                if visit_progress is not None and visit_progress.reward_earned:
                    visit_template = await self._required_template(
                        context.settings.visit_reward_template_id,
                        "visit_reward_template_missing",
                        expected_program=LoyaltyProgram.VISITS,
                    )
                if stamp_progress is not None and stamp_progress.rewards_earned:
                    stamp_template = await self._required_template(
                        context.settings.stamp_reward_template_id,
                        "stamp_reward_template_missing",
                        expected_program=LoyaltyProgram.STAMPS,
                    )
                reward_bonus_points = _template_point_bonus(
                    visit_template,
                    points_enabled=context.settings.points_enabled,
                ) + _template_point_bonus(
                    stamp_template,
                    points_enabled=context.settings.points_enabled,
                    occurrences=(
                        stamp_progress.rewards_earned if stamp_progress is not None else 0
                    ),
                )
            total_points = accrual.awarded_points + reward_bonus_points
            balance_before = context.state.points_balance
            balance_after = balance_before + total_points if committed else None
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                location_id=location_id,
                operation_type=operation_type,
                status=(OperationStatus.COMMITTED if committed else OperationStatus.PENDING),
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                purchase_amount_minor=purchase_amount_minor,
                points_delta=total_points,
                reward_bonus_points=reward_bonus_points,
                balance_before=balance_before,
                balance_after=balance_after,
                occurred_at=current_time,
            )
            objects: list[object] = [operation]
            rewards: list[Reward] = []
            visit: Visit | None = None
            stamp_transaction: StampTransaction | None = None

            if committed:
                context.state.points_balance = balance_after or 0
                objects.append(
                    PointTransaction(
                        id=uuid4(),
                        operation_id=operation.id,
                        user_id=user_id,
                        delta=total_points,
                        balance_before=balance_before,
                        balance_after=context.state.points_balance,
                        purchase_amount_minor=purchase_amount_minor,
                        created_at=current_time,
                    )
                )

                if visit_progress is not None:
                    visit = Visit(
                        id=uuid4(),
                        operation_id=operation.id,
                        user_id=user_id,
                        staff_member_id=_staff_member_id(actor),
                        location_id=location_id,
                        business_date=business_date,
                        ordinal=visit_count + 1,
                        visited_at=current_time,
                        streak_after=visit_progress.streak_after,
                    )
                    context.state.visit_streak = visit_progress.streak_after
                    context.state.allowed_misses_used = visit_progress.allowed_misses_used
                    context.state.last_visit_business_date = business_date
                    if context.state.visit_cycle_started_on is None:
                        context.state.visit_cycle_started_on = business_date
                    if visit_progress.reward_earned and context.settings.visit_restart_cycle:
                        context.state.visit_cycle_started_on = None
                    objects.append(visit)
                    if (
                        visit_template is not None
                        and visit_template.reward_type is not RewardType.POINTS
                    ):
                        rewards.append(
                            _new_reward(
                                visit_template,
                                user_id=user_id,
                                source_operation_id=operation.id,
                                validity_days=context.settings.visit_reward_validity_days,
                                now=current_time,
                            )
                        )

                if stamp_progress is not None:
                    stamp_rewards = [
                        _new_reward(
                            stamp_template,
                            user_id=user_id,
                            source_operation_id=operation.id,
                            validity_days=context.settings.stamp_reward_validity_days,
                            now=current_time,
                        )
                        for _ in range(stamp_progress.rewards_earned)
                        if stamp_template is not None
                        and stamp_template.reward_type is not RewardType.POINTS
                    ]
                    rewards.extend(stamp_rewards)
                    stamp_transaction = StampTransaction(
                        id=uuid4(),
                        operation_id=operation.id,
                        user_id=user_id,
                        delta=stamps_to_add,
                        stamps_before=context.state.stamp_count,
                        stamps_after=stamp_progress.stamps_after,
                        issued_reward_id=(stamp_rewards[0].id if stamp_rewards else None),
                        created_at=current_time,
                    )
                    context.state.stamp_count = stamp_progress.stamps_after
                    objects.append(stamp_transaction)

                context.state.version += 1
                objects.extend(rewards)

            event_type = "points.accrued" if committed else "points.accrual_pending"
            event_metadata = {
                "customer_name": _display_name(context.user),
                "points": total_points,
                "purchase_points": accrual.awarded_points,
                "reward_bonus_points": reward_bonus_points,
                "purchase_amount_minor": purchase_amount_minor,
                "stamps_added": stamps_to_add if committed else 0,
                "stamps_after": (
                    stamp_transaction.stamps_after if stamp_transaction is not None else None
                ),
                "visit_recorded": visit is not None,
                "visit_streak": visit.streak_after if visit is not None else None,
                "reward_ids": [str(reward.id) for reward in rewards],
                "status": operation.status.value,
            }
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type=event_type,
                    event_metadata=event_metadata,
                    metadata=metadata,
                    severity=(AuditSeverity.INFO if committed else AuditSeverity.WARNING),
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def preview_redemption(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        purchase_amount_minor: int,
        requested_points: int,
    ) -> RedemptionPreviewView:
        _require_permission(actor, PermissionCode.POINTS_REDEEM)
        context = await self._require_context(user_id, for_update=False)
        _require_not_self(actor, user_id)
        result = _calculate_redemption(
            context,
            purchase_amount_minor=purchase_amount_minor,
            requested_points=requested_points,
        )
        return _redemption_preview(context, purchase_amount_minor, result)

    async def confirm_redemption(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        purchase_amount_minor: int,
        requested_points: int,
        idempotency_key: str,
        location_id: UUID | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.POINTS_REDEEM)
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.POINTS_REDEMPTION
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "purchase_amount_minor": purchase_amount_minor,
                "requested_points": requested_points,
                "location_id": location_id,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)

            context = await self._require_context(user_id, for_update=True)
            _require_not_self(actor, user_id)
            result = _calculate_redemption(
                context,
                purchase_amount_minor=purchase_amount_minor,
                requested_points=requested_points,
            )
            balance_before = context.state.points_balance
            context.state.points_balance = result.balance_after
            context.state.version += 1
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                location_id=location_id,
                operation_type=operation_type,
                status=OperationStatus.COMMITTED,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                purchase_amount_minor=purchase_amount_minor,
                points_delta=-requested_points,
                balance_before=balance_before,
                balance_after=result.balance_after,
                occurred_at=current_time,
            )
            transaction = PointTransaction(
                id=uuid4(),
                operation_id=operation.id,
                user_id=user_id,
                delta=-requested_points,
                balance_before=balance_before,
                balance_after=result.balance_after,
                purchase_amount_minor=purchase_amount_minor,
                created_at=current_time,
            )
            event_metadata = {
                "customer_name": _display_name(context.user),
                "points": requested_points,
                "purchase_amount_minor": purchase_amount_minor,
                "discount_minor": result.discount_minor,
            }
            objects: list[object] = [operation, transaction]
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="points.redeemed",
                    event_metadata=event_metadata,
                    metadata=metadata,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    def _purchase_stamp_progress(
        self,
        context: LoyaltyContext,
        *,
        stamps_to_add: int,
    ) -> StampProgress | None:
        if stamps_to_add == 0:
            return None
        if not context.settings.stamps_enabled:
            _raise_validation("stamps_program_disabled", "Программа штампов отключена")
        try:
            return advance_stamps(
                current_stamps=context.state.stamp_count,
                stamps_to_add=stamps_to_add,
                required_stamps=context.settings.stamp_required_count,
                operation_limit=context.settings.stamp_operation_limit,
                reset_after_reward=context.settings.reset_stamps_after_reward,
            )
        except LoyaltyRuleViolation as exc:
            _raise_rule_violation(exc)

    def _purchase_visit_progress(
        self,
        context: LoyaltyContext,
        *,
        business_date: date,
        visit_count: int,
    ) -> VisitProgress | None:
        if not context.settings.visits_enabled or visit_count >= context.settings.visit_daily_limit:
            return None
        try:
            return advance_visit_streak(
                previous_business_date=context.state.last_visit_business_date,
                current_business_date=business_date,
                current_streak=context.state.visit_streak,
                required_visits=context.settings.visit_required_count,
                must_be_consecutive=context.settings.visits_must_be_consecutive,
                allowed_misses=context.settings.visit_allowed_misses,
                allowed_misses_used=context.state.allowed_misses_used,
                reset_on_miss=context.settings.visit_reset_on_miss,
                restart_cycle_after_reward=context.settings.visit_restart_cycle,
                allow_same_business_date=visit_count > 0,
            )
        except LoyaltyRuleViolation as exc:
            _raise_rule_violation(exc)

    async def _calculate_accrual(
        self,
        context: LoyaltyContext,
        *,
        purchase_amount_minor: int,
        now: datetime,
    ) -> AccrualResult:
        business_date = business_date_for(
            now,
            timezone_name=context.settings.timezone,
            boundary_minutes=context.settings.business_day_boundary_minutes,
        )
        started_at, ended_at = business_day_bounds_utc(
            business_date,
            timezone_name=context.settings.timezone,
            boundary_minutes=context.settings.business_day_boundary_minutes,
        )
        accrued_today = await self._repository.accrued_points_between(
            user_id=context.user.id,
            started_at=started_at,
            ended_at=ended_at,
        )
        try:
            return calculate_accrual(
                _accrual_policy(context.settings),
                purchase_amount_minor=purchase_amount_minor,
                accrued_today_points=accrued_today,
            )
        except LoyaltyRuleViolation as exc:
            _raise_rule_violation(exc)

    async def _idempotent_operation(
        self,
        operation_type: LoyaltyOperationType,
        idempotency_key: str,
        request_hash: str,
    ) -> LoyaltyOperation | None:
        _validate_idempotency_key(idempotency_key)
        await self._repository.acquire_idempotency_lock(
            operation_type.value,
            idempotency_key,
        )
        existing = await self._repository.get_operation_by_idempotency(
            operation_type=operation_type,
            idempotency_key=idempotency_key,
        )
        if existing is not None and not hmac.compare_digest(
            existing.request_hash,
            request_hash,
        ):
            _raise_conflict(
                "idempotency_conflict",
                "Ключ идемпотентности уже использован с другим запросом",
            )
        return existing

    async def _require_context(
        self,
        user_id: UUID,
        *,
        for_update: bool,
        allow_blocked: bool = False,
    ) -> LoyaltyContext:
        context = await self._repository.get_context(user_id, for_update=for_update)
        if context is None:
            _raise_not_found("Пользователь или активная карта не найдены")
        if context.user.status is UserStatus.BLOCKED and not allow_blocked:
            _raise_conflict("card_blocked", "Карта заблокирована")
        if context.user.status not in {UserStatus.ACTIVE, UserStatus.BLOCKED}:
            _raise_conflict("account_unavailable", "Аккаунт недоступен")
        return context

    async def _outcome(
        self,
        operation: LoyaltyOperation,
        *,
        replay: bool,
    ) -> OperationOutcome:
        artifacts = await self._repository.get_operation_artifacts(operation.id)
        message = (
            format_audit_event(
                artifacts.audit_event.event_type,
                artifacts.audit_event.event_metadata,
            )
            if artifacts.audit_event is not None
            else ""
        )
        return OperationOutcome(
            operation_id=operation.id,
            user_id=operation.user_id,
            operation_type=operation.operation_type,
            operation_status=operation.status,
            points_delta=operation.points_delta,
            balance_before=operation.balance_before,
            balance_after=operation.balance_after,
            purchase_amount_minor=operation.purchase_amount_minor,
            occurred_at=operation.occurred_at,
            business_date=(artifacts.visit.business_date if artifacts.visit else None),
            visit_ordinal=(artifacts.visit.ordinal if artifacts.visit else None),
            streak_after=(artifacts.visit.streak_after if artifacts.visit else None),
            stamps_after=(artifacts.stamp.stamps_after if artifacts.stamp else None),
            reward_ids=tuple(reward.id for reward in artifacts.rewards),
            idempotent_replay=replay,
            audit_message=message,
        )

    async def mark_visit(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        idempotency_key: str,
        location_id: UUID | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.VISITS_MARK)
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.VISIT_MARK
        request_hash = _request_hash(
            operation_type,
            actor,
            {"user_id": user_id, "location_id": location_id},
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            context = await self._require_context(user_id, for_update=True)
            _require_not_self(actor, user_id)
            if not context.settings.visits_enabled:
                _raise_validation("visits_program_disabled", "Программа посещений отключена")
            business_date = _business_date(context.settings, current_time)
            visit_count = await self._repository.count_visits(
                user_id=user_id,
                business_date=business_date,
            )
            if visit_count >= context.settings.visit_daily_limit:
                _raise_conflict(
                    "visit_daily_limit_reached",
                    "Лимит посещений за бизнес-день исчерпан",
                )
            try:
                progress = advance_visit_streak(
                    previous_business_date=context.state.last_visit_business_date,
                    current_business_date=business_date,
                    current_streak=context.state.visit_streak,
                    required_visits=context.settings.visit_required_count,
                    must_be_consecutive=context.settings.visits_must_be_consecutive,
                    allowed_misses=context.settings.visit_allowed_misses,
                    allowed_misses_used=context.state.allowed_misses_used,
                    reset_on_miss=context.settings.visit_reset_on_miss,
                    restart_cycle_after_reward=context.settings.visit_restart_cycle,
                    allow_same_business_date=visit_count > 0,
                )
            except LoyaltyRuleViolation as exc:
                _raise_rule_violation(exc)

            template = None
            if progress.reward_earned:
                template = await self._required_template(
                    context.settings.visit_reward_template_id,
                    "visit_reward_template_missing",
                    expected_program=LoyaltyProgram.VISITS,
                )
            operation = _new_operation(
                actor=actor,
                user_id=user_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=current_time,
                location_id=location_id,
                balance=context.state.points_balance,
            )
            reward_bonus_points = _template_point_bonus(
                template,
                points_enabled=context.settings.points_enabled,
            )
            point_transaction: PointTransaction | None = None
            if reward_bonus_points:
                balance_before = context.state.points_balance
                context.state.points_balance += reward_bonus_points
                operation.points_delta = reward_bonus_points
                operation.reward_bonus_points = reward_bonus_points
                operation.balance_after = context.state.points_balance
                point_transaction = PointTransaction(
                    id=uuid4(),
                    operation_id=operation.id,
                    user_id=user_id,
                    delta=reward_bonus_points,
                    balance_before=balance_before,
                    balance_after=context.state.points_balance,
                    created_at=current_time,
                )
            visit = Visit(
                id=uuid4(),
                operation_id=operation.id,
                user_id=user_id,
                staff_member_id=_staff_member_id(actor),
                location_id=location_id,
                business_date=business_date,
                ordinal=visit_count + 1,
                visited_at=current_time,
                streak_after=progress.streak_after,
            )
            context.state.visit_streak = progress.streak_after
            context.state.allowed_misses_used = progress.allowed_misses_used
            context.state.last_visit_business_date = business_date
            if context.state.visit_cycle_started_on is None:
                context.state.visit_cycle_started_on = business_date
            if progress.reward_earned and context.settings.visit_restart_cycle:
                context.state.visit_cycle_started_on = None
            context.state.version += 1

            rewards: list[Reward] = []
            if template is not None and template.reward_type is not RewardType.POINTS:
                rewards.append(
                    _new_reward(
                        template,
                        user_id=user_id,
                        source_operation_id=operation.id,
                        validity_days=context.settings.visit_reward_validity_days,
                        now=current_time,
                    )
                )
            event_metadata: dict[str, Any] = {
                "customer_name": _display_name(context.user),
                "streak": progress.streak_after,
                "business_date": business_date.isoformat(),
                "ordinal": visit.ordinal,
                "reward_ids": [str(reward.id) for reward in rewards],
                "reward_bonus_points": reward_bonus_points,
            }
            objects: list[object] = [operation, visit, *rewards]
            if point_transaction is not None:
                objects.append(point_transaction)
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="visit.marked",
                    event_metadata=event_metadata,
                    metadata=metadata,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def add_stamps(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        stamps_to_add: int,
        idempotency_key: str,
        location_id: UUID | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.STAMPS_ADD)
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.STAMP_ADDED
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "stamps_to_add": stamps_to_add,
                "location_id": location_id,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            context = await self._require_context(user_id, for_update=True)
            _require_not_self(actor, user_id)
            if not context.settings.stamps_enabled:
                _raise_validation("stamps_program_disabled", "Программа штампов отключена")
            try:
                progress = advance_stamps(
                    current_stamps=context.state.stamp_count,
                    stamps_to_add=stamps_to_add,
                    required_stamps=context.settings.stamp_required_count,
                    operation_limit=context.settings.stamp_operation_limit,
                    reset_after_reward=context.settings.reset_stamps_after_reward,
                )
            except LoyaltyRuleViolation as exc:
                _raise_rule_violation(exc)
            template = None
            if progress.rewards_earned:
                template = await self._required_template(
                    context.settings.stamp_reward_template_id,
                    "stamp_reward_template_missing",
                    expected_program=LoyaltyProgram.STAMPS,
                )
            operation = _new_operation(
                actor=actor,
                user_id=user_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=current_time,
                location_id=location_id,
                balance=context.state.points_balance,
            )
            reward_bonus_points = _template_point_bonus(
                template,
                points_enabled=context.settings.points_enabled,
                occurrences=progress.rewards_earned,
            )
            point_transaction: PointTransaction | None = None
            if reward_bonus_points:
                balance_before = context.state.points_balance
                context.state.points_balance += reward_bonus_points
                operation.points_delta = reward_bonus_points
                operation.reward_bonus_points = reward_bonus_points
                operation.balance_after = context.state.points_balance
                point_transaction = PointTransaction(
                    id=uuid4(),
                    operation_id=operation.id,
                    user_id=user_id,
                    delta=reward_bonus_points,
                    balance_before=balance_before,
                    balance_after=context.state.points_balance,
                    created_at=current_time,
                )
            rewards = [
                _new_reward(
                    template,
                    user_id=user_id,
                    source_operation_id=operation.id,
                    validity_days=context.settings.stamp_reward_validity_days,
                    now=current_time,
                )
                for _ in range(progress.rewards_earned)
                if template is not None and template.reward_type is not RewardType.POINTS
            ]
            transaction = StampTransaction(
                id=uuid4(),
                operation_id=operation.id,
                user_id=user_id,
                delta=stamps_to_add,
                stamps_before=context.state.stamp_count,
                stamps_after=progress.stamps_after,
                issued_reward_id=rewards[0].id if rewards else None,
                created_at=current_time,
            )
            context.state.stamp_count = progress.stamps_after
            context.state.version += 1
            event_metadata = {
                "customer_name": _display_name(context.user),
                "stamps": progress.stamps_after,
                "stamps_added": stamps_to_add,
                "reward_ids": [str(reward.id) for reward in rewards],
                "reward_bonus_points": reward_bonus_points,
            }
            objects: list[object] = [operation, transaction, *rewards]
            if point_transaction is not None:
                objects.append(point_transaction)
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="stamp.added",
                    event_metadata=event_metadata,
                    metadata=metadata,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def redeem_reward(
        self,
        actor: Actor,
        *,
        reward_id: UUID,
        idempotency_key: str,
        location_id: UUID | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.REWARDS_REDEEM)
        current_time = _aware_now(now)
        operation_type = LoyaltyOperationType.REWARD_REDEEMED
        request_hash = _request_hash(
            operation_type,
            actor,
            {"reward_id": reward_id, "location_id": location_id},
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            initial_reward = await self._repository.get_reward(reward_id, for_update=False)
            if initial_reward is None:
                _raise_not_found("Награда не найдена")
            context = await self._require_context(initial_reward.user_id, for_update=True)
            _require_not_self(actor, context.user.id)
            reward = await self._repository.get_reward(reward_id, for_update=True)
            if reward is None:
                _raise_not_found("Награда не найдена")
            if reward.status is not RewardStatus.ACTIVE:
                _raise_conflict("reward_not_active", "Награда уже недоступна")
            if reward.expires_at is not None and reward.expires_at <= current_time:
                _raise_conflict("reward_expired", "Срок действия награды истёк")
            operation = _new_operation(
                actor=actor,
                user_id=reward.user_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=current_time,
                location_id=location_id,
                balance=context.state.points_balance,
            )
            reward.status = RewardStatus.REDEEMED
            reward.redeemed_at = current_time
            reward.redeemed_by_staff_id = _staff_member_id(actor)
            reward.redemption_operation_id = operation.id
            event_metadata = {
                "customer_name": _display_name(context.user),
                "reward_name": reward.name,
                "reward_id": str(reward.id),
            }
            objects: list[object] = [operation]
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="reward.redeemed",
                    event_metadata=event_metadata,
                    metadata=metadata,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def admin_adjust_points(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        delta_points: int,
        reason: str,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        current_time = _aware_now(now)
        normalized_reason = _normalize_reason(reason)
        if delta_points == 0:
            _raise_validation("zero_adjustment", "Корректировка не может быть нулевой")
        operation_type = LoyaltyOperationType.ADMIN_ADJUSTMENT
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "delta_points": delta_points,
                "reason": normalized_reason,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            context = await self._require_context(user_id, for_update=True)
            _require_not_self(actor, user_id)
            balance_before = context.state.points_balance
            balance_after = balance_before + delta_points
            if balance_after < 0:
                _raise_conflict("insufficient_points", "Недостаточно баллов для корректировки")
            context.state.points_balance = balance_after
            context.state.version += 1
            operation = LoyaltyOperation(
                id=uuid4(),
                user_id=user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                operation_type=operation_type,
                status=OperationStatus.COMMITTED,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                points_delta=delta_points,
                balance_before=balance_before,
                balance_after=balance_after,
                reason=normalized_reason,
                occurred_at=current_time,
            )
            transaction = PointTransaction(
                id=uuid4(),
                operation_id=operation.id,
                user_id=user_id,
                delta=delta_points,
                balance_before=balance_before,
                balance_after=balance_after,
                created_at=current_time,
            )
            event_metadata = {
                "customer_name": _display_name(context.user),
                "delta_points": delta_points,
                "reason": normalized_reason,
            }
            objects: list[object] = [operation, transaction]
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="points.adjusted",
                    event_metadata=event_metadata,
                    metadata=metadata,
                    severity=AuditSeverity.WARNING,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def reverse_operation(
        self,
        actor: Actor,
        *,
        operation_id: UUID,
        reason: str,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        current_time = _aware_now(now)
        normalized_reason = _normalize_reason(reason)
        operation_type = LoyaltyOperationType.OPERATION_REVERSAL
        request_hash = _request_hash(
            operation_type,
            actor,
            {"operation_id": operation_id, "reason": normalized_reason},
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            initial = await self._repository.get_operation(operation_id, for_update=False)
            if initial is None:
                _raise_not_found("Операция не найдена")
            context = await self._require_context(initial.user_id, for_update=True)
            _require_not_self(actor, context.user.id)
            original = await self._repository.get_operation(operation_id, for_update=True)
            if original is None:
                _raise_not_found("Операция не найдена")
            if original.status is not OperationStatus.COMMITTED:
                _raise_conflict("operation_not_reversible", "Операцию нельзя отменить")
            if (
                original.operation_type
                not in {
                    LoyaltyOperationType.PURCHASE_ACCRUAL,
                    LoyaltyOperationType.POINTS_REDEMPTION,
                    LoyaltyOperationType.ADMIN_ADJUSTMENT,
                    LoyaltyOperationType.WELCOME_BONUS,
                }
                or original.points_delta == 0
            ):
                _raise_conflict(
                    "reversal_requires_admin_review",
                    "Последствия этой операции требуют ручного разбора",
                )
            if await self._repository.get_reversal(original.id) is not None:
                _raise_conflict("operation_already_reversed", "Операция уже отменена")
            is_admin = actor.can(PermissionCode.ADMIN_USERS_MANAGE)
            if not is_admin:
                _require_permission(actor, PermissionCode.OWN_OPERATIONS_REVERSE)
                if (
                    actor.staff_member_id is None
                    or original.actor_staff_id != actor.staff_member_id
                ):
                    _raise_forbidden("Можно отменять только собственные операции")
                age = current_time - original.occurred_at
                if age < timedelta(0) or age > OWN_REVERSAL_WINDOW:
                    _raise_conflict(
                        "reversal_window_expired",
                        "Истекло десятиминутное окно отмены",
                    )
            balance_before = context.state.points_balance
            reversal_delta = -original.points_delta
            balance_after = balance_before + reversal_delta
            if balance_after < 0:
                _raise_conflict(
                    "reversal_would_make_balance_negative",
                    "Недостаточно баллов; требуется ручная корректировка администратора",
                )
            context.state.points_balance = balance_after
            context.state.version += 1
            original.status = OperationStatus.REVERSED
            reversal = LoyaltyOperation(
                id=uuid4(),
                user_id=original.user_id,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                location_id=original.location_id,
                operation_type=operation_type,
                status=OperationStatus.COMMITTED,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                points_delta=reversal_delta,
                balance_before=balance_before,
                balance_after=balance_after,
                reason=normalized_reason,
                reversal_of_id=original.id,
                occurred_at=current_time,
            )
            transaction = PointTransaction(
                id=uuid4(),
                operation_id=reversal.id,
                user_id=original.user_id,
                delta=reversal_delta,
                balance_before=balance_before,
                balance_after=balance_after,
                created_at=current_time,
            )
            event_metadata = {
                "customer_name": _display_name(context.user),
                "points": original.points_delta,
                "reason": normalized_reason,
                "original_operation_id": str(original.id),
            }
            objects: list[object] = [reversal, transaction]
            objects.extend(
                _operation_side_effects(
                    reversal,
                    actor=actor,
                    event_type="operation.reversed",
                    event_metadata=event_metadata,
                    metadata=metadata,
                    severity=AuditSeverity.WARNING,
                    suspicious=is_admin
                    and current_time - original.occurred_at > OWN_REVERSAL_WINDOW,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(reversal, replay=False)

    async def block_user(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        reason: str,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> UserStatusOutcome:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        _require_not_self(actor, user_id)
        current_time = _aware_now(now)
        normalized_reason = _normalize_reason(reason)
        action_key = f"user-block:{idempotency_key}"
        request_hash = _request_hash(
            "user-block",
            actor,
            {"user_id": user_id, "reason": normalized_reason},
        )
        async with self._repository.transaction():
            replay = await self._idempotent_action(action_key, request_hash)
            if replay is not None:
                return UserStatusOutcome(
                    user_id=UUID(str(replay.payload["user_id"])),
                    user_status=UserStatus(str(replay.payload["user_status"])),
                    idempotent_replay=True,
                    audit_message=str(replay.payload.get("audit_message", "")),
                )
            context = await self._require_context(
                user_id,
                for_update=True,
                allow_blocked=True,
            )
            if context.user.status is UserStatus.BLOCKED:
                _raise_conflict("already_blocked", "Карта уже заблокирована")
            context.user.status = UserStatus.BLOCKED
            await self._repository.revoke_user_sessions(
                user_id=user_id,
                now=current_time,
                reason="user_blocked",
            )
            event_metadata = {
                "customer_name": _display_name(context.user),
                "reason": normalized_reason,
            }
            audit = _audit_event(
                actor=actor,
                subject_user_id=user_id,
                object_type="user_card",
                object_id=context.card.id,
                event_type="card.blocked",
                event_metadata=event_metadata,
                metadata=metadata,
                severity=AuditSeverity.WARNING,
            )
            outbox = _action_outbox(
                user_id=user_id,
                event_type="card.blocked",
                idempotency_key=action_key,
                request_hash=request_hash,
                payload={
                    "user_id": str(user_id),
                    "user_status": UserStatus.BLOCKED.value,
                    "audit_message": format_audit_event("card.blocked", event_metadata),
                },
            )
            self._repository.add_all([audit, outbox])
            await self._repository.flush()
            return UserStatusOutcome(
                user_id=user_id,
                user_status=UserStatus.BLOCKED,
                idempotent_replay=False,
                audit_message=format_audit_event("card.blocked", event_metadata),
            )

    async def unblock_user(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
    ) -> UserStatusOutcome:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        _require_not_self(actor, user_id)
        action_key = f"user-unblock:{idempotency_key}"
        request_hash = _request_hash("user-unblock", actor, {"user_id": user_id})
        async with self._repository.transaction():
            replay = await self._idempotent_action(action_key, request_hash)
            if replay is not None:
                return UserStatusOutcome(
                    user_id=UUID(str(replay.payload["user_id"])),
                    user_status=UserStatus(str(replay.payload["user_status"])),
                    idempotent_replay=True,
                    audit_message=str(replay.payload.get("audit_message", "")),
                )
            context = await self._require_context(
                user_id,
                for_update=True,
                allow_blocked=True,
            )
            if context.user.status is not UserStatus.BLOCKED:
                _raise_conflict("not_blocked", "Карта не заблокирована")
            context.user.status = UserStatus.ACTIVE
            event_metadata = {"customer_name": _display_name(context.user)}
            audit = _audit_event(
                actor=actor,
                subject_user_id=user_id,
                object_type="user_card",
                object_id=context.card.id,
                event_type="card.unblocked",
                event_metadata=event_metadata,
                metadata=metadata,
            )
            outbox = _action_outbox(
                user_id=user_id,
                event_type="card.unblocked",
                idempotency_key=action_key,
                request_hash=request_hash,
                payload={
                    "user_id": str(user_id),
                    "user_status": UserStatus.ACTIVE.value,
                    "audit_message": format_audit_event("card.unblocked", event_metadata),
                },
            )
            self._repository.add_all([audit, outbox])
            await self._repository.flush()
            return UserStatusOutcome(
                user_id=user_id,
                user_status=UserStatus.ACTIVE,
                idempotent_replay=False,
                audit_message=format_audit_event("card.unblocked", event_metadata),
            )

    async def reissue_card(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> CardReissueOutcome:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        _require_not_self(actor, user_id)
        current_time = _aware_now(now)
        action_key = f"card-reissue:{idempotency_key}"
        request_hash = _request_hash("card-reissue", actor, {"user_id": user_id})
        async with self._repository.transaction():
            replay = await self._idempotent_action(action_key, request_hash)
            if replay is not None:
                card = await self._repository.get_card(UUID(str(replay.payload["card_id"])))
                if card is None:
                    raise RuntimeError("Idempotent card reissue result is incomplete")
                return CardReissueOutcome(
                    user_id=card.user_id,
                    card_id=card.id,
                    qr_payload=card.qr_token,
                    short_code=card.short_code,
                    idempotent_replay=True,
                    audit_message=str(replay.payload.get("audit_message", "")),
                )
            context = await self._require_context(user_id, for_update=True)
            old_card = context.card
            old_card.status = CardStatus.REVOKED
            old_card.revoked_at = current_time
            old_card.revoked_by_staff_id = _staff_member_id(actor)
            old_card.revoke_reason = "admin_reissue"
            new_card = UserCard(
                id=uuid4(),
                user_id=user_id,
                qr_token=secrets.token_urlsafe(32),
                short_code="".join(
                    secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH)
                ),
                status=CardStatus.ACTIVE,
                issued_by_staff_id=_staff_member_id(actor),
            )
            event_metadata = {
                "customer_name": _display_name(context.user),
                "old_card_id": str(old_card.id),
                "new_card_id": str(new_card.id),
            }
            audit = _audit_event(
                actor=actor,
                subject_user_id=user_id,
                object_type="user_card",
                object_id=new_card.id,
                event_type="card.reissued",
                event_metadata=event_metadata,
                metadata=metadata,
                severity=AuditSeverity.WARNING,
            )
            outbox = _action_outbox(
                user_id=user_id,
                event_type="card.reissued",
                idempotency_key=action_key,
                request_hash=request_hash,
                payload={
                    "user_id": str(user_id),
                    "card_id": str(new_card.id),
                    "audit_message": format_audit_event("card.reissued", event_metadata),
                },
            )
            self._repository.add_all([new_card, audit, outbox])
            await self._repository.flush()
            return CardReissueOutcome(
                user_id=user_id,
                card_id=new_card.id,
                qr_payload=new_card.qr_token,
                short_code=new_card.short_code,
                idempotent_replay=False,
                audit_message=format_audit_event("card.reissued", event_metadata),
            )

    async def issue_reward(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        template_id: UUID,
        reason: str,
        idempotency_key: str,
        validity_days: int | None = None,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        _require_not_self(actor, user_id)
        current_time = _aware_now(now)
        normalized_reason = _normalize_reason(reason)
        if validity_days is not None and validity_days <= 0:
            _raise_validation("invalid_validity_days", "Срок действия должен быть положительным")
        operation_type = LoyaltyOperationType.REWARD_CREATED
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "template_id": template_id,
                "validity_days": validity_days,
                "reason": normalized_reason,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            context = await self._require_context(user_id, for_update=True)
            template = await self._required_template(
                template_id,
                "reward_template_missing",
            )
            operation = _new_operation(
                actor=actor,
                user_id=user_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=current_time,
                balance=context.state.points_balance,
                reason=normalized_reason,
            )
            reward = _new_reward(
                template,
                user_id=user_id,
                source_operation_id=operation.id,
                validity_days=validity_days,
                now=current_time,
            )
            event_metadata = {
                "customer_name": _display_name(context.user),
                "reward_name": reward.name,
                "reward_id": str(reward.id),
                "reason": normalized_reason,
            }
            objects: list[object] = [operation, reward]
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="reward.created",
                    event_metadata=event_metadata,
                    metadata=metadata,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def cancel_reward(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        reward_id: UUID,
        reason: str,
        idempotency_key: str,
        metadata: RequestMetadata = EMPTY_REQUEST_METADATA,
        now: datetime | None = None,
    ) -> OperationOutcome:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        _require_not_self(actor, user_id)
        current_time = _aware_now(now)
        normalized_reason = _normalize_reason(reason)
        operation_type = LoyaltyOperationType.REWARD_CANCELLED
        request_hash = _request_hash(
            operation_type,
            actor,
            {
                "user_id": user_id,
                "reward_id": reward_id,
                "reason": normalized_reason,
            },
        )
        async with self._repository.transaction():
            existing = await self._idempotent_operation(
                operation_type,
                idempotency_key,
                request_hash,
            )
            if existing is not None:
                return await self._outcome(existing, replay=True)
            context = await self._require_context(user_id, for_update=True)
            reward = await self._repository.get_reward(reward_id, for_update=True)
            if reward is None or reward.user_id != user_id:
                _raise_not_found("Награда не найдена")
            if reward.status is not RewardStatus.ACTIVE:
                _raise_conflict("reward_not_active", "Награда уже недоступна")
            operation = _new_operation(
                actor=actor,
                user_id=user_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                now=current_time,
                balance=context.state.points_balance,
                reason=normalized_reason,
            )
            reward.status = RewardStatus.CANCELLED
            reward.cancelled_at = current_time
            reward.cancelled_by_staff_id = _staff_member_id(actor)
            reward.cancellation_operation_id = operation.id
            event_metadata = {
                "customer_name": _display_name(context.user),
                "reward_name": reward.name,
                "reward_id": str(reward.id),
                "reason": normalized_reason,
            }
            objects: list[object] = [operation]
            objects.extend(
                _operation_side_effects(
                    operation,
                    actor=actor,
                    event_type="reward.cancelled",
                    event_metadata=event_metadata,
                    metadata=metadata,
                    severity=AuditSeverity.WARNING,
                )
            )
            self._repository.add_all(objects)
            await self._repository.flush()
            return await self._outcome(operation, replay=False)

    async def list_recent_operations(
        self,
        actor: Actor,
        *,
        page: int,
        page_size: int,
    ) -> OperationPage:
        if actor.staff_member_id is None:
            _raise_forbidden("Доступно только сотрудникам")
        elevated = actor.can(PermissionCode.ADMIN_USERS_READ) or actor.can(
            PermissionCode.ADMIN_EVENTS_READ
        )
        if not elevated and not any(
            actor.can(permission)
            for permission in (
                PermissionCode.POINTS_ACCRUE,
                PermissionCode.POINTS_REDEEM,
                PermissionCode.VISITS_MARK,
                PermissionCode.STAMPS_ADD,
                PermissionCode.REWARDS_REDEEM,
                PermissionCode.OWN_OPERATIONS_REVERSE,
            )
        ):
            _raise_forbidden("Недостаточно прав")
        return await self._repository.list_operations(
            user_id=None,
            actor_staff_id=None if elevated else actor.staff_member_id,
            page=page,
            page_size=page_size,
        )

    async def list_users(
        self,
        actor: Actor,
        *,
        query: str | None,
        user_status: UserStatus | None,
        page: int,
        page_size: int,
    ) -> UserPage:
        _require_permission(actor, PermissionCode.ADMIN_USERS_READ)
        normalized_query = " ".join(query.split())[:128] if query else None
        return await self._repository.list_users(
            query=normalized_query or None,
            user_status=user_status,
            page=page,
            page_size=page_size,
        )

    async def get_admin_user(self, actor: Actor, user_id: UUID) -> LoyaltyContext:
        _require_permission(actor, PermissionCode.ADMIN_USERS_READ)
        return await self._require_context(
            user_id,
            for_update=False,
            allow_blocked=True,
        )

    async def list_user_history(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        page: int,
        page_size: int,
    ) -> OperationPage:
        _require_permission(actor, PermissionCode.ADMIN_USERS_READ)
        return await self._repository.list_operations(
            user_id=user_id,
            actor_staff_id=None,
            page=page,
            page_size=page_size,
        )

    async def list_user_rewards(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPage:
        _require_permission(actor, PermissionCode.ADMIN_USERS_READ)
        return await self._repository.list_rewards(
            user_id=user_id,
            reward_status=reward_status,
            page=page,
            page_size=page_size,
        )

    async def list_audit_events(
        self,
        actor: Actor,
        *,
        started_at: datetime | None,
        ended_at: datetime | None,
        actor_user_id: UUID | None,
        subject_user_id: UUID | None,
        event_type: str | None,
        severity: AuditSeverity | None,
        suspicious: bool | None,
        adjustments: bool | None,
        reversed_operations: bool | None,
        page: int,
        page_size: int,
    ) -> AuditEventPage:
        _require_permission(actor, PermissionCode.ADMIN_EVENTS_READ)
        if started_at is not None:
            started_at = _aware_now(started_at)
        if ended_at is not None:
            ended_at = _aware_now(ended_at)
        if started_at is not None and ended_at is not None and started_at >= ended_at:
            _raise_validation("invalid_period", "Начало периода должно быть раньше конца")
        return await self._repository.list_audit_events(
            started_at=started_at,
            ended_at=ended_at,
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            event_type=event_type,
            severity=severity,
            suspicious=suspicious,
            adjustments=adjustments,
            reversed_operations=reversed_operations,
            page=page,
            page_size=page_size,
        )

    async def _required_template(
        self,
        template_id: UUID | None,
        error_code: str,
        *,
        expected_program: LoyaltyProgram | None = None,
    ) -> RewardTemplate:
        if template_id is None:
            _raise_conflict(error_code, "Шаблон награды не настроен")
        template = await self._repository.get_reward_template(template_id)
        if template is None or not template.is_active:
            _raise_conflict(error_code, "Шаблон награды недоступен")
        if expected_program is not None and template.source_program not in {
            expected_program,
            LoyaltyProgram.MANUAL,
        }:
            _raise_conflict(error_code, "Шаблон награды относится к другой программе")
        return template

    async def _idempotent_action(
        self,
        action_key: str,
        request_hash: str,
    ) -> NotificationOutbox | None:
        _validate_idempotency_key(action_key.split(":", 1)[-1])
        await self._repository.acquire_idempotency_lock("administrative-action", action_key)
        existing = await self._repository.get_outbox_by_key(action_key)
        if existing is not None:
            existing_hash = existing.payload.get("request_hash")
            if not isinstance(existing_hash, str) or not hmac.compare_digest(
                existing_hash,
                request_hash,
            ):
                _raise_conflict(
                    "idempotency_conflict",
                    "Ключ идемпотентности уже использован с другим запросом",
                )
        return existing


def _accrual_policy(settings: LoyaltySettings) -> AccrualPolicy:
    return AccrualPolicy(
        enabled=settings.points_enabled,
        minor_units_per_point=settings.minor_units_per_point,
        minimum_purchase_minor=settings.minimum_purchase_minor,
        maximum_purchase_minor=settings.maximum_purchase_minor,
        rounding_mode=settings.rounding_mode,
        operation_limit_points=settings.operation_accrual_limit_points,
        daily_limit_points=settings.daily_accrual_limit_points,
        large_operation_threshold_minor=settings.large_operation_threshold_minor,
        large_operation_requires_approval=settings.large_operation_requires_approval,
    )


def _redemption_policy(settings: LoyaltySettings) -> RedemptionPolicy:
    return RedemptionPolicy(
        enabled=settings.points_enabled,
        redemption_minor_units_per_point=settings.redemption_minor_units_per_point,
        minimum_redemption_points=settings.minimum_redemption_points,
        maximum_redemption_percent=settings.maximum_redemption_percent,
        maximum_purchase_minor=settings.maximum_purchase_minor,
    )


def _calculate_redemption(
    context: LoyaltyContext,
    *,
    purchase_amount_minor: int,
    requested_points: int,
) -> RedemptionResult:
    try:
        return calculate_redemption(
            _redemption_policy(context.settings),
            purchase_amount_minor=purchase_amount_minor,
            requested_points=requested_points,
            current_balance_points=context.state.points_balance,
        )
    except LoyaltyRuleViolation as exc:
        _raise_rule_violation(exc)


def _accrual_preview(
    context: LoyaltyContext,
    result: AccrualResult,
) -> AccrualPreviewView:
    return AccrualPreviewView(
        user_id=context.user.id,
        purchase_amount_minor=result.purchase_amount_minor,
        raw_points=result.raw_points,
        awarded_points=result.awarded_points,
        balance_before=context.state.points_balance,
        projected_balance_after=context.state.points_balance + result.awarded_points,
        limited_by_operation=result.limited_by_operation,
        limited_by_daily_total=result.limited_by_daily_total,
        requires_approval=result.requires_approval,
    )


def _redemption_preview(
    context: LoyaltyContext,
    purchase_amount_minor: int,
    result: RedemptionResult,
) -> RedemptionPreviewView:
    return RedemptionPreviewView(
        user_id=context.user.id,
        purchase_amount_minor=purchase_amount_minor,
        requested_points=result.requested_points,
        discount_minor=result.discount_minor,
        maximum_points_for_purchase=result.maximum_points_for_purchase,
        balance_before=context.state.points_balance,
        projected_balance_after=result.balance_after,
    )


def _new_operation(
    *,
    actor: Actor,
    user_id: UUID,
    operation_type: LoyaltyOperationType,
    idempotency_key: str,
    request_hash: str,
    now: datetime,
    balance: int,
    location_id: UUID | None = None,
    reason: str | None = None,
) -> LoyaltyOperation:
    return LoyaltyOperation(
        id=uuid4(),
        user_id=user_id,
        actor_user_id=actor.user_id,
        actor_staff_id=actor.staff_member_id,
        location_id=location_id,
        operation_type=operation_type,
        status=OperationStatus.COMMITTED,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        points_delta=0,
        balance_before=balance,
        balance_after=balance,
        reason=reason,
        occurred_at=now,
    )


def _template_point_bonus(
    template: RewardTemplate | None,
    *,
    points_enabled: bool,
    occurrences: int = 1,
) -> int:
    if template is None or template.reward_type is not RewardType.POINTS:
        return 0
    if not points_enabled:
        _raise_conflict(
            "points_program_disabled",
            "Балльная программа отключена; награда баллами недоступна",
        )
    if template.value_int is None or template.value_int <= 0:
        _raise_conflict(
            "invalid_points_reward",
            "Количество баллов в награде настроено некорректно",
        )
    if occurrences < 0:
        raise ValueError("reward occurrences cannot be negative")
    return template.value_int * occurrences


def _new_reward(
    template: RewardTemplate,
    *,
    user_id: UUID,
    source_operation_id: UUID,
    validity_days: int | None,
    now: datetime,
) -> Reward:
    if template.reward_type is RewardType.POINTS:
        _raise_conflict(
            "points_reward_is_automatic",
            "Балльная награда начисляется автоматически и не создаёт QR-код",
        )
    effective_validity = validity_days if validity_days is not None else template.validity_days
    if effective_validity is not None and effective_validity <= 0:
        _raise_conflict(
            "invalid_reward_validity",
            "Срок действия награды настроен некорректно",
        )
    return Reward(
        id=uuid4(),
        user_id=user_id,
        template_id=template.id,
        source_operation_id=source_operation_id,
        name=template.name,
        description=template.description,
        reward_type=template.reward_type,
        value_int=template.value_int,
        terms=template.terms,
        status=RewardStatus.ACTIVE,
        expires_at=(
            now + timedelta(days=effective_validity) if effective_validity is not None else None
        ),
    )


def _operation_side_effects(
    operation: LoyaltyOperation,
    *,
    actor: Actor,
    event_type: str,
    event_metadata: Mapping[str, Any],
    metadata: RequestMetadata,
    severity: AuditSeverity = AuditSeverity.INFO,
    suspicious: bool = False,
) -> list[object]:
    safe_metadata = dict(event_metadata)
    safe_metadata.setdefault("actor_name", "Сотрудник")
    audit = _audit_event(
        actor=actor,
        subject_user_id=operation.user_id,
        object_type="loyalty_operation",
        object_id=operation.id,
        event_type=event_type,
        event_metadata=safe_metadata,
        metadata=metadata,
        severity=severity,
        suspicious=suspicious,
    )
    outbox = NotificationOutbox(
        id=uuid4(),
        user_id=operation.user_id,
        event_type=event_type,
        payload={
            "operation_id": str(operation.id),
            "operation_type": operation.operation_type.value,
            "operation_status": operation.status.value,
            **safe_metadata,
        },
        idempotency_key=f"operation:{operation.id}",
        status=OutboxStatus.PENDING,
        attempts=0,
    )
    return [audit, outbox]


def _audit_event(
    *,
    actor: Actor,
    subject_user_id: UUID,
    object_type: str,
    object_id: UUID,
    event_type: str,
    event_metadata: Mapping[str, Any],
    metadata: RequestMetadata,
    severity: AuditSeverity = AuditSeverity.INFO,
    suspicious: bool = False,
) -> AuditEvent:
    safe_metadata = dict(event_metadata)
    safe_metadata.setdefault("actor_name", "Сотрудник")
    return AuditEvent(
        id=uuid4(),
        event_type=event_type,
        actor_user_id=actor.user_id,
        actor_staff_id=actor.staff_member_id,
        subject_user_id=subject_user_id,
        object_type=object_type,
        object_id=object_id,
        event_metadata=safe_metadata,
        severity=severity,
        is_suspicious=suspicious,
        ip_address=_truncate(metadata.ip_address, 45),
        user_agent=_truncate(metadata.user_agent, 512),
    )


def _action_outbox(
    *,
    user_id: UUID,
    event_type: str,
    idempotency_key: str,
    request_hash: str,
    payload: Mapping[str, Any],
) -> NotificationOutbox:
    return NotificationOutbox(
        id=uuid4(),
        user_id=user_id,
        event_type=event_type,
        payload={"request_hash": request_hash, **dict(payload)},
        idempotency_key=idempotency_key,
        status=OutboxStatus.PENDING,
        attempts=0,
    )


def _business_date(settings: LoyaltySettings, now: datetime) -> date:
    try:
        return business_date_for(
            now,
            timezone_name=settings.timezone,
            boundary_minutes=settings.business_day_boundary_minutes,
        )
    except LoyaltyRuleViolation as exc:
        _raise_rule_violation(exc)


def _request_hash(
    operation: LoyaltyOperationType | str,
    actor: Actor,
    payload: Mapping[str, Any],
) -> str:
    operation_name = operation.value if isinstance(operation, LoyaltyOperationType) else operation
    canonical = json.dumps(
        {
            "operation": operation_name,
            "actor_user_id": str(actor.user_id),
            "actor_staff_id": (
                str(actor.staff_member_id) if actor.staff_member_id is not None else None
            ),
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _validate_idempotency_key(value: str) -> None:
    if not value or len(value) > 128:
        _raise_validation(
            "invalid_idempotency_key",
            "Idempotency-Key должен быть UUID",
        )
    try:
        parsed = UUID(value)
    except ValueError:
        _raise_validation(
            "invalid_idempotency_key",
            "Idempotency-Key должен быть UUID",
        )
    if str(parsed) != value:
        _raise_validation(
            "invalid_idempotency_key",
            "Idempotency-Key должен быть каноническим UUID",
        )


def _normalize_reason(reason: str) -> str:
    normalized = " ".join(reason.split())
    if not normalized:
        _raise_validation("reason_required", "Необходимо указать причину")
    if len(normalized) > 1_000:
        _raise_validation("reason_too_long", "Причина слишком длинная")
    return normalized


def _require_permission(actor: Actor, permission: PermissionCode) -> None:
    if not actor.can(permission):
        _raise_forbidden("Недостаточно прав")


def _require_not_self(actor: Actor, user_id: UUID) -> None:
    if actor.user_id == user_id:
        raise AppError(
            code="self_operation_forbidden",
            message="Операции с собственной картой запрещены",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _staff_member_id(actor: Actor) -> UUID:
    if actor.staff_member_id is None:
        _raise_forbidden("Доступно только сотрудникам")
    return actor.staff_member_id


def _display_name(user: User) -> str:
    return " ".join(part for part in (user.first_name, user.last_name) if part).strip()


def _aware_now(value: datetime | None) -> datetime:
    current_time = value or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current_time


def _truncate(value: str | None, maximum: int) -> str | None:
    return None if value is None else value[:maximum]


def _raise_rule_violation(exc: LoyaltyRuleViolation) -> NoReturn:
    raise AppError(
        code=exc.code,
        message=exc.message,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    ) from exc


def _raise_validation(code: str, message: str) -> NoReturn:
    raise AppError(
        code=code,
        message=message,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _raise_conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _raise_not_found(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.NOT_FOUND,
        message=message,
        status_code=status.HTTP_404_NOT_FOUND,
    )


def _raise_forbidden(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.FORBIDDEN,
        message=message,
        status_code=status.HTTP_403_FORBIDDEN,
    )

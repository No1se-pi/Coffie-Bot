"""Strict request and response contracts for loyalty staff/admin endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    AuditSeverity,
    LoyaltyOperationType,
    OperationStatus,
    RewardStatus,
    RewardType,
    UserStatus,
)
from app.repositories.loyalty import (
    AuditEventPage,
    LoyaltyContext,
    OperationPage,
    RewardPage,
    UserPage,
)
from app.services.audit_formatter import format_audit_event
from app.services.loyalty import (
    AccrualPreviewView,
    CardLookupView,
    CardReissueOutcome,
    OperationOutcome,
    PurchasePreviewView,
    RedemptionPreviewView,
    UserStatusOutcome,
)


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardLookupRequest(ApiSchema):
    qr_token: str | None = Field(default=None, min_length=16, max_length=128)
    short_code: str | None = Field(default=None, min_length=4, max_length=16)

    @field_validator("short_code")
    @classmethod
    def normalize_short_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("short_code must contain visible characters")
        return normalized

    @model_validator(mode="after")
    def exactly_one_identifier(self) -> CardLookupRequest:
        if (self.qr_token is None) == (self.short_code is None):
            raise ValueError("exactly one of qr_token or short_code is required")
        return self


class CardRewardResponse(ApiSchema):
    id: UUID
    name: str
    description: str
    type: RewardType
    status: RewardStatus
    terms: str | None
    expires_at: datetime | None
    created_at: datetime


class CardOperationResponse(ApiSchema):
    id: UUID
    type: LoyaltyOperationType
    status: OperationStatus
    points_delta: int
    balance_after: int | None
    occurred_at: datetime


class CardLookupResponse(ApiSchema):
    user_id: UUID
    card_id: UUID
    display_name: str
    short_code: str
    user_status: UserStatus
    blocked: bool
    points_balance: int
    visit_streak: int
    visit_goal: int
    stamp_count: int
    stamp_goal: int
    currency_name: str
    available_rewards: list[CardRewardResponse]
    recent_operations: list[CardOperationResponse]


class AccrualRequest(ApiSchema):
    user_id: UUID
    purchase_amount_minor: int = Field(gt=0)
    location_id: UUID | None = None


class AccrualPreviewResponse(ApiSchema):
    user_id: UUID
    purchase_amount_minor: int
    raw_points: int
    awarded_points: int
    balance_before: int
    projected_balance_after: int
    limited_by_operation: bool
    limited_by_daily_total: bool
    requires_approval: bool


class PurchaseRequest(ApiSchema):
    user_id: UUID
    purchase_amount_minor: int = Field(gt=0)
    stamps_to_add: int = Field(default=0, ge=0, le=100)
    location_id: UUID | None = None


class PurchasePreviewResponse(ApiSchema):
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
    visit_will_be_recorded: bool
    visit_already_counted: bool
    projected_visit_streak: int
    requires_approval: bool


class RedemptionRequest(ApiSchema):
    user_id: UUID
    purchase_amount_minor: int = Field(gt=0)
    requested_points: int = Field(gt=0)
    location_id: UUID | None = None


class RedemptionPreviewResponse(ApiSchema):
    user_id: UUID
    purchase_amount_minor: int
    requested_points: int
    discount_minor: int
    maximum_points_for_purchase: int
    balance_before: int
    projected_balance_after: int


class VisitRequest(ApiSchema):
    user_id: UUID
    location_id: UUID | None = None


class StampRequest(ApiSchema):
    user_id: UUID
    stamps_to_add: int = Field(default=1, gt=0, le=100)
    location_id: UUID | None = None


class ReasonRequest(ApiSchema):
    reason: str = Field(min_length=1, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("reason must contain visible characters")
        return normalized


class AdjustmentRequest(ReasonRequest):
    delta_points: int

    @field_validator("delta_points")
    @classmethod
    def non_zero_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("delta_points must not be zero")
        return value


class RewardIssueRequest(ReasonRequest):
    template_id: UUID
    validity_days: int | None = Field(default=None, gt=0, le=3_650)


class RewardCancelRequest(ReasonRequest):
    pass


class OperationResponse(ApiSchema):
    operation_id: UUID
    user_id: UUID
    operation_type: LoyaltyOperationType
    status: OperationStatus
    points_delta: int
    balance_before: int | None
    balance_after: int | None
    purchase_amount_minor: int | None
    occurred_at: datetime
    business_date: date | None
    visit_ordinal: int | None
    streak_after: int | None
    stamps_after: int | None
    reward_ids: list[UUID]
    idempotent_replay: bool
    audit_message: str


class UserStatusResponse(ApiSchema):
    user_id: UUID
    status: UserStatus
    blocked: bool
    idempotent_replay: bool
    audit_message: str


class CardReissueResponse(ApiSchema):
    user_id: UUID
    card_id: UUID
    qr_payload: str
    short_code: str
    idempotent_replay: bool
    audit_message: str


class OperationListItemResponse(ApiSchema):
    id: UUID
    user_id: UUID
    actor_staff_id: UUID | None
    type: LoyaltyOperationType
    status: OperationStatus
    points_delta: int
    balance_before: int | None
    balance_after: int | None
    purchase_amount_minor: int | None
    reason: str | None
    reversal_of_id: UUID | None
    occurred_at: datetime


class OperationListResponse(ApiSchema):
    items: list[OperationListItemResponse]
    page: int
    page_size: int
    total: int


class RewardListItemResponse(ApiSchema):
    id: UUID
    user_id: UUID
    template_id: UUID
    name: str
    description: str
    type: RewardType
    status: RewardStatus
    value_int: int | None
    terms: str | None
    expires_at: datetime | None
    redeemed_at: datetime | None
    created_at: datetime


class RewardListResponse(ApiSchema):
    items: list[RewardListItemResponse]
    page: int
    page_size: int
    total: int


class AdminUserListItemResponse(ApiSchema):
    id: UUID
    telegram_id: int
    display_name: str
    username: str | None
    status: UserStatus
    created_at: datetime
    last_seen_at: datetime | None


class AdminUserListResponse(ApiSchema):
    items: list[AdminUserListItemResponse]
    page: int
    page_size: int
    total: int


class AdminUserResponse(AdminUserListItemResponse):
    card_id: UUID
    short_code: str
    points_balance: int
    visit_streak: int
    stamp_count: int
    active_card: bool


class AuditEventResponse(ApiSchema):
    id: UUID
    event_type: str
    actor_user_id: UUID | None
    actor_staff_id: UUID | None
    subject_user_id: UUID | None
    object_type: str | None
    object_id: UUID | None
    metadata: dict[str, Any]
    severity: AuditSeverity
    suspicious: bool
    human_message: str
    created_at: datetime


class AuditEventListResponse(ApiSchema):
    items: list[AuditEventResponse]
    page: int
    page_size: int
    total: int


def card_lookup_response(value: CardLookupView) -> CardLookupResponse:
    return CardLookupResponse(
        user_id=value.user_id,
        card_id=value.card_id,
        display_name=value.display_name,
        short_code=value.short_code,
        user_status=value.user_status,
        blocked=value.user_status is UserStatus.BLOCKED,
        points_balance=value.points_balance,
        visit_streak=value.visit_streak,
        visit_goal=value.visit_goal,
        stamp_count=value.stamp_count,
        stamp_goal=value.stamp_goal,
        currency_name=value.currency_name,
        available_rewards=[
            CardRewardResponse(
                id=reward.id,
                name=reward.name,
                description=reward.description,
                type=reward.reward_type,
                status=reward.status,
                terms=reward.terms,
                expires_at=reward.expires_at,
                created_at=reward.created_at,
            )
            for reward in value.active_rewards
        ],
        recent_operations=[
            CardOperationResponse(
                id=operation.id,
                type=operation.operation_type,
                status=operation.status,
                points_delta=operation.points_delta,
                balance_after=operation.balance_after,
                occurred_at=operation.occurred_at,
            )
            for operation in value.recent_operations
        ],
    )


def accrual_preview_response(value: AccrualPreviewView) -> AccrualPreviewResponse:
    return AccrualPreviewResponse(
        user_id=value.user_id,
        purchase_amount_minor=value.purchase_amount_minor,
        raw_points=value.raw_points,
        awarded_points=value.awarded_points,
        balance_before=value.balance_before,
        projected_balance_after=value.projected_balance_after,
        limited_by_operation=value.limited_by_operation,
        limited_by_daily_total=value.limited_by_daily_total,
        requires_approval=value.requires_approval,
    )


def purchase_preview_response(value: PurchasePreviewView) -> PurchasePreviewResponse:
    return PurchasePreviewResponse(
        user_id=value.user_id,
        purchase_amount_minor=value.purchase_amount_minor,
        raw_points=value.raw_points,
        awarded_points=value.awarded_points,
        balance_before=value.balance_before,
        projected_balance_after=value.projected_balance_after,
        limited_by_operation=value.limited_by_operation,
        limited_by_daily_total=value.limited_by_daily_total,
        stamps_to_add=value.stamps_to_add,
        stamps_before=value.stamps_before,
        projected_stamps_after=value.projected_stamps_after,
        stamp_rewards_earned=value.stamp_rewards_earned,
        visit_will_be_recorded=value.visit_will_be_recorded,
        visit_already_counted=value.visit_already_counted,
        projected_visit_streak=value.projected_visit_streak,
        requires_approval=value.requires_approval,
    )


def redemption_preview_response(
    value: RedemptionPreviewView,
) -> RedemptionPreviewResponse:
    return RedemptionPreviewResponse(
        user_id=value.user_id,
        purchase_amount_minor=value.purchase_amount_minor,
        requested_points=value.requested_points,
        discount_minor=value.discount_minor,
        maximum_points_for_purchase=value.maximum_points_for_purchase,
        balance_before=value.balance_before,
        projected_balance_after=value.projected_balance_after,
    )


def operation_response(value: OperationOutcome) -> OperationResponse:
    return OperationResponse(
        operation_id=value.operation_id,
        user_id=value.user_id,
        operation_type=value.operation_type,
        status=value.operation_status,
        points_delta=value.points_delta,
        balance_before=value.balance_before,
        balance_after=value.balance_after,
        purchase_amount_minor=value.purchase_amount_minor,
        occurred_at=value.occurred_at,
        business_date=value.business_date,
        visit_ordinal=value.visit_ordinal,
        streak_after=value.streak_after,
        stamps_after=value.stamps_after,
        reward_ids=list(value.reward_ids),
        idempotent_replay=value.idempotent_replay,
        audit_message=value.audit_message,
    )


def user_status_response(value: UserStatusOutcome) -> UserStatusResponse:
    return UserStatusResponse(
        user_id=value.user_id,
        status=value.user_status,
        blocked=value.user_status is UserStatus.BLOCKED,
        idempotent_replay=value.idempotent_replay,
        audit_message=value.audit_message,
    )


def card_reissue_response(value: CardReissueOutcome) -> CardReissueResponse:
    return CardReissueResponse(
        user_id=value.user_id,
        card_id=value.card_id,
        qr_payload=value.qr_payload,
        short_code=value.short_code,
        idempotent_replay=value.idempotent_replay,
        audit_message=value.audit_message,
    )


def operation_page_response(
    value: OperationPage,
    *,
    page: int,
    page_size: int,
) -> OperationListResponse:
    return OperationListResponse(
        items=[
            OperationListItemResponse(
                id=item.id,
                user_id=item.user_id,
                actor_staff_id=item.actor_staff_id,
                type=item.operation_type,
                status=item.status,
                points_delta=item.points_delta,
                balance_before=item.balance_before,
                balance_after=item.balance_after,
                purchase_amount_minor=item.purchase_amount_minor,
                reason=item.reason,
                reversal_of_id=item.reversal_of_id,
                occurred_at=item.occurred_at,
            )
            for item in value.items
        ],
        page=page,
        page_size=page_size,
        total=value.total,
    )


def reward_page_response(
    value: RewardPage,
    *,
    page: int,
    page_size: int,
) -> RewardListResponse:
    return RewardListResponse(
        items=[
            RewardListItemResponse(
                id=item.id,
                user_id=item.user_id,
                template_id=item.template_id,
                name=item.name,
                description=item.description,
                type=item.reward_type,
                status=item.status,
                value_int=item.value_int,
                terms=item.terms,
                expires_at=item.expires_at,
                redeemed_at=item.redeemed_at,
                created_at=item.created_at,
            )
            for item in value.items
        ],
        page=page,
        page_size=page_size,
        total=value.total,
    )


def user_page_response(
    value: UserPage,
    *,
    page: int,
    page_size: int,
) -> AdminUserListResponse:
    return AdminUserListResponse(
        items=[
            AdminUserListItemResponse(
                id=item.id,
                telegram_id=item.telegram_id,
                display_name=_display_name(item.first_name, item.last_name),
                username=item.username,
                status=item.status,
                created_at=item.created_at,
                last_seen_at=item.last_seen_at,
            )
            for item in value.items
        ],
        page=page,
        page_size=page_size,
        total=value.total,
    )


def admin_user_response(value: LoyaltyContext) -> AdminUserResponse:
    return AdminUserResponse(
        id=value.user.id,
        telegram_id=value.user.telegram_id,
        display_name=_display_name(value.user.first_name, value.user.last_name),
        username=value.user.username,
        status=value.user.status,
        created_at=value.user.created_at,
        last_seen_at=value.user.last_seen_at,
        card_id=value.card.id,
        short_code=value.card.short_code,
        points_balance=value.state.points_balance,
        visit_streak=value.state.visit_streak,
        stamp_count=value.state.stamp_count,
        active_card=value.card.status.value == "active",
    )


def audit_event_page_response(
    value: AuditEventPage,
    *,
    page: int,
    page_size: int,
) -> AuditEventListResponse:
    return AuditEventListResponse(
        items=[
            AuditEventResponse(
                id=item.id,
                event_type=item.event_type,
                actor_user_id=item.actor_user_id,
                actor_staff_id=item.actor_staff_id,
                subject_user_id=item.subject_user_id,
                object_type=item.object_type,
                object_id=item.object_id,
                metadata=item.event_metadata,
                severity=item.severity,
                suspicious=item.is_suspicious,
                human_message=format_audit_event(item.event_type, item.event_metadata),
                created_at=item.created_at,
            )
            for item in value.items
        ],
        page=page,
        page_size=page_size,
        total=value.total,
    )


def _display_name(first_name: str, last_name: str | None) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()

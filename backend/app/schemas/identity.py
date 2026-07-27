"""API schemas for authentication and current-user self-service endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    LoyaltyOperationType,
    OperationStatus,
    PermissionCode,
    RewardStatus,
    RewardType,
    Role,
    UserStatus,
)
from app.repositories.identity import (
    CardViewRecord,
    HistoryPageRecord,
    RewardPageRecord,
)
from app.services.identity import AuthenticationResult, IdentityView
from app.services.loyalty import PointsMenuPurchaseOutcome, PostPurchaseView


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TelegramAuthRequest(ApiSchema):
    init_data: str = Field(max_length=65_536)


class CurrentUserResponse(ApiSchema):
    id: UUID
    telegram_id: int
    display_name: str
    username: str | None
    photo_url: str | None
    status: UserStatus
    role: Role
    available_roles: list[Role]
    permissions: list[PermissionCode]


class CurrentStaffResponse(ApiSchema):
    id: UUID
    role: Role
    display_name: str | None
    position: str | None
    permissions: list[PermissionCode]


class AuthResponse(ApiSchema):
    access_token: str
    expires_at: datetime
    user: CurrentUserResponse
    staff: CurrentStaffResponse | None


class MeResponse(ApiSchema):
    user: CurrentUserResponse
    staff: CurrentStaffResponse | None


class CardResponse(ApiSchema):
    user_id: UUID
    display_name: str
    qr_payload: str
    short_code: str
    balance_points: int
    currency_name: str
    visit_streak: int
    visit_goal: int
    stamps: int
    stamp_goal: int
    blocked: bool
    updated_at: datetime


HistoryPublicStatus = Literal["completed", "pending", "reversed", "failed"]


class HistoryItemResponse(ApiSchema):
    id: UUID
    type: LoyaltyOperationType
    description: str
    delta_points: int
    balance_after: int | None
    created_at: datetime
    status: HistoryPublicStatus


class HistoryListResponse(ApiSchema):
    items: list[HistoryItemResponse]
    page: int
    page_size: int
    total: int


class RewardResponse(ApiSchema):
    id: UUID
    title: str
    description: str
    image_url: str | None = None
    type: RewardType
    status: RewardStatus
    expires_at: datetime | None
    created_at: datetime
    redeemed_at: datetime | None
    terms: str | None
    qr_payload: str | None


class PointsMenuPurchaseResponse(ApiSchema):
    operation_id: UUID
    reward_id: UUID
    item_id: UUID
    item_name: str
    points_spent: int
    balance_after: int
    qr_payload: str
    expires_at: datetime | None
    idempotent_replay: bool


class PostPurchaseResponse(ApiSchema):
    operation_id: UUID
    barista_name: str
    position: str
    photo_url: str | None
    tip_url: str | None
    tip_qr_url: str | None


class RewardListResponse(ApiSchema):
    items: list[RewardResponse]
    page: int
    page_size: int
    total: int


def auth_response(result: AuthenticationResult) -> AuthResponse:
    user, staff = identity_responses(result.registration.identity)
    return AuthResponse(
        access_token=result.access_token,
        expires_at=result.expires_at,
        user=user,
        staff=staff,
    )


def me_response(identity: IdentityView) -> MeResponse:
    user, staff = identity_responses(identity)
    return MeResponse(user=user, staff=staff)


def identity_responses(
    identity: IdentityView,
) -> tuple[CurrentUserResponse, CurrentStaffResponse | None]:
    permissions = sorted(identity.permissions, key=str)
    user = CurrentUserResponse(
        id=identity.user.id,
        telegram_id=identity.user.telegram_id,
        display_name=_user_display_name(identity),
        username=identity.user.username,
        photo_url=identity.user.photo_url,
        status=identity.user.status,
        role=identity.role,
        available_roles=list(identity.available_roles),
        permissions=permissions,
    )
    if identity.staff is None:
        return user, None
    staff = CurrentStaffResponse(
        id=identity.staff.id,
        role=identity.staff.role,
        display_name=identity.staff.display_name,
        position=identity.staff.position,
        permissions=permissions,
    )
    return user, staff


def card_response(record: CardViewRecord) -> CardResponse:
    settings = record.settings
    return CardResponse(
        user_id=record.user.id,
        display_name=_telegram_name(record.user.first_name, record.user.last_name),
        qr_payload=record.card.qr_token,
        short_code=record.card.short_code,
        balance_points=record.loyalty_state.points_balance,
        currency_name=settings.currency_name if settings is not None else "баллы",
        visit_streak=record.loyalty_state.visit_streak,
        visit_goal=settings.visit_required_count if settings is not None else 5,
        stamps=record.loyalty_state.stamp_count,
        stamp_goal=settings.stamp_required_count if settings is not None else 9,
        blocked=record.user.status is UserStatus.BLOCKED,
        updated_at=record.card.updated_at,
    )


def history_response(
    record: HistoryPageRecord,
    *,
    page: int,
    page_size: int,
) -> HistoryListResponse:
    return HistoryListResponse(
        items=[
            HistoryItemResponse(
                id=item.id,
                type=item.operation_type,
                description=_operation_description(item.operation_type),
                delta_points=item.points_delta,
                balance_after=item.balance_after,
                created_at=item.occurred_at,
                status=_operation_status(item.status),
            )
            for item in record.items
        ],
        page=page,
        page_size=page_size,
        total=record.total,
    )


def rewards_response(
    record: RewardPageRecord,
    *,
    page: int,
    page_size: int,
) -> RewardListResponse:
    return RewardListResponse(
        items=[
            RewardResponse(
                id=item.id,
                title=item.name,
                description=item.description,
                type=item.reward_type,
                status=item.status,
                expires_at=item.expires_at,
                created_at=item.created_at,
                redeemed_at=item.redeemed_at,
                terms=item.terms,
                qr_payload=item.qr_payload,
            )
            for item in record.items
        ],
        page=page,
        page_size=page_size,
        total=record.total,
    )


def points_menu_purchase_response(
    value: PointsMenuPurchaseOutcome,
) -> PointsMenuPurchaseResponse:
    return PointsMenuPurchaseResponse(
        operation_id=value.operation_id,
        reward_id=value.reward_id,
        item_id=value.item_id,
        item_name=value.item_name,
        points_spent=value.points_spent,
        balance_after=value.balance_after,
        qr_payload=value.qr_payload,
        expires_at=value.expires_at,
        idempotent_replay=value.idempotent_replay,
    )


def post_purchase_response(value: PostPurchaseView) -> PostPurchaseResponse:
    return PostPurchaseResponse(
        operation_id=value.operation_id,
        barista_name=value.barista_name,
        position=value.position,
        photo_url=(f"/api/v1/media/{value.photo_media_id}" if value.photo_media_id else None),
        tip_url=value.tip_url,
        tip_qr_url=(f"/api/v1/media/{value.tip_qr_media_id}" if value.tip_qr_media_id else None),
    )


def _user_display_name(identity: IdentityView) -> str:
    if identity.staff is not None and identity.staff.display_name:
        return identity.staff.display_name
    return _telegram_name(identity.user.first_name, identity.user.last_name)


def _telegram_name(first_name: str, last_name: str | None) -> str:
    return " ".join(value for value in (first_name, last_name) if value).strip()


def _operation_status(value: OperationStatus) -> HistoryPublicStatus:
    if value is OperationStatus.COMMITTED:
        return "completed"
    if value is OperationStatus.PENDING:
        return "pending"
    if value is OperationStatus.REVERSED:
        return "reversed"
    return "failed"


def _operation_description(operation_type: LoyaltyOperationType) -> str:
    descriptions = {
        LoyaltyOperationType.PURCHASE_ACCRUAL: "Начисление за покупку",
        LoyaltyOperationType.POINTS_REDEMPTION: "Списание баллов",
        LoyaltyOperationType.WELCOME_BONUS: "Приветственный бонус",
        LoyaltyOperationType.ADMIN_ADJUSTMENT: "Корректировка баланса",
        LoyaltyOperationType.OPERATION_REVERSAL: "Отмена операции",
        LoyaltyOperationType.POINTS_EXPIRATION: "Истечение баллов",
        LoyaltyOperationType.VISIT_MARK: "Отметка посещения",
        LoyaltyOperationType.STAMP_ADDED: "Добавлен штамп",
        LoyaltyOperationType.REWARD_CREATED: "Получена награда",
        LoyaltyOperationType.REWARD_REDEEMED: "Награда использована",
        LoyaltyOperationType.REWARD_CANCELLED: "Награда отменена",
    }
    return descriptions[operation_type]

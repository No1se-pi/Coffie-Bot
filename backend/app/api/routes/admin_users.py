"""Administrative customer and loyalty endpoints, not yet wired into the root router."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode, RewardStatus, UserStatus
from app.repositories.loyalty import LoyaltyRepository
from app.schemas.loyalty import (
    AdjustmentRequest,
    AdminUserListResponse,
    AdminUserResponse,
    CardReissueResponse,
    OperationListResponse,
    OperationResponse,
    ReasonRequest,
    RewardCancelRequest,
    RewardIssueRequest,
    RewardListResponse,
    UserStatusResponse,
    admin_user_response,
    card_reissue_response,
    operation_page_response,
    operation_response,
    reward_page_response,
    user_page_response,
    user_status_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.loyalty import LoyaltyService, RequestMetadata

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
ReadActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_USERS_READ)),
]
ManageActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_USERS_MANAGE)),
]


@router.get("", response_model=AdminUserListResponse)
async def list_users(
    session: DatabaseSession,
    actor: ReadActor,
    query: Annotated[str | None, Query(max_length=128)] = None,
    user_status: Annotated[UserStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AdminUserListResponse:
    value = await _service(session).list_users(
        actor,
        query=query,
        user_status=user_status,
        page=page,
        page_size=page_size,
    )
    return user_page_response(value, page=page, page_size=page_size)


@router.get("/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: UUID,
    session: DatabaseSession,
    actor: ReadActor,
) -> AdminUserResponse:
    return admin_user_response(await _service(session).get_admin_user(actor, user_id))


@router.get("/{user_id}/history", response_model=OperationListResponse)
async def get_user_history(
    user_id: UUID,
    session: DatabaseSession,
    actor: ReadActor,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OperationListResponse:
    value = await _service(session).list_user_history(
        actor,
        user_id=user_id,
        page=page,
        page_size=page_size,
    )
    return operation_page_response(value, page=page, page_size=page_size)


@router.get("/{user_id}/rewards", response_model=RewardListResponse)
async def get_user_rewards(
    user_id: UUID,
    session: DatabaseSession,
    actor: ReadActor,
    reward_status: Annotated[RewardStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RewardListResponse:
    value = await _service(session).list_user_rewards(
        actor,
        user_id=user_id,
        reward_status=reward_status,
        page=page,
        page_size=page_size,
    )
    return reward_page_response(value, page=page, page_size=page_size)


@router.post("/{user_id}/adjustments", response_model=OperationResponse)
async def adjust_points(
    user_id: UUID,
    payload: AdjustmentRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: ManageActor,
) -> OperationResponse:
    value = await _service(session).admin_adjust_points(
        actor,
        user_id=user_id,
        delta_points=payload.delta_points,
        reason=payload.reason,
        venue_id=payload.venue_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/{user_id}/block", response_model=UserStatusResponse)
async def block_user(
    user_id: UUID,
    payload: ReasonRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: ManageActor,
) -> UserStatusResponse:
    value = await _service(session).block_user(
        actor,
        user_id=user_id,
        reason=payload.reason,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return user_status_response(value)


@router.post("/{user_id}/unblock", response_model=UserStatusResponse)
async def unblock_user(
    user_id: UUID,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: ManageActor,
) -> UserStatusResponse:
    value = await _service(session).unblock_user(
        actor,
        user_id=user_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return user_status_response(value)


@router.post("/{user_id}/cards/reissue", response_model=CardReissueResponse)
async def reissue_card(
    user_id: UUID,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: ManageActor,
) -> CardReissueResponse:
    value = await _service(session).reissue_card(
        actor,
        user_id=user_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return card_reissue_response(value)


@router.post("/{user_id}/rewards", response_model=OperationResponse)
async def issue_reward(
    user_id: UUID,
    payload: RewardIssueRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: ManageActor,
) -> OperationResponse:
    value = await _service(session).issue_reward(
        actor,
        user_id=user_id,
        template_id=payload.template_id,
        validity_days=payload.validity_days,
        reason=payload.reason,
        venue_id=payload.venue_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/{user_id}/rewards/{reward_id}/cancel", response_model=OperationResponse)
async def cancel_reward(
    user_id: UUID,
    reward_id: UUID,
    payload: RewardCancelRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: ManageActor,
) -> OperationResponse:
    value = await _service(session).cancel_reward(
        actor,
        user_id=user_id,
        reward_id=reward_id,
        reason=payload.reason,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


def _service(session: AsyncSession) -> LoyaltyService:
    return LoyaltyService(LoyaltyRepository(session))


def _request_metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )

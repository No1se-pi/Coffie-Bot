"""Staff-facing loyalty endpoints; intentionally registered by the root router later."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode, Role
from app.repositories.loyalty import LoyaltyRepository
from app.schemas.loyalty import (
    AccrualPreviewResponse,
    AccrualRequest,
    CardLookupRequest,
    CardLookupResponse,
    OperationListResponse,
    OperationResponse,
    PurchasePreviewResponse,
    PurchaseRequest,
    ReasonRequest,
    RedemptionPreviewResponse,
    RedemptionRequest,
    RewardQrLookupRequest,
    RewardQrLookupResponse,
    StampRequest,
    VisitRequest,
    accrual_preview_response,
    card_lookup_response,
    operation_page_response,
    operation_response,
    purchase_preview_response,
    redemption_preview_response,
    reward_qr_lookup_response,
)
from app.security.rbac import Actor, require_permissions, require_roles
from app.services.loyalty import LoyaltyService, RequestMetadata

router = APIRouter(prefix="/staff", tags=["staff-loyalty"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post("/cards/lookup", response_model=CardLookupResponse)
async def lookup_card(
    payload: CardLookupRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.CARD_LOOKUP)),
    ],
) -> CardLookupResponse:
    value = await _service(session).lookup_card(
        actor,
        qr_token=payload.qr_token,
        short_code=payload.short_code,
        phone=payload.phone,
    )
    return card_lookup_response(value)


@router.post("/operations/accrual/preview", response_model=AccrualPreviewResponse)
async def preview_accrual(
    payload: AccrualRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.POINTS_ACCRUE)),
    ],
) -> AccrualPreviewResponse:
    value = await _service(session).preview_accrual(
        actor,
        user_id=payload.user_id,
        purchase_amount_minor=payload.purchase_amount_minor,
        location_id=payload.location_id,
    )
    return accrual_preview_response(value)


@router.post("/operations/accrual", response_model=OperationResponse)
async def confirm_accrual(
    payload: AccrualRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.POINTS_ACCRUE)),
    ],
) -> OperationResponse:
    value = await _service(session).confirm_accrual(
        actor,
        user_id=payload.user_id,
        purchase_amount_minor=payload.purchase_amount_minor,
        location_id=payload.location_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/operations/purchase/preview", response_model=PurchasePreviewResponse)
async def preview_purchase(
    payload: PurchaseRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.POINTS_ACCRUE)),
    ],
) -> PurchasePreviewResponse:
    value = await _service(session).preview_purchase(
        actor,
        user_id=payload.user_id,
        purchase_amount_minor=payload.purchase_amount_minor,
        stamps_to_add=payload.stamps_to_add,
        location_id=payload.location_id,
    )
    return purchase_preview_response(value)


@router.post("/operations/purchase", response_model=OperationResponse)
async def confirm_purchase(
    payload: PurchaseRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.POINTS_ACCRUE)),
    ],
) -> OperationResponse:
    value = await _service(session).confirm_purchase(
        actor,
        user_id=payload.user_id,
        purchase_amount_minor=payload.purchase_amount_minor,
        stamps_to_add=payload.stamps_to_add,
        location_id=payload.location_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/operations/redemption/preview", response_model=RedemptionPreviewResponse)
async def preview_redemption(
    payload: RedemptionRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.POINTS_REDEEM)),
    ],
) -> RedemptionPreviewResponse:
    value = await _service(session).preview_redemption(
        actor,
        user_id=payload.user_id,
        purchase_amount_minor=payload.purchase_amount_minor,
        requested_points=payload.requested_points,
        location_id=payload.location_id,
    )
    return redemption_preview_response(value)


@router.post("/operations/redemption", response_model=OperationResponse)
async def confirm_redemption(
    payload: RedemptionRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.POINTS_REDEEM)),
    ],
) -> OperationResponse:
    value = await _service(session).confirm_redemption(
        actor,
        user_id=payload.user_id,
        purchase_amount_minor=payload.purchase_amount_minor,
        requested_points=payload.requested_points,
        location_id=payload.location_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/operations/visits", response_model=OperationResponse)
async def mark_visit(
    payload: VisitRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.VISITS_MARK)),
    ],
) -> OperationResponse:
    value = await _service(session).mark_visit(
        actor,
        user_id=payload.user_id,
        location_id=payload.location_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/operations/stamps", response_model=OperationResponse)
async def add_stamps(
    payload: StampRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.STAMPS_ADD)),
    ],
) -> OperationResponse:
    value = await _service(session).add_stamps(
        actor,
        user_id=payload.user_id,
        stamps_to_add=payload.stamps_to_add,
        location_id=payload.location_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/rewards/lookup", response_model=RewardQrLookupResponse)
async def lookup_reward(
    payload: RewardQrLookupRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.REWARDS_REDEEM)),
    ],
) -> RewardQrLookupResponse:
    value = await _service(session).lookup_reward_qr(actor, qr_payload=payload.qr_payload)
    return reward_qr_lookup_response(value)


@router.post("/rewards/{reward_id}/redeem", response_model=OperationResponse)
async def redeem_reward(
    reward_id: UUID,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.REWARDS_REDEEM)),
    ],
) -> OperationResponse:
    value = await _service(session).redeem_reward(
        actor,
        reward_id=reward_id,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.post("/operations/{operation_id}/reverse", response_model=OperationResponse)
async def reverse_operation(
    operation_id: UUID,
    payload: ReasonRequest,
    request: Request,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
    actor: Annotated[
        Actor,
        Depends(require_roles(Role.STAFF, Role.ADMIN, Role.OWNER)),
    ],
) -> OperationResponse:
    value = await _service(session).reverse_operation(
        actor,
        operation_id=operation_id,
        reason=payload.reason,
        idempotency_key=str(idempotency_key),
        metadata=_request_metadata(request),
    )
    return operation_response(value)


@router.get("/operations/recent", response_model=OperationListResponse)
async def recent_operations(
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_roles(Role.STAFF, Role.ADMIN, Role.OWNER)),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OperationListResponse:
    value = await _service(session).list_recent_operations(
        actor,
        page=page,
        page_size=page_size,
    )
    return operation_page_response(value, page=page, page_size=page_size)


def _service(session: AsyncSession) -> LoyaltyService:
    return LoyaltyService(LoyaltyRepository(session))


def _request_metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )

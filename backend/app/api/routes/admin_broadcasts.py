"""Preview, create, confirm, inspect, and cancel Telegram broadcasts."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import BroadcastStatus, PermissionCode
from app.repositories.admin_broadcasts import AdminBroadcastRepository
from app.schemas.broadcasts import (
    BroadcastCancelRequest,
    BroadcastDraftRequest,
    BroadcastListResponse,
    BroadcastPreviewResponse,
    BroadcastResponse,
    BroadcastTransitionResponse,
    broadcast_page_response,
    broadcast_response,
    broadcast_transition_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.admin_broadcasts import (
    AdminBroadcastService,
    BroadcastRequestMetadata,
)

router = APIRouter(prefix="/admin/broadcasts", tags=["admin-broadcasts"])

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
BroadcastActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_BROADCASTS_MANAGE)),
]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


@router.post("/preview", response_model=BroadcastPreviewResponse)
async def preview_broadcast(
    payload: BroadcastDraftRequest,
    session: DatabaseSession,
    actor: BroadcastActor,
) -> BroadcastPreviewResponse:
    del actor
    audience_count = await _service(session).preview(payload.as_draft())
    return BroadcastPreviewResponse(audience_count=audience_count)


@router.post("", response_model=BroadcastResponse, status_code=status.HTTP_201_CREATED)
async def create_broadcast(
    payload: BroadcastDraftRequest,
    request: Request,
    session: DatabaseSession,
    actor: BroadcastActor,
    idempotency_key: IdempotencyKey,
) -> BroadcastResponse:
    value = await _service(session).create(
        actor,
        draft=payload.as_draft(),
        idempotency_key=str(idempotency_key),
        metadata=_metadata(request),
    )
    return broadcast_response(value)


@router.get("", response_model=BroadcastListResponse)
async def list_broadcasts(
    session: DatabaseSession,
    actor: BroadcastActor,
    broadcast_status: Annotated[BroadcastStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BroadcastListResponse:
    del actor
    value = await _service(session).list(
        broadcast_status=broadcast_status,
        page=page,
        page_size=page_size,
    )
    return broadcast_page_response(value, page=page, page_size=page_size)


@router.get("/{broadcast_id}", response_model=BroadcastResponse)
async def get_broadcast(
    broadcast_id: UUID,
    session: DatabaseSession,
    actor: BroadcastActor,
) -> BroadcastResponse:
    del actor
    return broadcast_response(await _service(session).get(broadcast_id))


@router.post("/{broadcast_id}/confirm", response_model=BroadcastTransitionResponse)
async def confirm_broadcast(
    broadcast_id: UUID,
    request: Request,
    session: DatabaseSession,
    actor: BroadcastActor,
) -> BroadcastTransitionResponse:
    value = await _service(session).confirm(
        actor,
        broadcast_id=broadcast_id,
        metadata=_metadata(request),
    )
    return broadcast_transition_response(value)


@router.post("/{broadcast_id}/cancel", response_model=BroadcastTransitionResponse)
async def cancel_broadcast(
    broadcast_id: UUID,
    payload: BroadcastCancelRequest,
    request: Request,
    session: DatabaseSession,
    actor: BroadcastActor,
) -> BroadcastTransitionResponse:
    value = await _service(session).cancel(
        actor,
        broadcast_id=broadcast_id,
        reason=payload.reason,
        metadata=_metadata(request),
    )
    return broadcast_transition_response(value)


def _service(session: AsyncSession) -> AdminBroadcastService:
    return AdminBroadcastService(AdminBroadcastRepository(session))


def _metadata(request: Request) -> BroadcastRequestMetadata:
    return BroadcastRequestMetadata(
        ip_address=request.client.host if request.client is not None else None,
        user_agent=request.headers.get("user-agent"),
    )

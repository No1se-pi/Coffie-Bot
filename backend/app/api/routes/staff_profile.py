"""Own moderated tip profile and admin moderation routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.admin import AdminRepository
from app.schemas.admin import (
    PendingTipProfileListResponse,
    PendingTipProfileResponse,
    TipModerationRequest,
    TipProfileResponse,
    TipProfileUpdate,
    pending_tip_profile_list_response,
    pending_tip_profile_response,
    tip_profile_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.admin import AdminService, RequestMetadata

router = APIRouter(tags=["staff-tip-profile"])

TipActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.OWN_TIP_PROFILE_MANAGE)),
]
AdminActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_STAFF_MANAGE)),
]


def _service(session: AsyncSession) -> AdminService:
    return AdminService(repository=AdminRepository(session))


def _metadata(request: Request) -> RequestMetadata:
    return RequestMetadata(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


@router.get("/staff/me/tip-profile", response_model=TipProfileResponse)
async def get_own_tip_profile(
    actor: TipActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TipProfileResponse:
    return tip_profile_response(await _service(session).get_own_tip_profile(actor=actor))


@router.put("/staff/me/tip-profile", response_model=TipProfileResponse)
async def update_own_tip_profile(
    payload: TipProfileUpdate,
    request: Request,
    actor: TipActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TipProfileResponse:
    view = await _service(session).update_own_tip_profile(
        actor=actor,
        display_name=payload.display_name,
        position=payload.position,
        bio=payload.bio,
        tip_url=payload.tip_url,
        photo_media_id=payload.photo_media_id,
        tip_qr_media_id=payload.tip_qr_media_id,
        metadata=_metadata(request),
    )
    return tip_profile_response(view)


@router.get("/admin/tip-profiles/pending", response_model=PendingTipProfileListResponse)
async def list_pending_tip_profiles(
    _actor: AdminActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PendingTipProfileListResponse:
    result = await _service(session).list_pending_tip_profiles(page=page, page_size=page_size)
    return pending_tip_profile_list_response(result, page=page, page_size=page_size)


@router.post(
    "/admin/tip-profiles/{profile_id}/approve",
    response_model=PendingTipProfileResponse,
)
async def approve_tip_profile(
    profile_id: UUID,
    payload: TipModerationRequest,
    request: Request,
    actor: AdminActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PendingTipProfileResponse:
    record = await _service(session).approve_tip_profile(
        actor=actor,
        profile_id=profile_id,
        moderation_note=payload.moderation_note,
        metadata=_metadata(request),
    )
    return pending_tip_profile_response(record)


@router.post(
    "/admin/tip-profiles/{profile_id}/hide",
    response_model=PendingTipProfileResponse,
)
async def hide_tip_profile(
    profile_id: UUID,
    payload: TipModerationRequest,
    request: Request,
    actor: AdminActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PendingTipProfileResponse:
    record = await _service(session).hide_tip_profile(
        actor=actor,
        profile_id=profile_id,
        moderation_note=payload.moderation_note,
        metadata=_metadata(request),
    )
    return pending_tip_profile_response(record)

"""Administrative Venue catalogue and lifecycle endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.venues import VenueRepository
from app.schemas.venues import (
    VenueAdminListResponse,
    VenueAdminResponse,
    VenueCreate,
    VenueUpdate,
    venue_admin_list_response,
    venue_admin_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.venues import VenueRequestMetadata, VenueService

router = APIRouter(prefix="/admin/venues", tags=["admin-venues"])

ContentActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_CONTENT_MANAGE)),
]


def _service(session: AsyncSession) -> VenueService:
    return VenueService(VenueRepository(session))


def _metadata(request: Request) -> VenueRequestMetadata:
    return VenueRequestMetadata(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


@router.get("", response_model=VenueAdminListResponse)
async def list_venues(
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    include_archived: bool = False,
) -> VenueAdminListResponse:
    result = await _service(session).list_admin(
        page=page,
        page_size=page_size,
        include_archived=include_archived,
    )
    return venue_admin_list_response(result, page=page, page_size=page_size)


@router.get("/{venue_id}", response_model=VenueAdminResponse)
async def get_venue(
    venue_id: UUID,
    _actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VenueAdminResponse:
    return venue_admin_response(await _service(session).get_admin(venue_id))


@router.post("", response_model=VenueAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_venue(
    payload: VenueCreate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VenueAdminResponse:
    venue = await _service(session).create(
        actor=actor,
        metadata=_metadata(request),
        **payload.model_dump(),
    )
    return venue_admin_response(venue)


@router.patch("/{venue_id}", response_model=VenueAdminResponse)
async def update_venue(
    venue_id: UUID,
    payload: VenueUpdate,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VenueAdminResponse:
    venue = await _service(session).update(
        actor=actor,
        venue_id=venue_id,
        updates=payload.model_dump(exclude_unset=True),
        metadata=_metadata(request),
    )
    return venue_admin_response(venue)


@router.post("/{venue_id}/archive", response_model=VenueAdminResponse)
async def archive_venue(
    venue_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VenueAdminResponse:
    venue = await _service(session).archive(
        actor=actor,
        venue_id=venue_id,
        metadata=_metadata(request),
    )
    return venue_admin_response(venue)


@router.post("/{venue_id}/restore", response_model=VenueAdminResponse)
async def restore_venue(
    venue_id: UUID,
    request: Request,
    actor: ContentActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VenueAdminResponse:
    venue = await _service(session).restore(
        actor=actor,
        venue_id=venue_id,
        metadata=_metadata(request),
    )
    return venue_admin_response(venue)

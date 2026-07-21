"""Admin staff membership, invite, role, permission, and session routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode, Role
from app.repositories.admin import AdminRepository
from app.schemas.admin import (
    SessionsRevokedResponse,
    StaffCreate,
    StaffInviteCreate,
    StaffInviteResponse,
    StaffListResponse,
    StaffResponse,
    StaffRoleUpdate,
    StaffUpdate,
    staff_invite_response,
    staff_list_response,
    staff_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.admin import AdminService, RequestMetadata

router = APIRouter(prefix="/admin/staff", tags=["admin-staff"])

StaffActor = Annotated[
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


@router.get("", response_model=StaffListResponse)
async def list_staff(
    _actor: StaffActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    role: Role | None = None,
    active: bool | None = None,
    query: Annotated[str | None, Query(max_length=128)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> StaffListResponse:
    result = await _service(session).list_staff(
        role=role,
        active=active,
        query=query.strip() if query else None,
        page=page,
        page_size=page_size,
    )
    return staff_list_response(result, page=page, page_size=page_size)


@router.post("", response_model=StaffResponse, status_code=status.HTTP_201_CREATED)
async def create_staff(
    payload: StaffCreate,
    request: Request,
    actor: StaffActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StaffResponse:
    item = await _service(session).create_staff(
        actor=actor, metadata=_metadata(request), **payload.model_dump()
    )
    return staff_response(item)


@router.patch("/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: UUID,
    payload: StaffUpdate,
    request: Request,
    actor: StaffActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StaffResponse:
    values = payload.model_dump(exclude_unset=True)
    permissions = values.pop("permissions", None)
    item = await _service(session).update_staff(
        actor=actor,
        staff_id=staff_id,
        updates=values,
        permissions=permissions,
        metadata=_metadata(request),
    )
    return staff_response(item)


@router.post("/{staff_id}/role", response_model=StaffResponse)
async def change_staff_role(
    staff_id: UUID,
    payload: StaffRoleUpdate,
    request: Request,
    actor: StaffActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StaffResponse:
    item = await _service(session).change_staff_role(
        actor=actor,
        staff_id=staff_id,
        new_role=payload.role,
        metadata=_metadata(request),
    )
    return staff_response(item)


@router.post("/{staff_id}/revoke-sessions", response_model=SessionsRevokedResponse)
async def revoke_staff_sessions(
    staff_id: UUID,
    request: Request,
    actor: StaffActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SessionsRevokedResponse:
    revoked = await _service(session).revoke_staff_sessions(
        actor=actor, staff_id=staff_id, metadata=_metadata(request)
    )
    return SessionsRevokedResponse(revoked_sessions=revoked)


@router.post(
    "/invites",
    response_model=StaffInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_staff_invite(
    payload: StaffInviteCreate,
    request: Request,
    actor: StaffActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StaffInviteResponse:
    result = await _service(session).create_staff_invite(
        actor=actor, metadata=_metadata(request), **payload.model_dump()
    )
    return staff_invite_response(result)

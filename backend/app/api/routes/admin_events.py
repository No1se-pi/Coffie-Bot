"""Administrative structured audit-event read API, registered separately later."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import AuditSeverity, PermissionCode
from app.repositories.loyalty import LoyaltyRepository
from app.schemas.loyalty import AuditEventListResponse, audit_event_page_response
from app.security.rbac import Actor, require_permissions
from app.services.loyalty import LoyaltyService

router = APIRouter(prefix="/admin/events", tags=["admin-events"])


@router.get("", response_model=AuditEventListResponse)
async def list_events(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_EVENTS_READ)),
    ],
    started_at: Annotated[datetime | None, Query()] = None,
    ended_at: Annotated[datetime | None, Query()] = None,
    actor_user_id: Annotated[UUID | None, Query(alias="actor")] = None,
    subject_user_id: Annotated[UUID | None, Query(alias="user")] = None,
    event_type: Annotated[str | None, Query(alias="type", max_length=100)] = None,
    severity: Annotated[AuditSeverity | None, Query()] = None,
    suspicious: Annotated[bool | None, Query()] = None,
    adjustments: Annotated[bool | None, Query()] = None,
    reversed_operations: Annotated[bool | None, Query(alias="reversed")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditEventListResponse:
    value = await LoyaltyService(LoyaltyRepository(session)).list_audit_events(
        actor,
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
    return audit_event_page_response(value, page=page, page_size=page_size)

"""Owner/admin dashboard and aggregate analytics endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    AdminAnalyticsResponse,
    AdminDashboardResponse,
    analytics_response,
    dashboard_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.analytics import AnalyticsService

router = APIRouter(prefix="/admin", tags=["admin-analytics"])


def _service(session: AsyncSession) -> AnalyticsService:
    return AnalyticsService(AnalyticsRepository(session))


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_EVENTS_READ)),
    ],
) -> AdminDashboardResponse:
    return dashboard_response(await _service(session).dashboard(actor))


@router.get("/analytics", response_model=AdminAnalyticsResponse)
async def get_analytics(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_EVENTS_READ)),
    ],
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> AdminAnalyticsResponse:
    return analytics_response(await _service(session).analytics(actor, days=days))

"""PostgreSQL smoke coverage for every Phase 8 aggregate query."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.models.enums import PermissionCode, Role
from app.repositories.analytics import AnalyticsRepository
from app.security.rbac import Actor
from app.services.analytics import AnalyticsService


def _database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value or not value.startswith("postgresql+asyncpg://"):
        pytest.skip("An async PostgreSQL DATABASE_URL is required")
    return value


def _actor(*, permitted: bool) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=1,
        session_id=uuid4(),
        role=Role.ADMIN if permitted else Role.CUSTOMER,
        staff_member_id=uuid4() if permitted else None,
        permissions=(frozenset({PermissionCode.ADMIN_EVENTS_READ}) if permitted else frozenset()),
    )


@pytest.mark.asyncio
async def test_admin_analytics_queries_are_complete_and_permission_guarded() -> None:
    engine = create_async_engine(_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 27, 12, tzinfo=UTC)
    try:
        async with sessions() as session:
            service = AnalyticsService(AnalyticsRepository(session))
            dashboard = await service.dashboard(_actor(permitted=True), now=now)
            analytics = await service.analytics(_actor(permitted=True), days=7, now=now)

            assert int(dashboard.values["customers"]) >= 0
            assert len(analytics.orders_by_day) == 7
            assert set(analytics.values) == {
                "orders_by_venue",
                "popular_items",
                "promotion_usage",
                "employee_activity",
                "loyalty",
                "customers",
                "subscriptions",
                "receipts",
                "delivery",
            }
            with pytest.raises(AppError) as denied:
                await service.analytics(_actor(permitted=False), days=7, now=now)
            assert denied.value.status_code == 403
    finally:
        await engine.dispose()

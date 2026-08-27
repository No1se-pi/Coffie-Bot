"""Business-facing orchestration for privacy-safe administrative aggregates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.enums import PermissionCode
from app.repositories.analytics import AnalyticsRepository
from app.security.rbac import Actor
from app.services.loyalty_calculations import business_date_for, business_day_bounds_utc


@dataclass(frozen=True, slots=True)
class DashboardView:
    generated_at: datetime
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AnalyticsView:
    generated_at: datetime
    days: int
    started_at: datetime
    ended_at: datetime
    orders_by_day: tuple[Mapping[str, Any], ...]
    values: Mapping[str, Any]


class AnalyticsService:
    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    async def dashboard(self, actor: Actor, *, now: datetime | None = None) -> DashboardView:
        _require_analytics(actor)
        current_time = _aware_now(now)
        timezone_name, boundary_minutes = await self._repository.clock_settings()
        business_date = business_date_for(
            current_time,
            timezone_name=timezone_name,
            boundary_minutes=boundary_minutes,
        )
        started_at, ended_at = business_day_bounds_utc(
            business_date,
            timezone_name=timezone_name,
            boundary_minutes=boundary_minutes,
        )
        return DashboardView(
            generated_at=current_time,
            values=await self._repository.dashboard(
                started_at=started_at,
                ended_at=ended_at,
                current_time=current_time,
            ),
        )

    async def analytics(
        self,
        actor: Actor,
        *,
        days: int,
        now: datetime | None = None,
    ) -> AnalyticsView:
        _require_analytics(actor)
        current_time = _aware_now(now)
        timezone_name, _ = await self._repository.clock_settings()
        started_at = current_time - timedelta(days=days)
        raw = await self._repository.analytics(
            started_at=started_at,
            ended_at=current_time,
            timezone_name=timezone_name,
        )
        by_day = {row["day"]: row for row in raw.pop("orders_by_day")}
        local_today = current_time.astimezone(ZoneInfo(timezone_name)).date()
        # A complete series keeps chart spacing stable even on quiet days.
        orders_by_day: list[Mapping[str, Any]] = []
        for offset in range(days - 1, -1, -1):
            day = local_today - timedelta(days=offset)
            orders_by_day.append(by_day.get(day, {"day": day, "orders": 0, "revenue_minor": 0}))
        return AnalyticsView(
            generated_at=current_time,
            days=days,
            started_at=started_at,
            ended_at=current_time,
            orders_by_day=tuple(orders_by_day),
            values=raw,
        )


def _require_analytics(actor: Actor) -> None:
    if not actor.can(PermissionCode.ADMIN_EVENTS_READ):
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="Insufficient permissions",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _aware_now(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return result.astimezone(UTC)

"""Read-only public content queries and authenticated customer feedback writes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.access import StaffMember, User
from app.models.audit import AuditEvent
from app.models.content import AppSetting, Location, MenuCategory, MenuItem, Promotion, Venue
from app.models.enums import (
    AuditSeverity,
    FeedbackCategory,
    FeedbackStatus,
    PromotionStatus,
    TipProfileStatus,
)
from app.models.staff import FeedbackItem, StaffTipProfile


@dataclass(frozen=True, slots=True)
class PublicStaffProfileRecord:
    profile: StaffTipProfile
    staff: StaffMember
    user: User


class PublicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_menu_categories(self, *, venue_id: UUID | None = None) -> list[MenuCategory]:
        filters: list[ColumnElement[bool]] = [
            MenuCategory.is_visible.is_(True),
            MenuCategory.archived_at.is_(None),
            Venue.is_active.is_(True),
            Venue.archived_at.is_(None),
        ]
        if venue_id is not None:
            filters.append(MenuCategory.venue_id == venue_id)
        return list(
            (
                await self._session.scalars(
                    select(MenuCategory)
                    .join(Venue, Venue.id == MenuCategory.venue_id)
                    .where(*filters)
                    .order_by(MenuCategory.sort_order, MenuCategory.id)
                )
            ).all()
        )

    async def list_menu_items(
        self,
        *,
        category_id: UUID | None,
        available: bool | None,
        venue_id: UUID | None = None,
    ) -> list[MenuItem]:
        filters: list[ColumnElement[bool]] = [
            MenuItem.is_visible.is_(True),
            MenuItem.archived_at.is_(None),
            MenuCategory.is_visible.is_(True),
            MenuCategory.archived_at.is_(None),
            Venue.is_active.is_(True),
            Venue.archived_at.is_(None),
        ]
        if category_id is not None:
            filters.append(MenuItem.category_id == category_id)
        if available is not None:
            filters.append(MenuItem.is_available == available)
        if venue_id is not None:
            filters.append(MenuItem.venue_id == venue_id)
        return list(
            (
                await self._session.scalars(
                    select(MenuItem)
                    .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
                    .join(Venue, Venue.id == MenuItem.venue_id)
                    .where(*filters)
                    .order_by(MenuItem.sort_order, MenuItem.id)
                )
            ).all()
        )

    async def list_promotions(
        self,
        *,
        active: bool,
        venue_id: UUID | None = None,
        now: datetime | None = None,
    ) -> list[Promotion]:
        current_time = now or datetime.now(UTC)
        filters = [Promotion.status == PromotionStatus.PUBLISHED]
        if venue_id is not None:
            filters.append(Promotion.venue_id == venue_id)
        if active:
            filters.extend(
                [
                    or_(Promotion.starts_at.is_(None), Promotion.starts_at <= current_time),
                    or_(Promotion.ends_at.is_(None), Promotion.ends_at > current_time),
                ]
            )
        return list(
            (
                await self._session.scalars(
                    select(Promotion)
                    .where(*filters)
                    .order_by(Promotion.published_at.desc().nullslast(), Promotion.id)
                )
            ).all()
        )

    async def get_public_settings(self) -> dict[str, Any]:
        rows = (
            await self._session.execute(
                select(AppSetting.key, AppSetting.value).where(AppSetting.is_public.is_(True))
            )
        ).all()
        settings: dict[str, Any] = {}
        for key, value in rows:
            settings[str(key)] = value
        return settings

    async def list_locations(self) -> list[Location]:
        return list(
            (
                await self._session.scalars(
                    select(Location)
                    .where(Location.is_active.is_(True))
                    .order_by(Location.sort_order, Location.id)
                )
            ).all()
        )

    async def list_staff_profiles(self) -> list[PublicStaffProfileRecord]:
        statement = (
            select(StaffTipProfile, StaffMember, User)
            .join(StaffMember, StaffMember.id == StaffTipProfile.staff_member_id)
            .join(User, User.id == StaffMember.user_id)
            .where(
                StaffTipProfile.status == TipProfileStatus.APPROVED,
                StaffTipProfile.is_visible.is_(True),
                StaffMember.is_active.is_(True),
            )
            .order_by(StaffTipProfile.sort_order, StaffTipProfile.id)
        )
        return [
            PublicStaffProfileRecord(profile=row[0], staff=row[1], user=row[2])
            for row in (await self._session.execute(statement)).all()
        ]

    async def create_feedback(
        self,
        *,
        user_id: UUID,
        rating: int,
        category: FeedbackCategory,
        message: str,
        may_contact: bool,
        ip_address: str | None,
        user_agent: str | None,
    ) -> FeedbackItem:
        feedback = FeedbackItem(
            id=uuid4(),
            user_id=user_id,
            rating=rating,
            category=category,
            message=message,
            may_contact=may_contact,
            status=FeedbackStatus.NEW,
        )
        audit = AuditEvent(
            id=uuid4(),
            event_type="feedback.created",
            actor_user_id=user_id,
            subject_user_id=user_id,
            object_type="feedback",
            object_id=feedback.id,
            event_metadata={
                "rating": rating,
                "category": category.value,
                "may_contact": may_contact,
            },
            severity=AuditSeverity.INFO,
            is_suspicious=False,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add_all([feedback, audit])
        await self._session.flush()
        await self._session.commit()
        return feedback

"""SQL queries for public review creation and moderation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import StaffMember, User
from app.models.content import Venue
from app.models.engagement import PublicReview
from app.models.enums import ReviewStatus, UserStatus
from app.models.orders import CustomerOrder, OrderSuborder


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    review: PublicReview
    venue_name: str
    employee_name: str | None


class ReviewRepository:
    """Repository whose service owns the commit boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        if not self._session.in_transaction():
            async with self._session.begin():
                yield
            return
        try:
            yield
        except BaseException:
            await self._session.rollback()
            raise
        else:
            await self._session.commit()

    async def get_user(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_venue(self, venue_id: UUID) -> Venue | None:
        return await self._session.get(Venue, venue_id)

    async def get_employee(self, staff_id: UUID) -> StaffMember | None:
        return await self._session.get(StaffMember, staff_id)

    async def order_matches(self, *, order_id: UUID, user_id: UUID, venue_id: UUID) -> bool:
        return (
            await self._session.scalar(
                select(OrderSuborder.id)
                .join(CustomerOrder, CustomerOrder.id == OrderSuborder.order_id)
                .where(
                    CustomerOrder.id == order_id,
                    CustomerOrder.user_id == user_id,
                    OrderSuborder.venue_id == venue_id,
                )
            )
            is not None
        )

    async def get(self, review_id: UUID, *, for_update: bool = False) -> PublicReview | None:
        statement = select(PublicReview).where(PublicReview.id == review_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PublicReview | None, await self._session.scalar(statement))

    async def list_records(
        self,
        *,
        status: ReviewStatus | None = None,
        user_id: UUID | None = None,
        venue_id: UUID | None = None,
        limit: int = 100,
    ) -> list[ReviewRecord]:
        filters = []
        if status is not None:
            filters.append(PublicReview.status == status)
        if user_id is not None:
            filters.append(PublicReview.user_id == user_id)
        if venue_id is not None:
            filters.append(PublicReview.venue_id == venue_id)
        rows = (
            await self._session.execute(
                select(PublicReview, Venue.name, StaffMember.display_name)
                .join(Venue, Venue.id == PublicReview.venue_id)
                .outerjoin(StaffMember, StaffMember.id == PublicReview.employee_staff_id)
                .where(*filters)
                .order_by(PublicReview.created_at.desc(), PublicReview.id.desc())
                .limit(limit)
            )
        ).all()
        return [
            ReviewRecord(review=row[0], venue_name=row[1], employee_name=row[2]) for row in rows
        ]

    async def active_customer(self, user_id: UUID) -> User | None:
        return cast(
            User | None,
            await self._session.scalar(
                select(User).where(User.id == user_id, User.status == UserStatus.ACTIVE)
            ),
        )

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()


def review_record(review: PublicReview, venue: Venue, employee: StaffMember | None) -> ReviewRecord:
    return ReviewRecord(
        review=review,
        venue_name=venue.name,
        employee_name=employee.display_name if employee is not None else None,
    )

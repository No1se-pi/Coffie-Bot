"""SQL access for employee monthly allowances."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import StaffMember, User
from app.models.content import AppSetting, MenuItem
from app.models.enums import Role, UserStatus
from app.models.loyalty import Reward
from app.models.staff_benefits import StaffBenefitGrant, StaffBenefitOperation, StaffBenefitPolicy


class StaffBenefitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            if not self.session.in_transaction():
                await self.session.begin()
            yield
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise

    async def lock_staff(self, staff_id: UUID) -> tuple[User, StaffMember] | None:
        user_id = await self.session.scalar(
            select(StaffMember.user_id).where(StaffMember.id == staff_id)
        )
        if user_id is None:
            return None
        user = await self.session.scalar(select(User).where(User.id == user_id).with_for_update())
        staff = await self.session.scalar(
            select(StaffMember).where(StaffMember.id == staff_id).with_for_update()
        )
        return (user, staff) if user is not None and staff is not None else None

    async def policy(self, staff_id: UUID) -> StaffBenefitPolicy | None:
        return cast(
            StaffBenefitPolicy | None,
            await self.session.scalar(
                select(StaffBenefitPolicy).where(StaffBenefitPolicy.staff_id == staff_id)
            ),
        )

    async def grants(self, staff_id: UUID) -> list[StaffBenefitGrant]:
        return list(
            (
                await self.session.scalars(
                    select(StaffBenefitGrant)
                    .where(StaffBenefitGrant.staff_id == staff_id)
                    .order_by(StaffBenefitGrant.period)
                    .with_for_update()
                )
            ).all()
        )

    async def operation(self, staff_id: UUID, key: str) -> StaffBenefitOperation | None:
        return cast(
            StaffBenefitOperation | None,
            await self.session.scalar(
                select(StaffBenefitOperation).where(
                    StaffBenefitOperation.staff_id == staff_id,
                    StaffBenefitOperation.idempotency_key == key,
                )
            ),
        )

    async def item(self, item_id: UUID) -> MenuItem | None:
        return cast(
            MenuItem | None,
            await self.session.scalar(
                select(MenuItem).where(MenuItem.id == item_id).with_for_update()
            ),
        )

    async def reward(self, reward_id: UUID) -> Reward | None:
        return await self.session.get(Reward, reward_id)

    async def available_ids(self, ids: set[UUID]) -> set[UUID]:
        return set(
            (
                await self.session.scalars(
                    select(MenuItem.id).where(
                        MenuItem.id.in_(ids),
                        MenuItem.archived_at.is_(None),
                        MenuItem.is_visible.is_(True),
                    )
                )
            ).all()
        )

    async def timezone(self) -> str:
        installation = await self.session.scalar(
            select(AppSetting.value).where(AppSetting.key == "installation")
        )
        return str(installation.get("timezone", "UTC")) if installation else "UTC"

    async def due_staff(self, period: date, now: datetime, limit: int) -> list[UUID]:
        current = exists(
            select(StaffBenefitGrant.id).where(
                StaffBenefitGrant.staff_id == StaffMember.id, StaffBenefitGrant.period == period
            )
        )
        expired = exists(
            select(StaffBenefitGrant.id).where(
                StaffBenefitGrant.staff_id == StaffMember.id,
                StaffBenefitGrant.expires_at <= now,
                StaffBenefitGrant.remaining_points > 0,
            )
        )
        statement = (
            select(StaffMember.id)
            .join(User, User.id == StaffMember.user_id)
            .join(StaffBenefitPolicy, StaffBenefitPolicy.staff_id == StaffMember.id)
            .where(
                or_(
                    expired,
                    and_(
                        StaffBenefitPolicy.enabled.is_(True),
                        StaffMember.is_active.is_(True),
                        StaffMember.archived_at.is_(None),
                        StaffMember.role != Role.COURIER,
                        User.status == UserStatus.ACTIVE,
                        ~current,
                    ),
                )
            )
            .order_by(StaffMember.id)
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    def add(self, *objects: object) -> None:
        self.session.add_all(objects)

    async def flush(self) -> None:
        await self.session.flush()

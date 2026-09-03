"""Persistence adapter for pass templates, issued passes, and usage ledger."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.cards import UserCard
from app.models.content import MenuCategory, MenuItem, Venue
from app.models.engagement import (
    CustomerPass,
    PassPurchase,
    PassTemplate,
    PassTemplateCategory,
    PassTemplateItem,
    PassTemplateVenue,
    PassUsage,
)
from app.models.enums import CardStatus, PassStatus, UserStatus


@dataclass(frozen=True, slots=True)
class TemplateAccess:
    template: PassTemplate
    venue_ids: frozenset[UUID]
    category_ids: frozenset[UUID]
    item_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class PassRecord:
    customer_pass: CustomerPass
    usage_count: int


@dataclass(frozen=True, slots=True)
class PassQrRecord:
    customer_pass: CustomerPass
    user: User
    customer_short_code: str


class SubscriptionRepository:
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

    async def acquire_lock(self, namespace: str, key: str) -> None:
        digest = hashlib.sha256(f"{namespace}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], "big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_template(
        self, template_id: UUID, *, for_update: bool = False
    ) -> PassTemplate | None:
        statement = select(PassTemplate).where(PassTemplate.id == template_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PassTemplate | None, await self._session.scalar(statement))

    async def template_access(self, template: PassTemplate) -> TemplateAccess:
        venues = frozenset(
            (
                await self._session.scalars(
                    select(PassTemplateVenue.venue_id).where(
                        PassTemplateVenue.template_id == template.id
                    )
                )
            ).all()
        )
        categories = frozenset(
            (
                await self._session.scalars(
                    select(PassTemplateCategory.category_id).where(
                        PassTemplateCategory.template_id == template.id
                    )
                )
            ).all()
        )
        items = frozenset(
            (
                await self._session.scalars(
                    select(PassTemplateItem.item_id).where(
                        PassTemplateItem.template_id == template.id
                    )
                )
            ).all()
        )
        return TemplateAccess(template, venues, categories, items)

    async def list_templates(self, *, active_only: bool) -> list[TemplateAccess]:
        statement = select(PassTemplate)
        if active_only:
            statement = statement.where(PassTemplate.is_active.is_(True))
        templates = list(
            (await self._session.scalars(statement.order_by(PassTemplate.created_at.desc()))).all()
        )
        return [await self.template_access(value) for value in templates]

    async def find_purchase(self, user_id: UUID, key: str) -> PassPurchase | None:
        return cast(
            PassPurchase | None,
            await self._session.scalar(
                select(PassPurchase).where(
                    PassPurchase.user_id == user_id,
                    PassPurchase.idempotency_key == key,
                )
            ),
        )

    async def get_purchase(
        self, purchase_id: UUID, *, for_update: bool = False
    ) -> PassPurchase | None:
        statement = select(PassPurchase).where(PassPurchase.id == purchase_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(PassPurchase | None, await self._session.scalar(statement))

    async def list_purchases(
        self, *, user_id: UUID | None = None, status: str | None = None
    ) -> list[PassPurchase]:
        statement = select(PassPurchase)
        if user_id is not None:
            statement = statement.where(PassPurchase.user_id == user_id)
        if status is not None:
            statement = statement.where(PassPurchase.status == status)
        return list(
            await self._session.scalars(
                statement.order_by(PassPurchase.created_at.desc(), PassPurchase.id.desc())
            )
        )

    async def existing_entity_ids(
        self, *, venue_ids: set[UUID], category_ids: set[UUID], item_ids: set[UUID]
    ) -> tuple[set[UUID], set[UUID], set[UUID]]:
        venues = (
            set(
                (await self._session.scalars(select(Venue.id).where(Venue.id.in_(venue_ids)))).all()
            )
            if venue_ids
            else set()
        )
        categories = (
            set(
                (
                    await self._session.scalars(
                        select(MenuCategory.id).where(MenuCategory.id.in_(category_ids))
                    )
                ).all()
            )
            if category_ids
            else set()
        )
        items = (
            set(
                (
                    await self._session.scalars(
                        select(MenuItem.id).where(MenuItem.id.in_(item_ids))
                    )
                ).all()
            )
            if item_ids
            else set()
        )
        return venues, categories, items

    async def replace_template_scopes(
        self,
        template_id: UUID,
        *,
        venue_ids: frozenset[UUID],
        category_ids: frozenset[UUID],
        item_ids: frozenset[UUID],
    ) -> None:
        """Replace applicability rows while the template row is locked by the service."""

        for model in (PassTemplateVenue, PassTemplateCategory, PassTemplateItem):
            await self._session.execute(delete(model).where(model.template_id == template_id))
        self.add_all(
            [
                *(
                    PassTemplateVenue(template_id=template_id, venue_id=value)
                    for value in venue_ids
                ),
                *(
                    PassTemplateCategory(template_id=template_id, category_id=value)
                    for value in category_ids
                ),
                *(PassTemplateItem(template_id=template_id, item_id=value) for value in item_ids),
            ]
        )

    async def active_user(self, user_id: UUID) -> User | None:
        return cast(
            User | None,
            await self._session.scalar(
                select(User).where(User.id == user_id, User.status == UserStatus.ACTIVE)
            ),
        )

    async def find_issue(self, staff_id: UUID, key: str) -> CustomerPass | None:
        return cast(
            CustomerPass | None,
            await self._session.scalar(
                select(CustomerPass).where(
                    CustomerPass.issued_by_staff_id == staff_id, CustomerPass.idempotency_key == key
                )
            ),
        )

    async def get_pass(self, pass_id: UUID, *, for_update: bool = False) -> CustomerPass | None:
        statement = select(CustomerPass).where(CustomerPass.id == pass_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(CustomerPass | None, await self._session.scalar(statement))

    async def get_pass_by_qr(self, qr_payload: str) -> PassQrRecord | None:
        row = (
            await self._session.execute(
                select(CustomerPass, User, UserCard.short_code)
                .join(User, User.id == CustomerPass.user_id)
                .join(
                    UserCard,
                    (UserCard.user_id == User.id) & (UserCard.status == CardStatus.ACTIVE),
                )
                .where(CustomerPass.qr_payload == qr_payload)
            )
        ).one_or_none()
        return PassQrRecord(row[0], row[1], row[2]) if row is not None else None

    async def find_usage(self, staff_id: UUID, key: str) -> PassUsage | None:
        return cast(
            PassUsage | None,
            await self._session.scalar(
                select(PassUsage).where(
                    PassUsage.actor_staff_id == staff_id, PassUsage.idempotency_key == key
                )
            ),
        )

    async def find_cancellation(self, staff_id: UUID, key: str) -> CustomerPass | None:
        return cast(
            CustomerPass | None,
            await self._session.scalar(
                select(CustomerPass).where(
                    CustomerPass.cancelled_by_staff_id == staff_id,
                    CustomerPass.cancellation_idempotency_key == key,
                )
            ),
        )

    async def get_usage(self, usage_id: UUID) -> PassUsage | None:
        return await self._session.get(PassUsage, usage_id)

    async def list_passes(self, *, user_id: UUID, active_only: bool = False) -> list[PassRecord]:
        filters = [CustomerPass.user_id == user_id]
        if active_only:
            filters.append(CustomerPass.status == PassStatus.ACTIVE)
        rows = (
            await self._session.execute(
                select(CustomerPass, func.count(PassUsage.id))
                .outerjoin(PassUsage, PassUsage.pass_id == CustomerPass.id)
                .where(*filters)
                .group_by(CustomerPass.id)
                .order_by(CustomerPass.created_at.desc())
            )
        ).all()
        return [PassRecord(row[0], int(row[1])) for row in rows]

    async def list_usages(self, pass_id: UUID) -> list[PassUsage]:
        return list(
            (
                await self._session.scalars(
                    select(PassUsage)
                    .where(PassUsage.pass_id == pass_id)
                    .order_by(PassUsage.created_at.desc())
                )
            ).all()
        )

    async def get_item(self, item_id: UUID) -> MenuItem | None:
        return await self._session.get(MenuItem, item_id)

    async def get_venue(self, venue_id: UUID) -> Venue | None:
        return await self._session.get(Venue, venue_id)

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()

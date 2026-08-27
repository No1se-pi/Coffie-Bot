"""PostgreSQL adapter for stable bulk-bonus audiences and point writes."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.cards import UserCard
from app.models.engagement import BulkBonusBatch, BulkBonusItem
from app.models.enums import CardStatus, UserStatus
from app.models.loyalty import UserLoyaltyState
from app.repositories.loyalty_v2 import PointLedgerRepository


class BulkBonusRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.point_ledger_repository = PointLedgerRepository(session)

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

    async def acquire_lock(self, staff_id: UUID, key: str) -> None:
        digest = hashlib.sha256(f"bulk-bonus:{staff_id}:{key}".encode()).digest()
        await self._session.execute(
            select(func.pg_advisory_xact_lock(int.from_bytes(digest[:8], "big", signed=True)))
        )

    async def audience(self, customer_ids: frozenset[UUID]) -> list[UUID]:
        statement = (
            select(User.id)
            .distinct()
            .join(UserCard, UserCard.user_id == User.id)
            .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
            .where(User.status == UserStatus.ACTIVE, UserCard.status == CardStatus.ACTIVE)
            .order_by(User.id)
        )
        if customer_ids:
            statement = statement.where(User.id.in_(customer_ids))
        return list((await self._session.scalars(statement)).all())

    async def lock_audience(self, user_ids: list[UUID]) -> list[tuple[User, UserLoyaltyState]]:
        rows = (
            await self._session.execute(
                select(User, UserLoyaltyState)
                .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
                .where(User.id.in_(user_ids), User.status == UserStatus.ACTIVE)
                .order_by(User.id)
                .with_for_update(of=[User, UserLoyaltyState])
            )
        ).all()
        return [(row[0], row[1]) for row in rows]

    async def find_batch(self, staff_id: UUID, key: str) -> BulkBonusBatch | None:
        return cast(
            BulkBonusBatch | None,
            await self._session.scalar(
                select(BulkBonusBatch).where(
                    BulkBonusBatch.created_by_staff_id == staff_id,
                    BulkBonusBatch.idempotency_key == key,
                )
            ),
        )

    async def list_items(self, batch_id: UUID) -> list[BulkBonusItem]:
        return list(
            (
                await self._session.scalars(
                    select(BulkBonusItem)
                    .where(BulkBonusItem.batch_id == batch_id)
                    .order_by(BulkBonusItem.user_id)
                )
            ).all()
        )

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()

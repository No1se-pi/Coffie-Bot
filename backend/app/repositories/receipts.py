"""PostgreSQL adapter for receipt creation, revisions, and risk counts."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.audit import AuditEvent
from app.models.content import Venue
from app.models.media import MediaFile
from app.models.receipts import Receipt, ReceiptRevision, ReceiptRiskFlag, ReceiptRiskSettings


class ReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        async with self._session.begin():
            yield

    async def acquire_idempotency_lock(self, staff_id: UUID, key: str) -> None:
        digest = hashlib.sha256(f"receipt:{staff_id}:{key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], "big", signed=True)
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def get_by_idempotency(self, staff_id: UUID, key: str) -> Receipt | None:
        return cast(
            Receipt | None,
            await self._session.scalar(
                select(Receipt).where(
                    Receipt.created_by_staff_id == staff_id, Receipt.idempotency_key == key
                )
            ),
        )

    async def get(self, receipt_id: UUID, *, for_update: bool = False) -> Receipt | None:
        statement = select(Receipt).where(Receipt.id == receipt_id)
        if for_update:
            statement = statement.with_for_update()
        return cast(Receipt | None, await self._session.scalar(statement))

    async def get_revision_by_key(self, key: str) -> ReceiptRevision | None:
        return cast(
            ReceiptRevision | None,
            await self._session.scalar(
                select(ReceiptRevision).where(ReceiptRevision.idempotency_key == key)
            ),
        )

    async def get_audit_by_key(self, key: str) -> AuditEvent | None:
        return cast(
            AuditEvent | None,
            await self._session.scalar(select(AuditEvent).where(AuditEvent.idempotency_key == key)),
        )

    async def list_revisions(self, receipt_id: UUID) -> list[ReceiptRevision]:
        return list(
            await self._session.scalars(
                select(ReceiptRevision)
                .where(ReceiptRevision.receipt_id == receipt_id)
                .order_by(ReceiptRevision.revision, ReceiptRevision.id)
            )
        )

    async def list_flags(self, receipt_id: UUID) -> list[ReceiptRiskFlag]:
        return list(
            await self._session.scalars(
                select(ReceiptRiskFlag)
                .where(ReceiptRiskFlag.receipt_id == receipt_id)
                .order_by(ReceiptRiskFlag.created_at, ReceiptRiskFlag.id)
            )
        )

    async def list_receipts(self, *, limit: int) -> list[Receipt]:
        return list(
            await self._session.scalars(
                select(Receipt).order_by(Receipt.created_at.desc(), Receipt.id.desc()).limit(limit)
            )
        )

    async def get_user(self, user_id: UUID) -> User | None:
        return cast(User | None, await self._session.scalar(select(User).where(User.id == user_id)))

    async def get_venue(self, venue_id: UUID) -> Venue | None:
        return cast(
            Venue | None, await self._session.scalar(select(Venue).where(Venue.id == venue_id))
        )

    async def get_media(self, media_id: UUID) -> MediaFile | None:
        return cast(
            MediaFile | None,
            await self._session.scalar(select(MediaFile).where(MediaFile.id == media_id)),
        )

    async def settings(self) -> ReceiptRiskSettings:
        value = await self._session.scalar(
            select(ReceiptRiskSettings).where(ReceiptRiskSettings.singleton_key == "default")
        )
        if value is None:
            raise RuntimeError("Receipt risk settings are missing")
        return value

    async def count_since(
        self,
        *,
        since: datetime,
        staff_id: UUID | None = None,
        user_id: UUID | None = None,
        amount_minor: int | None = None,
    ) -> int:
        statement = select(func.count()).select_from(Receipt).where(Receipt.created_at >= since)
        if staff_id is not None:
            statement = statement.where(Receipt.created_by_staff_id == staff_id)
        if user_id is not None:
            statement = statement.where(Receipt.user_id == user_id)
        if amount_minor is not None:
            statement = statement.where(Receipt.amount_minor == amount_minor)
        return int(await self._session.scalar(statement) or 0)

    async def count_number(self, receipt_number: str, *, excluding_id: UUID | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(Receipt)
            .where(func.lower(Receipt.receipt_number) == receipt_number.casefold())
        )
        if excluding_id is not None:
            statement = statement.where(Receipt.id != excluding_id)
        return int(await self._session.scalar(statement) or 0)

    async def count_staff_cancellations(self, staff_id: UUID, *, since: datetime) -> int:
        statement = (
            select(func.count())
            .select_from(Receipt)
            .where(
                Receipt.cancelled_by_staff_id == staff_id,
                Receipt.cancelled_at >= since,
            )
        )
        return int(await self._session.scalar(statement) or 0)

    def add(self, value: object) -> None:
        self._session.add(value)

    def add_all(self, values: list[object]) -> None:
        self._session.add_all(values)

    async def flush(self) -> None:
        await self._session.flush()

"""Transactional administration of durable Telegram broadcasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.audit import AuditEvent
from app.models.delivery import Broadcast, BroadcastDelivery
from app.models.enums import (
    AuditSeverity,
    BroadcastStatus,
    DeliveryStatus,
    UserStatus,
)


@dataclass(frozen=True, slots=True)
class BroadcastRecord:
    id: UUID
    title: str
    message: str
    image_media_id: UUID | None
    button_label: str | None
    button_url: str | None
    audience_filter: dict[str, Any]
    status: BroadcastStatus
    success_count: int
    failure_count: int
    skipped_count: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BroadcastPageRecord:
    items: list[BroadcastRecord]
    total: int


@dataclass(frozen=True, slots=True)
class CreateBroadcastRecord:
    broadcast: BroadcastRecord
    created: bool


@dataclass(frozen=True, slots=True)
class BroadcastTransitionRecord:
    broadcast: BroadcastRecord
    previous_status: BroadcastStatus
    recipient_count: int


class AdminBroadcastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_audience(self, audience_filter: dict[str, Any]) -> int:
        statement = select(func.count()).select_from(User).where(User.status == UserStatus.ACTIVE)
        statement = self._apply_audience_filter(statement, audience_filter)
        return int(await self._session.scalar(statement) or 0)

    async def create_draft(
        self,
        *,
        title: str,
        message: str,
        image_media_id: UUID | None,
        button_label: str | None,
        button_url: str | None,
        audience_filter: dict[str, Any],
        idempotency_key: str,
        actor_user_id: UUID,
        actor_staff_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
    ) -> CreateBroadcastRecord:
        async with self._session.begin():
            statement = (
                insert(Broadcast)
                .values(
                    title=title,
                    message=message,
                    image_media_id=image_media_id,
                    button_label=button_label,
                    button_url=button_url,
                    audience_filter=audience_filter,
                    status=BroadcastStatus.DRAFT,
                    idempotency_key=idempotency_key,
                    created_by_staff_id=actor_staff_id,
                )
                .on_conflict_do_nothing(index_elements=[Broadcast.idempotency_key])
                .returning(Broadcast)
            )
            broadcast = await self._session.scalar(statement)
            created = broadcast is not None
            if broadcast is None:
                broadcast = await self._session.scalar(
                    select(Broadcast).where(Broadcast.idempotency_key == idempotency_key)
                )
            if broadcast is None:  # Defensive: a concurrent transaction must leave a row.
                raise RuntimeError("Broadcast idempotency lookup failed")
            if created:
                self._session.add(
                    AuditEvent(
                        event_type="broadcast.created",
                        actor_user_id=actor_user_id,
                        actor_staff_id=actor_staff_id,
                        object_type="broadcast",
                        object_id=broadcast.id,
                        event_metadata={"title": title, "status": BroadcastStatus.DRAFT.value},
                        severity=AuditSeverity.INFO,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                )
                await self._session.flush()
            return CreateBroadcastRecord(
                broadcast=self._record(broadcast),
                created=created,
            )

    async def list_broadcasts(
        self,
        *,
        broadcast_status: BroadcastStatus | None,
        page: int,
        page_size: int,
    ) -> BroadcastPageRecord:
        filters = []
        if broadcast_status is not None:
            filters.append(Broadcast.status == broadcast_status)
        total = int(
            await self._session.scalar(select(func.count()).select_from(Broadcast).where(*filters))
            or 0
        )
        rows = (
            await self._session.scalars(
                select(Broadcast)
                .where(*filters)
                .order_by(Broadcast.created_at.desc(), Broadcast.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return BroadcastPageRecord(
            items=[self._record(item) for item in rows],
            total=total,
        )

    async def get_broadcast(self, broadcast_id: UUID) -> BroadcastRecord | None:
        broadcast = await self._session.get(Broadcast, broadcast_id)
        return self._record(broadcast) if broadcast is not None else None

    async def confirm_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor_user_id: UUID,
        actor_staff_id: UUID,
        now: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> BroadcastTransitionRecord | None:
        async with self._session.begin():
            broadcast = await self._session.scalar(
                select(Broadcast).where(Broadcast.id == broadcast_id).with_for_update()
            )
            if broadcast is None:
                return None
            previous_status = broadcast.status
            if previous_status == BroadcastStatus.DRAFT:
                recipient_ids = list(
                    (
                        await self._session.scalars(
                            self._audience_statement(broadcast.audience_filter)
                        )
                    ).all()
                )
                if recipient_ids:
                    await self._session.execute(
                        insert(BroadcastDelivery)
                        .values(
                            [
                                {
                                    "broadcast_id": broadcast.id,
                                    "user_id": user_id,
                                    "status": DeliveryStatus.PENDING,
                                    "attempts": 0,
                                }
                                for user_id in recipient_ids
                            ]
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                BroadcastDelivery.broadcast_id,
                                BroadcastDelivery.user_id,
                            ]
                        )
                    )
                broadcast.status = (
                    BroadcastStatus.CONFIRMED if recipient_ids else BroadcastStatus.COMPLETED
                )
                broadcast.confirmed_by_staff_id = actor_staff_id
                broadcast.confirmed_at = now
                if not recipient_ids:
                    broadcast.completed_at = now
                self._session.add(
                    AuditEvent(
                        event_type="broadcast.confirmed",
                        actor_user_id=actor_user_id,
                        actor_staff_id=actor_staff_id,
                        object_type="broadcast",
                        object_id=broadcast.id,
                        event_metadata={"recipient_count": len(recipient_ids)},
                        severity=AuditSeverity.INFO,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                )
                await self._session.flush()
                recipient_count = len(recipient_ids)
            else:
                recipient_count = int(
                    await self._session.scalar(
                        select(func.count())
                        .select_from(BroadcastDelivery)
                        .where(BroadcastDelivery.broadcast_id == broadcast.id)
                    )
                    or 0
                )
            return BroadcastTransitionRecord(
                broadcast=self._record(broadcast),
                previous_status=previous_status,
                recipient_count=recipient_count,
            )

    async def cancel_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor_user_id: UUID,
        actor_staff_id: UUID,
        reason: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> BroadcastTransitionRecord | None:
        async with self._session.begin():
            broadcast = await self._session.scalar(
                select(Broadcast).where(Broadcast.id == broadcast_id).with_for_update()
            )
            if broadcast is None:
                return None
            previous_status = broadcast.status
            recipient_count = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(BroadcastDelivery)
                    .where(BroadcastDelivery.broadcast_id == broadcast.id)
                )
                or 0
            )
            if previous_status in {BroadcastStatus.DRAFT, BroadcastStatus.CONFIRMED}:
                result = await self._session.execute(
                    update(BroadcastDelivery)
                    .where(
                        BroadcastDelivery.broadcast_id == broadcast.id,
                        BroadcastDelivery.status == DeliveryStatus.PENDING,
                    )
                    .values(
                        status=DeliveryStatus.SKIPPED,
                        error_code="broadcast_cancelled",
                    )
                )
                skipped = int(cast(CursorResult[Any], result).rowcount or 0)
                broadcast.skipped_count += skipped
                broadcast.status = BroadcastStatus.CANCELLED
                self._session.add(
                    AuditEvent(
                        event_type="broadcast.cancelled",
                        actor_user_id=actor_user_id,
                        actor_staff_id=actor_staff_id,
                        object_type="broadcast",
                        object_id=broadcast.id,
                        event_metadata={"reason": reason, "skipped_count": skipped},
                        severity=AuditSeverity.WARNING,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                )
                await self._session.flush()
            return BroadcastTransitionRecord(
                broadcast=self._record(broadcast),
                previous_status=previous_status,
                recipient_count=recipient_count,
            )

    def _audience_statement(self, audience_filter: dict[str, Any]) -> Any:
        statement = select(User.id).where(User.status == UserStatus.ACTIVE)
        return self._apply_audience_filter(statement, audience_filter).order_by(User.id)

    @staticmethod
    def _apply_audience_filter(statement: Any, audience_filter: dict[str, Any]) -> Any:
        if audience_filter.get("mode") == "selected":
            raw_ids = audience_filter.get("user_ids", [])
            selected_ids = [UUID(value) for value in raw_ids if isinstance(value, str)]
            statement = statement.where(User.id.in_(selected_ids))
        return statement

    @staticmethod
    def _record(broadcast: Broadcast) -> BroadcastRecord:
        return BroadcastRecord(
            id=broadcast.id,
            title=broadcast.title,
            message=broadcast.message,
            image_media_id=broadcast.image_media_id,
            button_label=broadcast.button_label,
            button_url=broadcast.button_url,
            audience_filter=dict(broadcast.audience_filter),
            status=broadcast.status,
            success_count=broadcast.success_count,
            failure_count=broadcast.failure_count,
            skipped_count=broadcast.skipped_count,
            created_at=broadcast.created_at,
            updated_at=broadcast.updated_at,
            confirmed_at=broadcast.confirmed_at,
            started_at=broadcast.started_at,
            completed_at=broadcast.completed_at,
        )

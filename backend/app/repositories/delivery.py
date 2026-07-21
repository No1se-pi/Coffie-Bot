"""PostgreSQL queues for notifications and broadcast recipients."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypeGuard, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.access import User
from app.models.delivery import Broadcast, BroadcastDelivery, NotificationOutbox
from app.models.enums import (
    BroadcastStatus,
    DeliveryStatus,
    OutboxStatus,
    UserStatus,
)
from app.models.media import MediaFile


@dataclass(frozen=True, slots=True)
class NotificationJob:
    id: UUID
    telegram_id: int
    event_type: str
    payload: dict[str, Any]
    attempts: int
    lease_until: datetime


@dataclass(frozen=True, slots=True)
class BroadcastJob:
    id: UUID
    broadcast_id: UUID
    telegram_id: int
    user_status: UserStatus
    message: str
    button_label: str | None
    button_url: str | None
    image_storage_key: str | None
    attempts: int
    lease_until: datetime


class DeliveryRepository:
    """Claim and settle durable jobs without holding a lock during I/O."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim_notifications(
        self,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[NotificationJob]:
        lease_until = now + lease_for
        eligible = or_(
            and_(
                NotificationOutbox.status == OutboxStatus.PENDING,
                or_(
                    NotificationOutbox.next_attempt_at.is_(None),
                    NotificationOutbox.next_attempt_at <= now,
                ),
            ),
            and_(
                NotificationOutbox.status == OutboxStatus.PROCESSING,
                NotificationOutbox.lease_until < now,
            ),
        )
        async with self._session.begin():
            rows = (
                await self._session.execute(
                    select(NotificationOutbox, User.telegram_id)
                    .join(User, User.id == NotificationOutbox.user_id)
                    .where(eligible)
                    .order_by(NotificationOutbox.created_at, NotificationOutbox.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True, of=NotificationOutbox)
                )
            ).all()
            jobs: list[NotificationJob] = []
            for outbox, telegram_id in rows:
                outbox.status = OutboxStatus.PROCESSING
                outbox.attempts += 1
                outbox.lease_until = lease_until
                outbox.next_attempt_at = None
                jobs.append(
                    NotificationJob(
                        id=outbox.id,
                        telegram_id=telegram_id,
                        event_type=outbox.event_type,
                        payload=dict(outbox.payload),
                        attempts=outbox.attempts,
                        lease_until=lease_until,
                    )
                )
        return jobs

    async def mark_notification_sent(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        sent_at: datetime,
    ) -> bool:
        async with self._session.begin():
            job = await self._locked_notification(job_id)
            if not _owns_notification(job, lease_until):
                return False
            job.status = OutboxStatus.SENT
            job.sent_at = sent_at
            job.lease_until = None
            job.next_attempt_at = None
            job.last_error_code = None
        return True

    async def mark_notification_failed(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> bool:
        async with self._session.begin():
            job = await self._locked_notification(job_id)
            if not _owns_notification(job, lease_until):
                return False
            job.status = OutboxStatus.PENDING if retry_at is not None else OutboxStatus.FAILED
            job.next_attempt_at = retry_at
            job.lease_until = None
            job.last_error_code = error_code[:128]
        return True

    async def claim_broadcasts(
        self,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[BroadcastJob]:
        lease_until = now + lease_for
        eligible_delivery = or_(
            and_(
                BroadcastDelivery.status == DeliveryStatus.PENDING,
                or_(
                    BroadcastDelivery.next_attempt_at.is_(None),
                    BroadcastDelivery.next_attempt_at <= now,
                ),
            ),
            and_(
                BroadcastDelivery.status == DeliveryStatus.PROCESSING,
                BroadcastDelivery.lease_until < now,
            ),
        )
        async with self._session.begin():
            rows = (
                await self._session.execute(
                    select(
                        BroadcastDelivery,
                        Broadcast,
                        User.telegram_id,
                        User.status,
                        MediaFile.storage_key,
                    )
                    .join(Broadcast, Broadcast.id == BroadcastDelivery.broadcast_id)
                    .join(User, User.id == BroadcastDelivery.user_id)
                    .outerjoin(MediaFile, MediaFile.id == Broadcast.image_media_id)
                    .where(
                        eligible_delivery,
                        Broadcast.status.in_((BroadcastStatus.CONFIRMED, BroadcastStatus.RUNNING)),
                    )
                    .order_by(BroadcastDelivery.created_at, BroadcastDelivery.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True, of=BroadcastDelivery)
                )
            ).all()
            jobs: list[BroadcastJob] = []
            for delivery, broadcast, telegram_id, user_status, storage_key in rows:
                delivery.status = DeliveryStatus.PROCESSING
                delivery.attempts += 1
                delivery.lease_until = lease_until
                delivery.next_attempt_at = None
                if broadcast.status == BroadcastStatus.CONFIRMED:
                    broadcast.status = BroadcastStatus.RUNNING
                    broadcast.started_at = now
                jobs.append(
                    BroadcastJob(
                        id=delivery.id,
                        broadcast_id=broadcast.id,
                        telegram_id=telegram_id,
                        user_status=user_status,
                        message=broadcast.message,
                        button_label=broadcast.button_label,
                        button_url=broadcast.button_url,
                        image_storage_key=storage_key,
                        attempts=delivery.attempts,
                        lease_until=lease_until,
                    )
                )
        return jobs

    async def mark_broadcast_sent(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        telegram_message_id: int,
        sent_at: datetime,
    ) -> bool:
        async with self._session.begin():
            delivery = await self._locked_broadcast_delivery(job_id)
            if not _owns_broadcast(delivery, lease_until):
                return False
            delivery.status = DeliveryStatus.SENT
            delivery.telegram_message_id = telegram_message_id
            delivery.delivered_at = sent_at
            delivery.error_code = None
            delivery.next_attempt_at = None
            delivery.lease_until = None
            await self._increment_broadcast(delivery.broadcast_id, "success_count")
        return True

    async def mark_broadcast_failed(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> bool:
        async with self._session.begin():
            delivery = await self._locked_broadcast_delivery(job_id)
            if not _owns_broadcast(delivery, lease_until):
                return False
            delivery.status = (
                DeliveryStatus.PENDING if retry_at is not None else DeliveryStatus.FAILED
            )
            delivery.next_attempt_at = retry_at
            delivery.lease_until = None
            delivery.error_code = error_code[:128]
            if retry_at is None:
                await self._increment_broadcast(delivery.broadcast_id, "failure_count")
        return True

    async def mark_broadcast_skipped(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        reason: str,
    ) -> bool:
        async with self._session.begin():
            delivery = await self._locked_broadcast_delivery(job_id)
            if not _owns_broadcast(delivery, lease_until):
                return False
            delivery.status = DeliveryStatus.SKIPPED
            delivery.error_code = reason[:128]
            delivery.next_attempt_at = None
            delivery.lease_until = None
            await self._increment_broadcast(delivery.broadcast_id, "skipped_count")
        return True

    async def finalize_broadcasts(
        self,
        broadcast_ids: set[UUID],
        *,
        now: datetime,
    ) -> None:
        for broadcast_id in broadcast_ids:
            async with self._session.begin():
                broadcast = await self._session.scalar(
                    select(Broadcast).where(Broadcast.id == broadcast_id).with_for_update()
                )
                if broadcast is None or broadcast.status != BroadcastStatus.RUNNING:
                    continue
                unfinished = await self._session.scalar(
                    select(func.count())
                    .select_from(BroadcastDelivery)
                    .where(
                        BroadcastDelivery.broadcast_id == broadcast_id,
                        BroadcastDelivery.status.in_(
                            (DeliveryStatus.PENDING, DeliveryStatus.PROCESSING)
                        ),
                    )
                )
                if unfinished:
                    continue
                if broadcast.failure_count > 0 and broadcast.success_count == 0:
                    broadcast.status = BroadcastStatus.FAILED
                else:
                    broadcast.status = BroadcastStatus.COMPLETED
                broadcast.completed_at = now

    async def _locked_notification(self, job_id: UUID) -> NotificationOutbox | None:
        return cast(
            NotificationOutbox | None,
            await self._session.scalar(
                select(NotificationOutbox).where(NotificationOutbox.id == job_id).with_for_update()
            ),
        )

    async def _locked_broadcast_delivery(
        self,
        job_id: UUID,
    ) -> BroadcastDelivery | None:
        return cast(
            BroadcastDelivery | None,
            await self._session.scalar(
                select(BroadcastDelivery).where(BroadcastDelivery.id == job_id).with_for_update()
            ),
        )

    async def _increment_broadcast(self, broadcast_id: UUID, field: str) -> None:
        column = getattr(Broadcast, field)
        await self._session.execute(
            update(Broadcast).where(Broadcast.id == broadcast_id).values({field: column + 1})
        )


def _owns_notification(
    job: NotificationOutbox | None,
    lease_until: datetime,
) -> TypeGuard[NotificationOutbox]:
    return bool(
        job is not None and job.status == OutboxStatus.PROCESSING and job.lease_until == lease_until
    )


def _owns_broadcast(
    delivery: BroadcastDelivery | None,
    lease_until: datetime,
) -> TypeGuard[BroadcastDelivery]:
    return bool(
        delivery is not None
        and delivery.status == DeliveryStatus.PROCESSING
        and delivery.lease_until == lease_until
    )

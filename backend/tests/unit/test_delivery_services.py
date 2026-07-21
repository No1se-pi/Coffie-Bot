from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.models.enums import UserStatus
from app.repositories.delivery import BroadcastJob, NotificationJob
from app.services.broadcasts import BroadcastService
from app.services.notifications import (
    DeliveryError,
    NotificationService,
    OutboundMessage,
    RetryPolicy,
)

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
LEASE = NOW + timedelta(minutes=1)


class FakeSender:
    def __init__(self, failures: dict[int, DeliveryError] | None = None) -> None:
        self.failures = failures or {}
        self.calls: list[tuple[int, OutboundMessage]] = []

    async def send(self, telegram_id: int, message: OutboundMessage) -> int:
        self.calls.append((telegram_id, message))
        failure = self.failures.get(telegram_id)
        if failure is not None:
            raise failure
        return telegram_id + 1000


class FakeNotificationRepository:
    def __init__(self, jobs: list[NotificationJob]) -> None:
        self.jobs = jobs
        self.sent: list[UUID] = []
        self.failed: list[tuple[UUID, str, datetime | None]] = []

    async def claim_notifications(
        self,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[NotificationJob]:
        assert now == NOW
        assert lease_for == timedelta(minutes=1)
        return self.jobs[:limit]

    async def mark_notification_sent(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        sent_at: datetime,
    ) -> bool:
        assert lease_until == LEASE
        assert sent_at == NOW
        self.sent.append(job_id)
        return True

    async def mark_notification_failed(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> bool:
        assert lease_until == LEASE
        self.failed.append((job_id, error_code, retry_at))
        return True


class FakeBroadcastRepository:
    def __init__(self, jobs: list[BroadcastJob]) -> None:
        self.jobs = jobs
        self.sent: list[tuple[UUID, int]] = []
        self.failed: list[tuple[UUID, str, datetime | None]] = []
        self.skipped: list[tuple[UUID, str]] = []
        self.finalized: list[set[UUID]] = []

    async def claim_broadcasts(
        self,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[BroadcastJob]:
        assert now == NOW
        assert lease_for == timedelta(minutes=1)
        return self.jobs[:limit]

    async def mark_broadcast_sent(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        telegram_message_id: int,
        sent_at: datetime,
    ) -> bool:
        assert lease_until == LEASE
        assert sent_at == NOW
        self.sent.append((job_id, telegram_message_id))
        return True

    async def mark_broadcast_failed(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> bool:
        assert lease_until == LEASE
        self.failed.append((job_id, error_code, retry_at))
        return True

    async def mark_broadcast_skipped(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        reason: str,
    ) -> bool:
        assert lease_until == LEASE
        self.skipped.append((job_id, reason))
        return True

    async def finalize_broadcasts(
        self,
        broadcast_ids: set[UUID],
        *,
        now: datetime,
    ) -> None:
        assert now == NOW
        self.finalized.append(broadcast_ids)


async def test_notification_failure_does_not_stop_the_batch() -> None:
    first = _notification_job(telegram_id=101)
    second = _notification_job(telegram_id=202)
    repository = FakeNotificationRepository([first, second])
    sender = FakeSender({101: DeliveryError("telegram_forbidden", permanent=True)})
    service = NotificationService(
        repository=repository,
        sender=sender,
        retry_policy=RetryPolicy(max_attempts=3),
        webapp_url="https://example.test/app",
    )

    result = await service.process_batch(
        limit=10,
        lease_for=timedelta(minutes=1),
        now=NOW,
    )

    assert [telegram_id for telegram_id, _ in sender.calls] == [101, 202]
    assert result.claimed == 2
    assert result.sent == 1
    assert result.failed == 1
    assert repository.sent == [second.id]
    assert repository.failed == [(first.id, "telegram_forbidden", None)]


async def test_notification_retry_uses_exponential_backoff() -> None:
    job = _notification_job(telegram_id=101, attempts=3)
    repository = FakeNotificationRepository([job])
    sender = FakeSender({101: DeliveryError("telegram_network_error")})
    service = NotificationService(
        repository=repository,
        sender=sender,
        retry_policy=RetryPolicy(
            max_attempts=5,
            base_delay=timedelta(seconds=10),
            max_delay=timedelta(minutes=5),
        ),
    )

    result = await service.process_batch(
        limit=1,
        lease_for=timedelta(minutes=1),
        now=NOW,
    )

    assert result.retried == 1
    assert repository.failed == [
        (job.id, "telegram_network_error", NOW + timedelta(seconds=40))
    ]


async def test_broadcast_isolates_failures_and_skips_inactive_users(tmp_path: Path) -> None:
    broadcast_id = uuid4()
    failed = _broadcast_job(broadcast_id, telegram_id=101)
    sent = _broadcast_job(broadcast_id, telegram_id=202)
    inactive = _broadcast_job(
        broadcast_id,
        telegram_id=303,
        user_status=UserStatus.INACTIVE,
    )
    repository = FakeBroadcastRepository([failed, sent, inactive])
    sender = FakeSender({101: DeliveryError("telegram_forbidden", permanent=True)})
    service = BroadcastService(
        repository=repository,
        sender=sender,
        retry_policy=RetryPolicy(max_attempts=3),
        media_root=tmp_path,
    )

    result = await service.process_batch(
        limit=10,
        lease_for=timedelta(minutes=1),
        now=NOW,
    )

    assert [telegram_id for telegram_id, _ in sender.calls] == [101, 202]
    assert result.failed == 1
    assert result.sent == 1
    assert result.skipped == 1
    assert repository.sent == [(sent.id, 1202)]
    assert repository.failed == [(failed.id, "telegram_forbidden", None)]
    assert repository.skipped == [(inactive.id, "user_inactive")]
    assert repository.finalized == [{broadcast_id}]


def _notification_job(*, telegram_id: int, attempts: int = 1) -> NotificationJob:
    return NotificationJob(
        id=uuid4(),
        telegram_id=telegram_id,
        event_type="user.registered",
        payload={"welcome_bonus_points": 10},
        attempts=attempts,
        lease_until=LEASE,
    )


def _broadcast_job(
    broadcast_id: UUID,
    *,
    telegram_id: int,
    user_status: UserStatus = UserStatus.ACTIVE,
) -> BroadcastJob:
    return BroadcastJob(
        id=uuid4(),
        broadcast_id=broadcast_id,
        telegram_id=telegram_id,
        user_status=user_status,
        message="Нейтральное сообщение",
        button_label=None,
        button_url=None,
        image_storage_key=None,
        attempts=1,
        lease_until=LEASE,
    )

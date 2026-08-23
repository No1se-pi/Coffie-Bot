"""Application service for reliable Telegram notification delivery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.repositories.delivery import NotificationJob


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    text: str
    button_label: str | None = None
    button_url: str | None = None
    image_path: Path | None = None
    open_as_web_app: bool = False


class MessageSender(Protocol):
    async def send(self, telegram_id: int, message: OutboundMessage) -> int: ...


class DeliveryError(Exception):
    """Normalized transport failure safe to persist and use for retry decisions."""

    def __init__(
        self,
        code: str,
        *,
        permanent: bool = False,
        retry_after: timedelta | None = None,
    ) -> None:
        super().__init__(code)
        self.code = _safe_error_code(code)
        self.permanent = permanent
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 7
    base_delay: timedelta = timedelta(seconds=10)
    max_delay: timedelta = timedelta(hours=1)

    def delay(self, attempt: int, *, retry_after: timedelta | None = None) -> timedelta:
        exponent = max(attempt - 1, 0)
        seconds = min(
            self.base_delay.total_seconds() * (2**exponent),
            self.max_delay.total_seconds(),
        )
        calculated = timedelta(seconds=seconds)
        if retry_after is None:
            return calculated
        return min(max(calculated, retry_after), self.max_delay)


@dataclass(slots=True)
class DeliveryBatchResult:
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0
    stale: int = 0


class NotificationRepositoryPort(Protocol):
    async def claim_notifications(
        self,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[NotificationJob]: ...

    async def mark_notification_sent(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        sent_at: datetime,
    ) -> bool: ...

    async def mark_notification_failed(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> bool: ...


class NotificationService:
    def __init__(
        self,
        *,
        repository: NotificationRepositoryPort,
        sender: MessageSender,
        retry_policy: RetryPolicy,
        webapp_url: str | None = None,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._retry_policy = retry_policy
        self._webapp_url = webapp_url

    async def process_batch(
        self,
        *,
        limit: int,
        lease_for: timedelta,
        now: datetime | None = None,
    ) -> DeliveryBatchResult:
        current_time = _aware_now(now)
        jobs = await self._repository.claim_notifications(
            now=current_time,
            lease_for=lease_for,
            limit=limit,
        )
        result = DeliveryBatchResult(claimed=len(jobs))
        for job in jobs:
            if job.telegram_id is None:
                # Phone-only customers are valid loyalty participants but have no
                # Telegram delivery channel until they explicitly link an identity.
                settled = await self._repository.mark_notification_failed(
                    job.id,
                    lease_until=job.lease_until,
                    error_code="telegram_identity_missing",
                    retry_at=None,
                )
                if settled:
                    result.failed += 1
                else:
                    result.stale += 1
                continue
            try:
                message = render_notification(job, webapp_url=self._webapp_url)
                await self._sender.send(job.telegram_id, message)
            except DeliveryError as exc:
                await self._settle_failure(job, exc, current_time, result)
            except Exception as exc:  # A single malformed job must not stop the queue.
                error = DeliveryError(f"unexpected_{type(exc).__name__}")
                await self._settle_failure(job, error, current_time, result)
            else:
                settled = await self._repository.mark_notification_sent(
                    job.id,
                    lease_until=job.lease_until,
                    sent_at=current_time,
                )
                if settled:
                    result.sent += 1
                else:
                    result.stale += 1
        return result

    async def _settle_failure(
        self,
        job: NotificationJob,
        error: DeliveryError,
        now: datetime,
        result: DeliveryBatchResult,
    ) -> None:
        terminal = error.permanent or job.attempts >= self._retry_policy.max_attempts
        retry_at = None
        if not terminal:
            retry_at = now + self._retry_policy.delay(
                job.attempts,
                retry_after=error.retry_after,
            )
        settled = await self._repository.mark_notification_failed(
            job.id,
            lease_until=job.lease_until,
            error_code=error.code,
            retry_at=retry_at,
        )
        if not settled:
            result.stale += 1
        elif terminal:
            result.failed += 1
        else:
            result.retried += 1


def render_notification(
    job: NotificationJob,
    *,
    webapp_url: str | None,
) -> OutboundMessage:
    payload = job.payload
    event_type = job.event_type
    if event_type == "user.registered":
        bonus = _integer(payload.get("welcome_bonus_points"))
        text = "Регистрация завершена. Ваша карта лояльности готова."
        if bonus > 0:
            text += f" Начислено приветственных баллов: {bonus}."
    elif event_type in {"points.accrued", "loyalty.points_accrued"}:
        amount = _integer(payload.get("points", payload.get("points_delta")))
        text = f"Начислено баллов: {amount}." if amount else "Баллы начислены."
    elif event_type in {"points.redeemed", "loyalty.points_redeemed"}:
        amount = abs(_integer(payload.get("points", payload.get("points_delta"))))
        text = f"Списано баллов: {amount}." if amount else "Баллы списаны."
    elif event_type in {"reward.issued", "loyalty.reward_created"}:
        name = _short_text(payload.get("name"))
        text = f"Вам доступна награда: {name}." if name else "Вам доступна новая награда."
    elif event_type == "feedback.created":
        text = "Спасибо. Ваше обращение принято."
    else:
        text = "В программе лояльности появилось обновление."

    operation_id = _short_text(payload.get("operation_id"))
    post_purchase_event = event_type in {
        "points.accrued",
        "loyalty.points_accrued",
        "points.redeemed",
        "loyalty.points_redeemed",
        "reward.redeemed",
    }
    post_purchase_url = (
        f"{webapp_url.rstrip('/')}/after-purchase/{operation_id}"
        if webapp_url and operation_id and post_purchase_event
        else None
    )
    return OutboundMessage(
        text=text,
        button_label=("Оценить бариста" if post_purchase_url else "Открыть приложение")
        if webapp_url
        else None,
        button_url=post_purchase_url or webapp_url,
        open_as_web_app=bool(webapp_url),
    )


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _short_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    return normalized[:120] or None


def _safe_error_code(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in {"_", "-", "."} else "_"
        for character in value.casefold()
    )
    return normalized[:128] or "delivery_error"


def _aware_now(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value

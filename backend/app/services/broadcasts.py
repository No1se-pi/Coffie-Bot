"""Application service for isolated per-recipient broadcast delivery."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from app.models.enums import UserStatus
from app.repositories.delivery import BroadcastJob
from app.services.notifications import (
    DeliveryBatchResult,
    DeliveryError,
    MessageSender,
    OutboundMessage,
    RetryPolicy,
    _aware_now,
)


class BroadcastRepositoryPort(Protocol):
    async def claim_broadcasts(
        self,
        *,
        now: datetime,
        lease_for: timedelta,
        limit: int,
    ) -> list[BroadcastJob]: ...

    async def mark_broadcast_sent(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        telegram_message_id: int,
        sent_at: datetime,
    ) -> bool: ...

    async def mark_broadcast_failed(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        error_code: str,
        retry_at: datetime | None,
    ) -> bool: ...

    async def mark_broadcast_skipped(
        self,
        job_id: UUID,
        *,
        lease_until: datetime,
        reason: str,
    ) -> bool: ...

    async def finalize_broadcasts(
        self,
        broadcast_ids: set[UUID],
        *,
        now: datetime,
    ) -> None: ...


class BroadcastService:
    def __init__(
        self,
        *,
        repository: BroadcastRepositoryPort,
        sender: MessageSender,
        retry_policy: RetryPolicy,
        media_root: Path,
        webapp_url: str | None = None,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._retry_policy = retry_policy
        self._media_root = media_root
        self._webapp_url = webapp_url

    async def process_batch(
        self,
        *,
        limit: int,
        lease_for: timedelta,
        now: datetime | None = None,
    ) -> DeliveryBatchResult:
        current_time = _aware_now(now)
        jobs = await self._repository.claim_broadcasts(
            now=current_time,
            lease_for=lease_for,
            limit=limit,
        )
        result = DeliveryBatchResult(claimed=len(jobs))
        touched = {job.broadcast_id for job in jobs}
        for job in jobs:
            telegram_id = job.telegram_id
            if telegram_id is None:
                reason = "telegram_identity_missing"
            elif job.user_status != UserStatus.ACTIVE:
                reason = f"user_{job.user_status.value}"
            else:
                reason = None
            if reason is not None:
                # Broadcast audience can include phone-only profiles. Mark those
                # rows as skipped instead of retrying an impossible Telegram send.
                settled = await self._repository.mark_broadcast_skipped(
                    job.id,
                    lease_until=job.lease_until,
                    reason=reason,
                )
                if settled:
                    result.skipped += 1
                else:
                    result.stale += 1
                continue
            assert telegram_id is not None  # Narrowed by the channel check above.
            try:
                message_id = await self._sender.send(
                    telegram_id,
                    OutboundMessage(
                        text=job.message,
                        button_label=job.button_label,
                        button_url=job.button_url,
                        image_path=self._safe_media_path(job.image_storage_key),
                        open_as_web_app=_belongs_to_web_app(
                            job.button_url,
                            self._webapp_url,
                        ),
                    ),
                )
            except DeliveryError as exc:
                await self._settle_failure(job, exc, current_time, result)
            except Exception as exc:  # Continue delivering to the remaining recipients.
                error = DeliveryError(f"unexpected_{type(exc).__name__}")
                await self._settle_failure(job, error, current_time, result)
            else:
                settled = await self._repository.mark_broadcast_sent(
                    job.id,
                    lease_until=job.lease_until,
                    telegram_message_id=message_id,
                    sent_at=current_time,
                )
                if settled:
                    result.sent += 1
                else:
                    result.stale += 1
        if touched:
            await self._repository.finalize_broadcasts(touched, now=current_time)
        return result

    async def _settle_failure(
        self,
        job: BroadcastJob,
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
        settled = await self._repository.mark_broadcast_failed(
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

    def _safe_media_path(self, storage_key: str | None) -> Path | None:
        if not storage_key:
            return None
        root = self._media_root.resolve()
        candidate = (root / storage_key).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        return candidate


def _belongs_to_web_app(button_url: str | None, webapp_url: str | None) -> bool:
    if not button_url or not webapp_url:
        return False
    button = urlsplit(button_url)
    base = urlsplit(webapp_url)
    if (button.scheme, button.netloc) != (base.scheme, base.netloc):
        return False
    base_path = base.path.rstrip("/")
    return not base_path or button.path == base_path or button.path.startswith(f"{base_path}/")

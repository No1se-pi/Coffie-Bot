"""Business rules for previewing and safely starting broadcasts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.enums import BroadcastStatus
from app.repositories.admin_broadcasts import (
    BroadcastPageRecord,
    BroadcastRecord,
    BroadcastTransitionRecord,
    CreateBroadcastRecord,
)
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class BroadcastDraft:
    title: str
    message: str
    image_media_id: UUID | None
    button_label: str | None
    button_url: str | None
    audience_filter: dict[str, Any]


@dataclass(frozen=True, slots=True)
class BroadcastRequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


class AdminBroadcastRepositoryPort(Protocol):
    async def count_audience(self, audience_filter: dict[str, Any]) -> int: ...

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
    ) -> CreateBroadcastRecord: ...

    async def list_broadcasts(
        self,
        *,
        broadcast_status: BroadcastStatus | None,
        page: int,
        page_size: int,
    ) -> BroadcastPageRecord: ...

    async def get_broadcast(self, broadcast_id: UUID) -> BroadcastRecord | None: ...

    async def confirm_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor_user_id: UUID,
        actor_staff_id: UUID,
        now: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> BroadcastTransitionRecord | None: ...

    async def cancel_broadcast(
        self,
        *,
        broadcast_id: UUID,
        actor_user_id: UUID,
        actor_staff_id: UUID,
        reason: str,
        ip_address: str | None,
        user_agent: str | None,
    ) -> BroadcastTransitionRecord | None: ...


class AdminBroadcastService:
    def __init__(self, repository: AdminBroadcastRepositoryPort) -> None:
        self._repository = repository

    async def preview(self, draft: BroadcastDraft) -> int:
        return await self._repository.count_audience(draft.audience_filter)

    async def create(
        self,
        actor: Actor,
        *,
        draft: BroadcastDraft,
        idempotency_key: str,
        metadata: BroadcastRequestMetadata,
    ) -> BroadcastRecord:
        staff_id = self._staff_id(actor)
        result = await self._repository.create_draft(
            title=draft.title,
            message=draft.message,
            image_media_id=draft.image_media_id,
            button_label=draft.button_label,
            button_url=draft.button_url,
            audience_filter=draft.audience_filter,
            idempotency_key=idempotency_key,
            actor_user_id=actor.user_id,
            actor_staff_id=staff_id,
            ip_address=metadata.ip_address,
            user_agent=metadata.user_agent,
        )
        if not result.created and not self._same_payload(result.broadcast, draft):
            raise AppError(
                code="idempotency_conflict",
                message="Idempotency key was already used for another broadcast",
                status_code=status.HTTP_409_CONFLICT,
            )
        return result.broadcast

    async def list(
        self,
        *,
        broadcast_status: BroadcastStatus | None,
        page: int,
        page_size: int,
    ) -> BroadcastPageRecord:
        return await self._repository.list_broadcasts(
            broadcast_status=broadcast_status,
            page=page,
            page_size=page_size,
        )

    async def get(self, broadcast_id: UUID) -> BroadcastRecord:
        broadcast = await self._repository.get_broadcast(broadcast_id)
        if broadcast is None:
            raise self._not_found()
        return broadcast

    async def confirm(
        self,
        actor: Actor,
        *,
        broadcast_id: UUID,
        metadata: BroadcastRequestMetadata,
        now: datetime | None = None,
    ) -> BroadcastTransitionRecord:
        result = await self._repository.confirm_broadcast(
            broadcast_id=broadcast_id,
            actor_user_id=actor.user_id,
            actor_staff_id=self._staff_id(actor),
            now=now or datetime.now(UTC),
            ip_address=metadata.ip_address,
            user_agent=metadata.user_agent,
        )
        if result is None:
            raise self._not_found()
        if result.previous_status in {BroadcastStatus.CANCELLED, BroadcastStatus.FAILED}:
            raise self._state_conflict(result.previous_status)
        return result

    async def cancel(
        self,
        actor: Actor,
        *,
        broadcast_id: UUID,
        reason: str,
        metadata: BroadcastRequestMetadata,
    ) -> BroadcastTransitionRecord:
        result = await self._repository.cancel_broadcast(
            broadcast_id=broadcast_id,
            actor_user_id=actor.user_id,
            actor_staff_id=self._staff_id(actor),
            reason=reason,
            ip_address=metadata.ip_address,
            user_agent=metadata.user_agent,
        )
        if result is None:
            raise self._not_found()
        if result.previous_status not in {
            BroadcastStatus.DRAFT,
            BroadcastStatus.CONFIRMED,
            BroadcastStatus.CANCELLED,
        }:
            raise self._state_conflict(result.previous_status)
        return result

    @staticmethod
    def _staff_id(actor: Actor) -> UUID:
        if actor.staff_member_id is None:
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="Staff identity is required",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return actor.staff_member_id

    @staticmethod
    def _same_payload(record: BroadcastRecord, draft: BroadcastDraft) -> bool:
        return (
            record.title == draft.title
            and record.message == draft.message
            and record.image_media_id == draft.image_media_id
            and record.button_label == draft.button_label
            and record.button_url == draft.button_url
            and record.audience_filter == draft.audience_filter
        )

    @staticmethod
    def _not_found() -> AppError:
        return AppError(
            code=ErrorCode.NOT_FOUND,
            message="Broadcast was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    @staticmethod
    def _state_conflict(current_status: BroadcastStatus) -> AppError:
        return AppError(
            code="broadcast_state_conflict",
            message="Broadcast cannot be changed in its current state",
            status_code=status.HTTP_409_CONFLICT,
            details={"status": current_status.value},
        )

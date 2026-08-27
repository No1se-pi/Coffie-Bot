"""Business rules for customer reviews and auditable moderation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.engagement import PublicReview
from app.models.enums import AuditSeverity, PermissionCode, ReviewStatus
from app.repositories.reviews import ReviewRecord, ReviewRepository, review_record
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class ReviewCreateCommand:
    venue_id: UUID
    rating: int
    text: str
    order_id: UUID | None = None
    employee_staff_id: UUID | None = None
    author_display_name: str | None = None


class ReviewService:
    def __init__(self, repository: ReviewRepository) -> None:
        self._repository = repository

    async def create(self, actor: Actor, command: ReviewCreateCommand) -> ReviewRecord:
        text = " ".join(command.text.split())
        if len(text) < 3:
            _validation("review_text_too_short", "Текст отзыва слишком короткий")
        async with self._repository.transaction():
            user = await self._repository.active_customer(actor.user_id)
            venue = await self._repository.get_venue(command.venue_id)
            if user is None or venue is None or venue.archived_at is not None:
                _not_found("Заведение или профиль не найден")
            if command.order_id is not None and not await self._repository.order_matches(
                order_id=command.order_id,
                user_id=actor.user_id,
                venue_id=command.venue_id,
            ):
                # Neutral error prevents order ID probing and enforces ownership.
                _not_found("Заказ не найден")
            employee = None
            if command.employee_staff_id is not None:
                employee = await self._repository.get_employee(command.employee_staff_id)
                if employee is None or not employee.is_active:
                    _not_found("Сотрудник не найден")
            display_name = " ".join((command.author_display_name or user.first_name).split())[:128]
            review = PublicReview(
                id=uuid4(),
                user_id=actor.user_id,
                order_id=command.order_id,
                venue_id=command.venue_id,
                employee_staff_id=command.employee_staff_id,
                rating=command.rating,
                text=text,
                author_display_name=display_name,
                status=ReviewStatus.PENDING,
            )
            self._repository.add_all([review])
            await self._repository.flush()
            return review_record(review, venue, employee)

    async def list_public(self, *, venue_id: UUID | None, limit: int) -> list[ReviewRecord]:
        return await self._repository.list_records(
            status=ReviewStatus.APPROVED, venue_id=venue_id, limit=limit
        )

    async def list_mine(self, actor: Actor, *, limit: int) -> list[ReviewRecord]:
        return await self._repository.list_records(user_id=actor.user_id, limit=limit)

    async def list_moderation(
        self, actor: Actor, *, review_status: ReviewStatus | None, limit: int
    ) -> list[ReviewRecord]:
        _require_manage(actor)
        return await self._repository.list_records(status=review_status, limit=limit)

    async def moderate(
        self,
        actor: Actor,
        review_id: UUID,
        *,
        target_status: ReviewStatus,
        note: str | None,
        now: datetime | None = None,
    ) -> ReviewRecord:
        _require_manage(actor)
        if target_status is ReviewStatus.PENDING:
            _validation("invalid_review_status", "Нельзя вернуть отзыв в очередь")
        current_time = now or datetime.now(UTC)
        async with self._repository.transaction():
            review = await self._repository.get(review_id, for_update=True)
            if review is None:
                _not_found("Отзыв не найден")
            venue = await self._repository.get_venue(review.venue_id)
            employee = (
                await self._repository.get_employee(review.employee_staff_id)
                if review.employee_staff_id is not None
                else None
            )
            if venue is None:
                _not_found("Заведение не найдено")
            review.status = target_status
            review.moderation_note = " ".join(note.split()) if note else None
            review.moderated_at = current_time
            review.moderated_by_staff_id = actor.staff_member_id
            self._repository.add_all(
                [
                    AuditEvent(
                        id=uuid4(),
                        event_type="review.moderated",
                        actor_user_id=actor.user_id,
                        actor_staff_id=actor.staff_member_id,
                        subject_user_id=review.user_id,
                        object_type="public_review",
                        object_id=review.id,
                        event_metadata={"status": target_status.value},
                        severity=AuditSeverity.INFO,
                        is_suspicious=False,
                    )
                ]
            )
            await self._repository.flush()
            return review_record(review, venue, employee)


def _require_manage(actor: Actor) -> None:
    if not actor.can(PermissionCode.ADMIN_REVIEWS_MANAGE):
        raise AppError(code="forbidden", message="Insufficient permissions", status_code=403)


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)


def _not_found(message: str) -> NoReturn:
    raise AppError(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND)

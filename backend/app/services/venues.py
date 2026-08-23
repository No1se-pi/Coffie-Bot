"""Venue use cases shared by public and administrative transports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import status
from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError, ErrorCode
from app.models.audit import AuditEvent
from app.models.content import Venue
from app.models.enums import AuditSeverity
from app.repositories.venues import VenuePage, VenueRepository
from app.security.rbac import Actor


@dataclass(frozen=True, slots=True)
class VenueRequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


EMPTY_METADATA = VenueRequestMetadata()


class VenueService:
    """Enforce Venue lifecycle invariants and atomic audit logging."""

    def __init__(self, repository: VenueRepository) -> None:
        self._repository = repository

    async def list_public(self) -> list[Venue]:
        return await self._repository.list_public()

    async def list_admin(
        self,
        *,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> VenuePage:
        return await self._repository.list_admin(
            page=page,
            page_size=page_size,
            include_archived=include_archived,
        )

    async def get_admin(self, venue_id: UUID) -> Venue:
        venue = await self._repository.get(venue_id, for_update=False)
        if venue is None:
            _not_found()
        return venue

    async def create(
        self,
        *,
        actor: Actor,
        slug: str,
        name: str,
        description: str | None,
        phone: str | None,
        email: str | None,
        website: str | None,
        telegram: str | None,
        logo_media_id: UUID | None,
        active: bool,
        sort_order: int,
        metadata: VenueRequestMetadata = EMPTY_METADATA,
    ) -> Venue:
        venue = Venue(
            id=uuid4(),
            slug=slug,
            name=name,
            description=description,
            phone=phone,
            email=email,
            website=website,
            telegram=telegram,
            logo_media_id=logo_media_id,
            is_active=active,
            sort_order=sort_order,
        )
        try:
            async with self._repository.transaction():
                if await self._repository.get_by_slug(slug, for_update=False) is not None:
                    _slug_conflict(slug)
                await self._require_media(logo_media_id)
                self._repository.add(venue)
                self._audit(
                    actor=actor,
                    event_type="venue.created",
                    venue=venue,
                    event_metadata={"slug": slug, "name": name, "active": active},
                    metadata=metadata,
                )
                await self._repository.flush()
        except IntegrityError as exc:
            if _is_slug_conflict(exc):
                _slug_conflict(slug)
            raise
        return venue

    async def update(
        self,
        *,
        actor: Actor,
        venue_id: UUID,
        updates: Mapping[str, Any],
        metadata: VenueRequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> Venue:
        allowed = {
            "slug",
            "name",
            "description",
            "phone",
            "email",
            "website",
            "telegram",
            "logo_media_id",
            "active",
            "sort_order",
        }
        unexpected = set(updates) - allowed
        if unexpected:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Unsupported Venue fields",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"fields": sorted(unexpected)},
            )
        if not updates:
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="At least one Venue field is required",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

        try:
            async with self._repository.transaction():
                venue = await self._repository.get(venue_id, for_update=True)
                if venue is None:
                    _not_found()
                if venue.archived_at is not None:
                    _conflict("venue_archived", "Archived Venue cannot be changed")
                new_slug = updates.get("slug")
                if new_slug is not None and new_slug != venue.slug:
                    conflict = await self._repository.get_by_slug(new_slug, for_update=False)
                    if conflict is not None and conflict.id != venue.id:
                        _slug_conflict(new_slug)
                if "logo_media_id" in updates:
                    await self._require_media(updates["logo_media_id"])
                for key, value in updates.items():
                    setattr(venue, "is_active" if key == "active" else key, value)
                venue.updated_at = _aware_now(now)
                self._audit(
                    actor=actor,
                    event_type="venue.updated",
                    venue=venue,
                    event_metadata={"changed_fields": sorted(updates)},
                    metadata=metadata,
                )
                await self._repository.flush()
                return venue
        except IntegrityError as exc:
            if _is_slug_conflict(exc):
                _slug_conflict(str(updates.get("slug", "")))
            raise

    async def archive(
        self,
        *,
        actor: Actor,
        venue_id: UUID,
        metadata: VenueRequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> Venue:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            venue = await self._repository.get(venue_id, for_update=True)
            if venue is None:
                _not_found()
            if venue.archived_at is not None:
                _conflict("venue_already_archived", "Venue is already archived")
            venue.is_active = False
            venue.archived_at = current_time
            venue.updated_at = current_time
            self._audit(
                actor=actor,
                event_type="venue.archived",
                venue=venue,
                event_metadata={"slug": venue.slug},
                metadata=metadata,
            )
            await self._repository.flush()
            return venue

    async def restore(
        self,
        *,
        actor: Actor,
        venue_id: UUID,
        metadata: VenueRequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> Venue:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            venue = await self._repository.get(venue_id, for_update=True)
            if venue is None:
                _not_found()
            if venue.archived_at is None:
                _conflict("venue_not_archived", "Venue is not archived")
            venue.is_active = True
            venue.archived_at = None
            venue.updated_at = current_time
            self._audit(
                actor=actor,
                event_type="venue.restored",
                venue=venue,
                event_metadata={"slug": venue.slug},
                metadata=metadata,
            )
            await self._repository.flush()
            return venue

    async def _require_media(self, media_id: UUID | None) -> None:
        if media_id is not None and not await self._repository.has_active_media(media_id):
            raise AppError(
                code=ErrorCode.VALIDATION_ERROR,
                message="Venue logo must reference an active media file",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

    def _audit(
        self,
        *,
        actor: Actor,
        event_type: str,
        venue: Venue,
        event_metadata: dict[str, Any],
        metadata: VenueRequestMetadata,
    ) -> None:
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type=event_type,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                object_type="venue",
                object_id=venue.id,
                event_metadata=event_metadata,
                severity=AuditSeverity.INFO,
                is_suspicious=False,
                ip_address=_truncate(metadata.ip_address, 45),
                user_agent=_truncate(metadata.user_agent, 512),
            )
        )


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Venue timestamps must be timezone-aware")
    return current


def _not_found() -> NoReturn:
    raise AppError(
        code=ErrorCode.NOT_FOUND,
        message="Venue was not found",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _slug_conflict(slug: str) -> NoReturn:
    raise AppError(
        code="venue_slug_conflict",
        message="Venue slug is already in use",
        status_code=status.HTTP_409_CONFLICT,
        details={"slug": slug},
    )


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def _is_slug_conflict(exc: IntegrityError) -> bool:
    return _constraint_name(exc) == "uq_venues_slug" or "uq_venues_slug" in str(exc)


def _truncate(value: str | None, limit: int) -> str | None:
    return value[:limit] if value is not None else None

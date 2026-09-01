"""Administrative delivery policy mutations with structured audit events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.content import Location
from app.models.enums import AuditSeverity, PermissionCode
from app.models.orders import DeliverySettings, DeliveryZone
from app.repositories.orders import OrderRepository
from app.security.rbac import Actor


class DeliveryAdminService:
    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    async def get_settings(self, actor: Actor) -> DeliverySettings:
        _require(actor)
        value = await self._repository.get_delivery_settings()
        if value is None:
            _not_found("Настройки доставки не найдены")
        return value

    async def update_settings(self, actor: Actor, updates: dict[str, Any]) -> DeliverySettings:
        _require(actor)
        async with self._repository.transaction():
            value = await self._repository.get_delivery_settings(lock_mode="update")
            if value is None:
                _not_found("Настройки доставки не найдены")
            for field in ("default_pickup_location_id", "consolidation_location_id"):
                location_id = updates.get(field)
                if location_id is not None:
                    location = await self._repository.get_location(location_id)
                    if location is None:
                        _validation("location_not_found", "Выбранная точка не найдена")
                    if field == "default_pickup_location_id" and not location.pickup_enabled:
                        _validation("pickup_disabled", "У выбранной точки выключена выдача")
                    if field == "consolidation_location_id" and not location.consolidation_enabled:
                        _validation(
                            "consolidation_disabled",
                            "У выбранной точки выключена консолидация",
                        )
            for field, field_value in updates.items():
                setattr(value, field, field_value)
            value.updated_by_staff_id = actor.staff_member_id
            self._audit(actor, "delivery.settings_updated", value.id)
            await self._repository.flush()
            return value

    async def list_zones(self, actor: Actor) -> list[DeliveryZone]:
        _require(actor)
        return await self._repository.list_delivery_zones(include_archived=True)

    async def create_zone(self, actor: Actor, values: dict[str, Any]) -> DeliveryZone:
        _require(actor)
        async with self._repository.transaction():
            zone = DeliveryZone(id=uuid4(), **_clean_zone(values))
            self._repository.add(zone)
            self._audit(actor, "delivery.zone_created", zone.id)
            await self._repository.flush()
            return zone

    async def update_zone(
        self, actor: Actor, zone_id: UUID, values: dict[str, Any]
    ) -> DeliveryZone:
        _require(actor)
        async with self._repository.transaction():
            zone = await self._repository.get_delivery_zone_admin(zone_id, for_update=True)
            if zone is None:
                _not_found("Зона доставки не найдена")
            if zone.archived_at is not None:
                _validation("zone_archived", "Архивную зону нельзя изменить")
            for field, field_value in _clean_zone(values).items():
                setattr(zone, field, field_value)
            self._audit(actor, "delivery.zone_updated", zone.id)
            await self._repository.flush()
            return zone

    async def archive_zone(self, actor: Actor, zone_id: UUID) -> DeliveryZone:
        _require(actor)
        async with self._repository.transaction():
            zone = await self._repository.get_delivery_zone_admin(zone_id, for_update=True)
            if zone is None:
                _not_found("Зона доставки не найдена")
            if zone.archived_at is None:
                zone.archived_at = datetime.now(UTC)
                zone.is_active = False
                self._audit(actor, "delivery.zone_archived", zone.id)
                await self._repository.flush()
            return zone

    async def list_locations(self, actor: Actor) -> list[Location]:
        _require(actor)
        return await self._repository.list_locations()

    async def create_location(self, actor: Actor, values: dict[str, Any]) -> Location:
        _require(actor)
        async with self._repository.transaction():
            if await self._repository.get_location_by_slug(str(values["slug"])) is not None:
                _conflict("location_slug_conflict", "Точка с таким slug уже существует")
            venue_id = values.get("venue_id")
            if venue_id is not None and await self._repository.get_venue(venue_id) is None:
                _validation("venue_not_found", "Выбранное заведение не найдено или неактивно")
            # Location creation lives in the same audited transaction as the
            # delivery configuration that will reference it.
            location = Location(
                id=uuid4(),
                description=None,
                latitude=None,
                longitude=None,
                business_day_boundary_minutes=0,
                opening_hours={},
                is_default=False,
                **values,
            )
            self._repository.add(location)
            self._audit(actor, "delivery.location_created", location.id)
            await self._repository.flush()
            return location

    async def update_location(
        self, actor: Actor, location_id: UUID, values: dict[str, Any]
    ) -> Location:
        _require(actor)
        async with self._repository.transaction():
            location = await self._repository.get_location(location_id, for_update=True)
            if location is None:
                _not_found("Точка не найдена")
            venue_id = values.get("venue_id")
            if venue_id is not None and await self._repository.get_venue(venue_id) is None:
                _validation("venue_not_found", "Выбранное заведение не найдено или неактивно")
            for field, field_value in values.items():
                if field_value is None and field in {"name", "address", "is_active"}:
                    continue
                setattr(location, field, field_value)
            self._audit(actor, "delivery.location_updated", location.id)
            await self._repository.flush()
            return location

    def _audit(self, actor: Actor, event_type: str, object_id: UUID) -> None:
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type=event_type,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                object_type="delivery_configuration",
                object_id=object_id,
                event_metadata={},
                severity=AuditSeverity.INFO,
                is_suspicious=False,
            )
        )


def _clean_zone(values: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(values)
    cleaned["name"] = " ".join(str(values["name"]).split()).strip()
    description = " ".join(str(values.get("description") or "").split()).strip()
    cleaned["description"] = description or None
    return cleaned


def _require(actor: Actor) -> None:
    if not actor.can(PermissionCode.ADMIN_DELIVERY_MANAGE):
        raise AppError(
            code="forbidden",
            message="Недостаточно прав",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _not_found(message: str) -> NoReturn:
    raise AppError(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)

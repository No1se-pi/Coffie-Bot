from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.routes import admin_venues, delivery_admin, venues
from app.core.errors import AppError
from app.models.audit import AuditEvent
from app.models.content import Location, Venue
from app.models.enums import PermissionCode, Role
from app.repositories.orders import OrderRepository
from app.repositories.venues import VenuePage, VenueRepository
from app.schemas.delivery_admin import LocationCreate
from app.schemas.public import contacts_response
from app.schemas.venues import VenueCreate, VenueUpdate, venue_public_response
from app.security.rbac import Actor
from app.services.delivery_admin import DeliveryAdminService
from app.services.venues import VenueRequestMetadata, VenueService

NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)


class RecordingVenueRepository:
    def __init__(self, venue: Venue | None = None) -> None:
        self.venue = venue
        self.slug_conflict: Venue | None = None
        self.added: list[object] = []
        self.commits = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield
        self.commits += 1

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, Venue):
            self.venue = value

    async def flush(self) -> None:
        return None

    async def list_public(self) -> list[Venue]:
        return [] if self.venue is None else [self.venue]

    async def list_admin(
        self,
        *,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> VenuePage:
        del page, page_size, include_archived
        items = [] if self.venue is None else [self.venue]
        return VenuePage(items=items, total=len(items))

    async def get(self, venue_id: UUID, *, for_update: bool) -> Venue | None:
        del venue_id, for_update
        return self.venue

    async def get_by_slug(self, slug: str, *, for_update: bool) -> Venue | None:
        del slug, for_update
        return self.slug_conflict

    async def has_active_media(self, media_id: UUID) -> bool:
        del media_id
        return True


class RecordingLocationRepository:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield
        self.commits += 1

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def get_location_by_slug(self, slug: str) -> Location | None:
        del slug
        return None

    async def get_venue(self, venue_id: UUID) -> Venue:
        return Venue(id=venue_id, slug="venue", name="Venue", is_active=True, sort_order=0)


def _actor() -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=42,
        session_id=uuid4(),
        role=Role.ADMIN,
        staff_member_id=uuid4(),
        permissions=frozenset({PermissionCode.ADMIN_CONTENT_MANAGE}),
    )


def _delivery_actor() -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=42,
        session_id=uuid4(),
        role=Role.ADMIN,
        staff_member_id=uuid4(),
        permissions=frozenset({PermissionCode.ADMIN_DELIVERY_MANAGE}),
    )


def _venue(*, archived: bool = False) -> Venue:
    return Venue(
        id=uuid4(),
        slug="coffee-point",
        name="Кофейня и точка",
        description="Описание",
        phone=None,
        email=None,
        website=None,
        telegram=None,
        logo_media_id=None,
        is_active=not archived,
        sort_order=10,
        archived_at=NOW if archived else None,
    )


def test_venue_routes_publish_public_and_rbac_admin_contracts() -> None:
    app = FastAPI()
    app.include_router(venues.router, prefix="/api/v1")
    app.include_router(admin_venues.router, prefix="/api/v1")

    paths = app.openapi()["paths"]
    assert "get" in paths["/api/v1/venues"]
    assert {"get", "post"}.issubset(paths["/api/v1/admin/venues"])
    assert {"get", "patch"}.issubset(paths["/api/v1/admin/venues/{venue_id}"])
    assert "post" in paths["/api/v1/admin/venues/{venue_id}/archive"]
    assert "post" in paths["/api/v1/admin/venues/{venue_id}/restore"]
    assert paths["/api/v1/admin/venues"]["post"]["security"]


def test_venue_schemas_normalize_content_and_reject_unsafe_patch_shapes() -> None:
    payload = VenueCreate(
        slug="coffee-point",
        name="  Кофейня   и точка  ",
        description="  Описание  ",
        website="https://example.com/coffee",
    )
    assert payload.name == "Кофейня и точка"
    assert payload.description == "Описание"

    with pytest.raises(ValidationError, match="https"):
        VenueCreate(
            slug="unsafe-link",
            name="Кофейня",
            website="http://example.com/coffee",
        )

    with pytest.raises(ValidationError):
        VenueCreate.model_validate(
            {"slug": "Coffee Point", "name": "Кофейня", "tenant_id": str(uuid4())}
        )
    with pytest.raises(ValidationError, match="at least one"):
        VenueUpdate.model_validate({})
    with pytest.raises(ValidationError, match="may not be null"):
        VenueUpdate.model_validate({"name": None})


def test_location_contract_adds_nullable_venue_id_without_changing_old_fields() -> None:
    venue_id = uuid4()
    location = Location(
        id=uuid4(),
        venue_id=venue_id,
        slug="main",
        name="Основная точка",
        address="Демо-адрес, 1",
        timezone="Europe/Moscow",
        business_day_boundary_minutes=0,
        opening_hours={},
        is_default=True,
        is_active=True,
        sort_order=0,
    )

    response = contacts_response({}, [location])

    assert response.locations[0].venue_id == venue_id
    assert response.locations[0].name == "Основная точка"
    venue_column = Location.__table__.c.venue_id
    assert venue_column.nullable is True
    assert next(iter(venue_column.foreign_keys)).ondelete == "SET NULL"


def test_delivery_contract_allows_creating_a_location_for_a_venue() -> None:
    app = FastAPI()
    app.include_router(delivery_admin.router, prefix="/api/v1")

    paths = app.openapi()["paths"]
    assert {"get", "post"}.issubset(paths["/api/v1/admin/delivery/locations"])
    payload = LocationCreate(
        venue_id=uuid4(),
        slug="north-point",
        name="Северная точка",
        address="ул. Северная, 1",
    )
    assert payload.pickup_enabled is True
    with pytest.raises(ValidationError):
        LocationCreate(slug="Bad slug", name="Точка", address="Адрес")


@pytest.mark.asyncio
async def test_create_location_writes_an_audit_event_in_one_transaction() -> None:
    repository = RecordingLocationRepository()
    service = DeliveryAdminService(cast(OrderRepository, repository))
    venue_id = uuid4()

    location = await service.create_location(
        _delivery_actor(),
        LocationCreate(
            venue_id=venue_id,
            slug="north-point",
            name="Северная точка",
            address="ул. Северная, 1",
        ).model_dump(),
    )

    assert location.venue_id == venue_id
    assert repository.commits == 1
    audit = next(item for item in repository.added if isinstance(item, AuditEvent))
    assert audit.event_type == "delivery.location_created"
    assert audit.object_id == location.id


def test_public_venue_response_does_not_expose_archive_state_or_media_storage() -> None:
    response = venue_public_response(_venue()).model_dump()

    assert response["name"] == "Кофейня и точка"
    assert "archived_at" not in response
    assert "logo_media_id" not in response


@pytest.mark.asyncio
async def test_create_venue_writes_audit_in_the_same_repository_transaction() -> None:
    repository = RecordingVenueRepository()
    service = VenueService(cast(VenueRepository, repository))
    actor = _actor()

    venue = await service.create(
        actor=actor,
        slug="food-court",
        name="ФудДворик",
        description=None,
        phone=None,
        email=None,
        website=None,
        telegram=None,
        logo_media_id=None,
        active=True,
        sort_order=20,
        metadata=VenueRequestMetadata(ip_address="127.0.0.1", user_agent="pytest"),
    )

    assert venue.slug == "food-court"
    assert repository.commits == 1
    audit = next(item for item in repository.added if isinstance(item, AuditEvent))
    assert audit.event_type == "venue.created"
    assert audit.object_id == venue.id
    assert audit.actor_user_id == actor.user_id
    assert audit.ip_address == "127.0.0.1"


@pytest.mark.asyncio
async def test_duplicate_venue_slug_is_a_stable_conflict() -> None:
    repository = RecordingVenueRepository()
    repository.slug_conflict = _venue()
    service = VenueService(cast(VenueRepository, repository))

    with pytest.raises(AppError) as error:
        await service.create(
            actor=_actor(),
            slug="coffee-point",
            name="Дубликат",
            description=None,
            phone=None,
            email=None,
            website=None,
            telegram=None,
            logo_media_id=None,
            active=True,
            sort_order=0,
        )

    assert error.value.status_code == 409
    assert error.value.code == "venue_slug_conflict"


@pytest.mark.asyncio
async def test_archive_and_restore_are_locked_audited_lifecycle_transitions() -> None:
    repository = RecordingVenueRepository(_venue())
    service = VenueService(cast(VenueRepository, repository))
    actor = _actor()

    archived = await service.archive(actor=actor, venue_id=repository.venue.id, now=NOW)  # type: ignore[union-attr]
    assert archived.archived_at == NOW
    assert archived.is_active is False

    restored = await service.restore(actor=actor, venue_id=archived.id, now=NOW)
    assert restored.archived_at is None
    assert restored.is_active is True
    assert [item.event_type for item in repository.added if isinstance(item, AuditEvent)] == [
        "venue.archived",
        "venue.restored",
    ]


@pytest.mark.asyncio
async def test_archived_venue_cannot_be_patched() -> None:
    repository = RecordingVenueRepository(_venue(archived=True))
    service = VenueService(cast(VenueRepository, repository))

    with pytest.raises(AppError) as error:
        await service.update(
            actor=_actor(),
            venue_id=repository.venue.id,  # type: ignore[union-attr]
            updates={"name": "Новое имя"},
            now=NOW,
        )

    assert error.value.status_code == 409
    assert error.value.code == "venue_archived"

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.core.config import AppEnvironment
from app.models.enums import PermissionCode, Role
from app.services.seed import SeedConfigurationError, SeedDocument, SeedService

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)
SEED_PATH = Path(__file__).parents[3] / "configs" / "demo-seed.json"


class FakeSeedRepository:
    def __init__(self, *, active_staff_id: UUID | None = None) -> None:
        self.active_staff_id = active_staff_id
        self.entity_ids: dict[str, UUID] = {}
        self.entity_id_calls: list[UUID] = []
        self.settings: dict[str, Any] = {}
        self.venue_ids: dict[str, UUID] = {}
        self.location_venue_ids: dict[str, UUID | None] = {}
        self.development_staff_calls: list[int] = []
        self.commits = 0
        self.rollbacks = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        try:
            yield
        except BaseException:
            self.rollbacks += 1
            raise
        else:
            self.commits += 1

    async def acquire_lock(self) -> None:
        return None

    async def load_seed_entity_ids(self) -> dict[str, UUID]:
        return dict(self.entity_ids)

    async def save_seed_entity_ids(self, values: dict[str, UUID]) -> None:
        self.entity_ids = dict(values)

    async def upsert_app_setting(self, key: str, value: Any, *, is_public: bool) -> None:
        assert is_public is True
        self.settings[key] = value

    async def upsert_venue(
        self,
        entity_id: UUID,
        slug: str,
        values: dict[str, Any],
    ) -> UUID:
        assert values["name"]
        persisted_id = self.venue_ids.setdefault(slug, entity_id)
        self.entity_id_calls.append(persisted_id)
        return persisted_id

    async def upsert_location(self, slug: str, values: dict[str, Any]) -> UUID:
        assert slug
        assert values["name"]
        self.location_venue_ids[slug] = values.get("venue_id")
        return uuid4()

    async def find_media_id(self, storage_key: str | None) -> UUID | None:
        assert storage_key is None
        return None

    async def upsert_reward_template(
        self,
        entity_id: UUID,
        values: dict[str, Any],
    ) -> UUID:
        assert values["name"]
        self.entity_id_calls.append(entity_id)
        return entity_id

    async def upsert_loyalty_settings(self, values: dict[str, Any]) -> UUID:
        assert values["minor_units_per_point"] == 1000
        return uuid4()

    async def upsert_menu_category(
        self,
        entity_id: UUID,
        values: dict[str, Any],
    ) -> UUID:
        assert values["name"]
        self.entity_id_calls.append(entity_id)
        return entity_id

    async def upsert_menu_item(
        self,
        entity_id: UUID,
        values: dict[str, Any],
    ) -> UUID:
        assert values["category_id"]
        self.entity_id_calls.append(entity_id)
        return entity_id

    async def upsert_promotion(
        self,
        entity_id: UUID,
        values: dict[str, Any],
    ) -> UUID:
        assert values["created_by_staff_id"] == self.active_staff_id
        self.entity_id_calls.append(entity_id)
        return entity_id

    async def find_active_staff_id(self) -> UUID | None:
        return self.active_staff_id

    async def upsert_seed_staff(
        self,
        *,
        telegram_id: int,
        display_name: str,
        role: Role,
        permissions: set[PermissionCode],
        is_active: bool,
    ) -> UUID:
        assert display_name
        assert role == Role.STAFF
        assert permissions
        assert is_active is True
        self.development_staff_calls.append(telegram_id)
        if self.active_staff_id is None:
            self.active_staff_id = uuid4()
        return self.active_staff_id

    async def export_configuration(self) -> dict[str, Any]:
        return {"app_settings": self.settings}


def test_demo_seed_file_is_valid_and_neutral() -> None:
    document = SeedDocument.from_file(SEED_PATH)

    assert document.schema_version == 1
    assert document.installation.mode == "single_organization"
    assert document.brand.name == "Демо Кофе"
    assert [item.name for item in document.venues] == [
        "Кофейня и точка",
        "ФудДворик",
        "Шашлык Джан",
    ]
    assert {location.venue_slug for location in document.locations} == {
        "coffee-point",
        "food-court",
        "shashlik-dzhan",
    }
    assert document.development_only.staff_members[0].synthetic is True


def test_seed_rejects_unknown_location_venue_reference() -> None:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload["locations"][0]["venue_slug"] = "missing-venue"

    with pytest.raises(ValueError, match="unknown venue slug"):
        SeedDocument.model_validate(payload)


def test_schema_v1_seed_without_venues_remains_valid() -> None:
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    payload.pop("venues")
    for location in payload["locations"]:
        location.pop("venue_slug")

    document = SeedDocument.model_validate(payload)

    assert document.schema_version == 1
    assert document.venues == []
    assert all(location.venue_slug is None for location in document.locations)


@pytest.mark.asyncio
async def test_development_seed_is_repeatable_with_stable_entity_ids() -> None:
    document = SeedDocument.from_file(SEED_PATH)
    repository = FakeSeedRepository()
    service = SeedService(repository)

    first = await service.apply(document, environment=AppEnvironment.DEVELOPMENT, now=NOW)
    first_call_ids = list(repository.entity_id_calls)
    repository.entity_id_calls.clear()
    second = await service.apply(document, environment=AppEnvironment.DEVELOPMENT, now=NOW)

    assert first.development_staff == 1
    assert first.venues == 3
    assert first.locations == 3
    assert second.development_staff == 1
    assert repository.development_staff_calls == [1000000000001, 1000000000001]
    assert repository.entity_id_calls == first_call_ids
    assert repository.commits == 2
    assert len(repository.entity_ids) == len(first_call_ids)
    assert set(repository.location_venue_ids.values()) == set(repository.venue_ids.values())


@pytest.mark.asyncio
async def test_production_seed_never_imports_development_staff() -> None:
    document = SeedDocument.from_file(SEED_PATH)
    repository = FakeSeedRepository(active_staff_id=uuid4())

    report = await SeedService(repository).apply(
        document,
        environment=AppEnvironment.PRODUCTION,
        now=NOW,
    )

    assert report.development_staff == 0
    assert repository.development_staff_calls == []


@pytest.mark.asyncio
async def test_seed_requires_real_staff_author_for_promotions_outside_development() -> None:
    document = SeedDocument.from_file(SEED_PATH)
    repository = FakeSeedRepository()

    with pytest.raises(SeedConfigurationError, match="create-owner"):
        await SeedService(repository).apply(
            document,
            environment=AppEnvironment.PRODUCTION,
            now=NOW,
        )

    assert repository.development_staff_calls == []
    assert repository.rollbacks == 1

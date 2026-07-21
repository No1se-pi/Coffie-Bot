from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api.routes import admin_content, admin_staff, media, staff_profile
from app.core.errors import AppError
from app.models.access import StaffMember
from app.models.enums import Role, RoundingMode
from app.models.loyalty import LoyaltySettings
from app.repositories.admin import AdminRepository
from app.schemas.admin import (
    MenuItemUpdate,
    PromotionCreate,
    boundary_minutes,
    loyalty_settings_response,
)
from app.security.rbac import Actor
from app.services.admin import (
    MAX_MEDIA_BYTES,
    AdminService,
    detect_image_mime,
    safe_original_filename,
)

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)


class RecordingAdminRepository:
    def __init__(self) -> None:
        self.added: list[object] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


def _actor(role: Role = Role.OWNER) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=42,
        session_id=uuid4(),
        role=role,
        staff_member_id=uuid4(),
        permissions=frozenset(),
    )


def test_admin_routes_import_and_publish_expected_paths() -> None:
    app = FastAPI()
    for router in (
        admin_content.router,
        admin_staff.router,
        staff_profile.router,
        media.router,
    ):
        app.include_router(router, prefix="/api/v1")

    paths = app.openapi()["paths"]
    assert "/api/v1/admin/loyalty-settings" in paths
    assert "/api/v1/admin/staff/invites" in paths
    assert "/api/v1/staff/me/tip-profile" in paths
    assert "/api/v1/admin/media" in paths
    assert "/api/v1/media/{media_id}" in paths


def test_settings_shape_uses_exact_integer_minor_unit_conversion() -> None:
    settings = LoyaltySettings(
        id=uuid4(),
        singleton_key="default",
        points_enabled=True,
        currency_name="бобы",
        minor_units_per_point=1_000,
        minimum_purchase_minor=10_000,
        rounding_mode=RoundingMode.FLOOR,
        maximum_redemption_percent=30,
        visits_enabled=True,
        visit_required_count=5,
        timezone="Europe/Moscow",
        business_day_boundary_minutes=240,
        stamps_enabled=True,
        stamp_required_count=9,
    )

    response = loyalty_settings_response(settings)

    assert response.rubles_per_point == 10
    assert response.minimum_purchase_minor == 10_000
    assert response.business_day_boundary == "04:00"
    assert boundary_minutes(response.business_day_boundary) == 240


def test_admin_patch_forbids_excess_fields_and_promotion_requires_aware_window() -> None:
    with pytest.raises(ValidationError):
        MenuItemUpdate.model_validate({"visible": False, "archived_at": NOW.isoformat()})
    with pytest.raises(ValidationError):
        PromotionCreate(
            title="Акция",
            text="Условия",
            starts_at=NOW.replace(tzinfo=None),
        )


def test_image_sniffing_and_filename_sanitization_reject_spoofing() -> None:
    assert detect_image_mime(b"\x89PNG\r\n\x1a\ncontent") == "image/png"
    assert detect_image_mime(b"\xff\xd8\xffcontent") == "image/jpeg"
    assert safe_original_filename(r"..\..\secret\photo.png") == "photo.png"
    with pytest.raises(AppError) as error:
        detect_image_mime(b"<svg><script>alert(1)</script></svg>")
    assert error.value.status_code == 415


@pytest.mark.asyncio
async def test_media_upload_uses_random_confined_path_and_audits(tmp_path: Path) -> None:
    repository = RecordingAdminRepository()
    service = AdminService(repository=cast(AdminRepository, repository))
    content = b"\x89PNG\r\n\x1a\ncontent"

    result = await service.upload_media(
        actor=_actor(),
        content=content,
        original_filename="../../outside.png",
        claimed_content_type="image/png",
        kind="menu",
        media_root=tmp_path,
        now=NOW,
    )

    stored_path = tmp_path / result.media.storage_key
    assert ".." not in Path(result.media.storage_key).parts
    assert await asyncio.to_thread(stored_path.read_bytes) == content
    assert "outside" not in result.media.storage_key
    assert result.media.original_filename == "outside.png"
    assert len(repository.added) == 2  # MediaFile plus immutable AuditEvent.

    with pytest.raises(AppError) as error:
        await service.upload_media(
            actor=_actor(),
            content=b"x" * (MAX_MEDIA_BYTES + 1),
            original_filename="large.png",
            claimed_content_type="image/png",
            kind="menu",
            media_root=tmp_path,
            now=NOW,
        )
    assert error.value.status_code == 413


def test_admin_cannot_manage_privileged_roles_and_last_owner_is_guarded() -> None:
    admin = _actor(Role.ADMIN)
    with pytest.raises(AppError) as forbidden:
        AdminService._validate_role_assignment(
            admin,
            current_role=Role.STAFF,
            new_role=Role.ADMIN,
        )
    assert forbidden.value.status_code == 403

    owner = StaffMember(
        id=uuid4(),
        user_id=uuid4(),
        role=Role.OWNER,
        is_active=True,
    )
    with pytest.raises(AppError) as conflict:
        AdminService._guard_last_owner(owner, 1)
    assert conflict.value.status_code == 409

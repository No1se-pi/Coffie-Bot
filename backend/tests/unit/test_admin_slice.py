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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import admin_content, admin_staff, media, staff_profile
from app.core.errors import AppError
from app.models.access import StaffMember, StaffPermission, User
from app.models.audit import AuditEvent
from app.models.content import MenuItem
from app.models.enums import (
    FeedbackCategory,
    FeedbackStatus,
    PermissionCode,
    Role,
    RoundingMode,
)
from app.models.loyalty import LoyaltySettings, RewardTemplate
from app.models.staff import FeedbackItem
from app.repositories.admin import AdminRepository, FeedbackRecord, LockedStaffManagement
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
        self.feedback_record: FeedbackRecord | None = None
        self.deleted_feedback: list[FeedbackItem] = []
        self.staff_user: User | None = None
        self.existing_staff: StaffMember | None = None
        self.permission_overrides: dict[PermissionCode, bool] | None = None
        self.staff_permissions_were_initialized = False
        self.locked_staff: LockedStaffManagement | None = None
        self.revoked_staff_user_id: object | None = None
        self.menu_item: MenuItem | None = None
        self.reward_template: RewardTemplate | None = None
        self.flush_item_template_ids: list[object | None] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_item_template_ids.append(
            self.menu_item.points_reward_template_id if self.menu_item is not None else None
        )
        return None

    async def get_menu_item(
        self,
        _item_id: object,
        *,
        for_update: bool,
    ) -> MenuItem | None:
        assert for_update is True
        return self.menu_item

    async def get_reward_template(self, _template_id: object) -> RewardTemplate | None:
        return self.reward_template

    async def get_feedback(
        self,
        _feedback_id: object,
        *,
        for_update: bool,
    ) -> FeedbackRecord | None:
        assert for_update is True
        return self.feedback_record

    async def delete_feedback(self, feedback: FeedbackItem) -> None:
        self.deleted_feedback.append(feedback)

    async def get_user_for_staff_creation(self, _user_id: object) -> User | None:
        return self.staff_user

    async def get_staff_by_user(
        self,
        _user_id: object,
        *,
        for_update: bool,
    ) -> StaffMember | None:
        assert for_update is True
        return self.existing_staff

    def replace_staff_permissions(
        self,
        staff: StaffMember,
        permissions: dict[PermissionCode, bool],
    ) -> None:
        self.staff_permissions_were_initialized = "permissions" in staff.__dict__
        self.permission_overrides = permissions

    async def lock_staff_management(
        self,
        _staff_id: object,
    ) -> LockedStaffManagement | None:
        return self.locked_staff

    async def revoke_user_sessions(
        self,
        *,
        user_id: object,
        now: datetime,
        reason: str,
    ) -> int:
        assert now == NOW
        assert reason == "staff_archived"
        self.revoked_staff_user_id = user_id
        return 2


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
    assert "delete" in paths["/api/v1/admin/feedback/{feedback_id}"]
    assert "delete" in paths["/api/v1/admin/staff/{staff_id}"]
    assert "/api/v1/admin/staff/invites" in paths
    assert "/api/v1/staff/me/tip-profile" in paths
    assert "/api/v1/staff/me/tip-profile/cancel-review" in paths
    assert "/api/v1/admin/media" in paths
    assert "/api/v1/staff/me/media" in paths
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


@pytest.mark.asyncio
async def test_points_price_flushes_reward_template_before_menu_item_foreign_key() -> None:
    repository = RecordingAdminRepository()
    item = MenuItem(
        id=uuid4(),
        category_id=uuid4(),
        name="Капучино",
        price_minor=29_000,
        points_price=None,
        labels=[],
        is_available=True,
        is_visible=True,
        sort_order=0,
        archived_at=None,
    )
    repository.menu_item = item
    service = AdminService(repository=cast(AdminRepository, repository))

    updated = await service.update_menu_item(
        actor=_actor(),
        item_id=item.id,
        updates={"points_price": 120},
    )

    template = next(value for value in repository.added if isinstance(value, RewardTemplate))
    assert repository.flush_item_template_ids == [None, template.id]
    assert updated.points_price == 120
    assert updated.points_reward_template_id == template.id


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


@pytest.mark.asyncio
async def test_feedback_must_be_archived_before_deletion_and_keeps_audit() -> None:
    repository = RecordingAdminRepository()
    feedback = FeedbackItem(
        id=uuid4(),
        user_id=uuid4(),
        rating=2,
        category=FeedbackCategory.SERVICE,
        message="Long wait",
        may_contact=False,
        status=FeedbackStatus.NEW,
    )
    repository.feedback_record = FeedbackRecord(
        feedback=feedback,
        user=User(id=feedback.user_id, telegram_id=100, first_name="Anna"),
    )
    service = AdminService(repository=cast(AdminRepository, repository))

    with pytest.raises(AppError) as conflict:
        await service.delete_feedback(actor=_actor(), feedback_id=feedback.id)
    assert conflict.value.status_code == 409
    assert repository.deleted_feedback == []

    feedback.status = FeedbackStatus.ARCHIVED
    await service.delete_feedback(actor=_actor(), feedback_id=feedback.id)

    assert repository.deleted_feedback == [feedback]
    audit = next(item for item in repository.added if isinstance(item, AuditEvent))
    assert audit.event_type == "feedback.deleted"
    assert audit.object_id == feedback.id


@pytest.mark.asyncio
async def test_created_staff_keeps_loaded_user_for_response_and_permissions() -> None:
    repository = RecordingAdminRepository()
    repository.staff_user = User(
        id=uuid4(),
        telegram_id=101,
        first_name="Anna",
    )
    service = AdminService(repository=cast(AdminRepository, repository))

    staff = await service.create_staff(
        actor=_actor(),
        user_id=repository.staff_user.id,
        role=Role.STAFF,
        display_name="Anna",
        position="Barista",
        bio=None,
        can_edit_tip_profile=True,
        permissions={PermissionCode.POINTS_REDEEM: False},
    )

    assert staff.user is repository.staff_user
    assert repository.staff_permissions_were_initialized is True
    assert repository.permission_overrides == {PermissionCode.POINTS_REDEEM: False}


@pytest.mark.asyncio
async def test_archived_staff_profile_is_restored_instead_of_conflicting() -> None:
    repository = RecordingAdminRepository()
    user = User(id=uuid4(), telegram_id=102, first_name="Ivan")
    repository.staff_user = user
    repository.existing_staff = StaffMember(
        id=uuid4(),
        user_id=user.id,
        role=Role.STAFF,
        display_name="Старое имя",
        is_active=False,
        disabled_at=NOW,
        archived_at=NOW,
        user=user,
        permissions=[],
    )
    service = AdminService(repository=cast(AdminRepository, repository))

    restored = await service.create_staff(
        actor=_actor(),
        user_id=user.id,
        role=Role.STAFF,
        display_name="Новое имя",
        position="Бариста",
        bio=None,
        can_edit_tip_profile=True,
        permissions={PermissionCode.CARD_LOOKUP: True},
        now=NOW,
    )

    assert restored is repository.existing_staff
    assert restored.is_active is True
    assert restored.archived_at is None
    assert restored.disabled_at is None
    assert restored.display_name == "Новое имя"
    audit = next(item for item in repository.added if isinstance(item, AuditEvent))
    assert audit.event_type == "staff.restored"


@pytest.mark.asyncio
async def test_archiving_staff_revokes_access_but_preserves_the_record() -> None:
    repository = RecordingAdminRepository()
    staff = StaffMember(
        id=uuid4(),
        user_id=uuid4(),
        role=Role.STAFF,
        is_active=True,
        disabled_at=None,
        archived_at=None,
    )
    repository.locked_staff = LockedStaffManagement(target=staff, active_owner_count=1)
    service = AdminService(repository=cast(AdminRepository, repository))

    await service.archive_staff(
        actor=_actor(),
        staff_id=staff.id,
        now=NOW,
    )

    assert staff.is_active is False
    assert staff.disabled_at == NOW
    assert staff.archived_at == NOW
    assert repository.revoked_staff_user_id == staff.user_id
    audit = next(item for item in repository.added if isinstance(item, AuditEvent))
    assert audit.event_type == "staff.archived"
    assert audit.event_metadata == {"revoked_sessions": 2}


def test_staff_permission_replacement_updates_existing_rows_without_duplicates() -> None:
    staff_id = uuid4()
    existing = StaffPermission(
        id=uuid4(),
        staff_member_id=staff_id,
        permission=PermissionCode.CARD_LOOKUP,
        allowed=False,
    )
    obsolete = StaffPermission(
        id=uuid4(),
        staff_member_id=staff_id,
        permission=PermissionCode.POINTS_REDEEM,
        allowed=True,
    )
    staff = StaffMember(
        id=staff_id,
        user_id=uuid4(),
        role=Role.STAFF,
        permissions=[existing, obsolete],
    )
    repository = AdminRepository(cast(AsyncSession, object()))

    repository.replace_staff_permissions(
        staff,
        {
            PermissionCode.CARD_LOOKUP: True,
            PermissionCode.STAMPS_ADD: False,
        },
    )

    by_permission = {item.permission: item for item in staff.permissions}
    assert by_permission[PermissionCode.CARD_LOOKUP] is existing
    assert by_permission[PermissionCode.CARD_LOOKUP].allowed is True
    assert by_permission[PermissionCode.STAMPS_ADD].allowed is False
    assert PermissionCode.POINTS_REDEEM not in by_permission


@pytest.mark.asyncio
async def test_staff_update_keeps_updated_at_loaded_for_the_api_response() -> None:
    repository = RecordingAdminRepository()
    staff = StaffMember(
        id=uuid4(),
        user_id=uuid4(),
        role=Role.STAFF,
        display_name="Before",
        is_active=True,
        archived_at=None,
        permissions=[],
    )
    repository.locked_staff = LockedStaffManagement(target=staff, active_owner_count=1)
    service = AdminService(repository=cast(AdminRepository, repository))

    updated = await service.update_staff(
        actor=_actor(),
        staff_id=staff.id,
        updates={"display_name": "After"},
        permissions=None,
        now=NOW,
    )

    assert updated.display_name == "After"
    assert updated.updated_at == NOW

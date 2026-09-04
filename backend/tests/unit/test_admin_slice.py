from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes import admin_content, admin_staff, media, staff_profile
from app.core.errors import AppError
from app.models.access import StaffMember, StaffPermission, User
from app.models.audit import AuditEvent
from app.models.content import MenuItem, Promotion
from app.models.enums import (
    AuditSeverity,
    FeedbackCategory,
    FeedbackStatus,
    LoyaltyProgram,
    PermissionCode,
    PromotionStatus,
    RewardType,
    Role,
    RoundingMode,
)
from app.models.loyalty import LoyaltySettings, RewardTemplate
from app.models.staff import FeedbackItem
from app.repositories.admin import AdminRepository, FeedbackRecord, LockedStaffManagement
from app.schemas.admin import (
    LoyaltySettingsUpdate,
    MenuItemUpdate,
    PromotionCreate,
    TipProfileUpdate,
    boundary_minutes,
    loyalty_settings_response,
)
from app.security.rbac import Actor
from app.services.admin import (
    MAX_MEDIA_BYTES,
    AdminService,
    LoyaltyRewardConfiguration,
    LoyaltySettingsView,
    detect_image_mime,
    safe_original_filename,
)

NOW = datetime(2026, 7, 21, 12, tzinfo=UTC)


class RecordingAdminRepository:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.feedback_record: FeedbackRecord | None = None
        self.deleted_feedback: list[FeedbackItem] = []
        self.promotion: Promotion | None = None
        self.deleted_promotions: list[Promotion] = []
        self.staff_user: User | None = None
        self.existing_staff: StaffMember | None = None
        self.permission_overrides: dict[PermissionCode, bool] | None = None
        self.staff_permissions_were_initialized = False
        self.locked_staff: LockedStaffManagement | None = None
        self.revoked_staff_user_id: object | None = None
        self.menu_item: MenuItem | None = None
        self.deleted_menu_items: list[MenuItem] = []
        self.current_loyalty_reward_programs: frozenset[LoyaltyProgram] = frozenset()
        self.settings: LoyaltySettings | None = None
        self.reward_template: RewardTemplate | None = None
        self.reward_templates: dict[object, RewardTemplate] = {}
        self.audit_by_idempotency_key: dict[str, AuditEvent] = {}
        self.idempotency_locks: list[tuple[str, str]] = []
        self.flush_item_template_ids: list[object | None] = []

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, RewardTemplate):
            self.reward_templates[value.id] = value
        if isinstance(value, AuditEvent) and value.idempotency_key is not None:
            self.audit_by_idempotency_key[value.idempotency_key] = value

    async def acquire_idempotency_lock(self, namespace: str, key: str) -> None:
        self.idempotency_locks.append((namespace, key))

    async def get_audit_event_by_idempotency_key(
        self,
        key: str,
    ) -> AuditEvent | None:
        return self.audit_by_idempotency_key.get(key)

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
        return self.menu_item

    async def get_reward_template(
        self,
        template_id: object,
        *,
        for_update: bool = False,
    ) -> RewardTemplate | None:
        del for_update
        return self.reward_templates.get(template_id, self.reward_template)

    async def get_menu_item_loyalty_reward_programs(
        self,
        _item_id: object,
        *,
        for_update: bool,
    ) -> frozenset[LoyaltyProgram]:
        assert for_update is True
        return self.current_loyalty_reward_programs

    async def delete_menu_item(self, item: MenuItem) -> None:
        self.deleted_menu_items.append(item)

    async def get_loyalty_settings(self, *, for_update: bool) -> LoyaltySettings | None:
        del for_update
        return self.settings

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

    async def get_promotion(
        self,
        _promotion_id: object,
        *,
        for_update: bool,
    ) -> Promotion | None:
        assert for_update is True
        return self.promotion

    async def delete_promotion(self, promotion: Promotion) -> None:
        self.deleted_promotions.append(promotion)

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


def _loyalty_settings() -> LoyaltySettings:
    return LoyaltySettings(
        id=uuid4(),
        singleton_key="default",
        points_enabled=True,
        currency_name="баллы",
        minor_units_per_point=1_000,
        redemption_minor_units_per_point=100,
        minimum_purchase_minor=0,
        maximum_purchase_minor=1_000_000,
        rounding_mode=RoundingMode.FLOOR,
        maximum_redemption_percent=50,
        minimum_redemption_points=1,
        welcome_bonus_points=0,
        large_operation_requires_approval=False,
        visits_enabled=True,
        visit_required_count=5,
        visits_must_be_consecutive=True,
        visit_daily_limit=1,
        timezone="Europe/Moscow",
        business_day_boundary_minutes=0,
        visit_allowed_misses=0,
        visit_reset_on_miss=True,
        visit_restart_cycle=True,
        stamps_enabled=True,
        stamp_required_count=9,
        stamps_per_purchase=1,
        stamp_operation_limit=10,
        reset_stamps_after_reward=True,
    )


async def _save_loyalty_settings(
    service: AdminService,
    *,
    points_enabled: bool = True,
    visit_enabled: bool = True,
    stamps_enabled: bool = True,
    visit_reward: LoyaltyRewardConfiguration | None = None,
    stamp_reward: LoyaltyRewardConfiguration | None = None,
) -> LoyaltySettingsView:
    return await service.update_loyalty_settings(
        actor=_actor(),
        points_enabled=points_enabled,
        currency_name="баллы",
        rubles_per_point=10,
        redemption_rubles_per_point=1,
        minimum_purchase_minor=0,
        maximum_purchase_minor=1_000_000,
        rounding=RoundingMode.FLOOR.value,
        max_redemption_percent=50,
        minimum_redemption_points=1,
        welcome_bonus_points=0,
        points_validity_days=None,
        daily_accrual_limit_points=None,
        operation_accrual_limit_points=None,
        large_operation_threshold_minor=None,
        large_operation_requires_approval=False,
        visit_enabled=visit_enabled,
        visit_goal=5,
        visits_must_be_consecutive=True,
        visit_daily_limit=1,
        timezone="Europe/Moscow",
        business_day_boundary_minutes=0,
        visit_allowed_misses=0,
        visit_reset_on_miss=True,
        visit_reward_validity_days=30,
        visit_restart_cycle=True,
        stamps_enabled=stamps_enabled,
        stamp_goal=9,
        stamps_per_purchase=1,
        stamp_operation_limit=10,
        stamp_reward_validity_days=30,
        reset_stamps_after_reward=True,
        visit_reward=visit_reward,
        stamp_reward=stamp_reward,
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
    menu_delete = paths["/api/v1/admin/menu/items/{item_id}"]["delete"]
    assert any(
        parameter["name"] == "Idempotency-Key"
        and parameter["in"] == "header"
        and parameter["required"] is True
        for parameter in menu_delete["parameters"]
    )
    assert "delete" in paths["/api/v1/admin/feedback/{feedback_id}"]
    assert "delete" in paths["/api/v1/admin/promotions/{promotion_id}"]
    assert "/api/v1/admin/promotions/{promotion_id}/restore" in paths
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


def test_loyalty_reward_settings_use_strict_discriminated_shapes() -> None:
    payload = loyalty_settings_response(_loyalty_settings()).model_dump()
    payload["visit_reward"] = {"kind": "points", "points": 0}
    with pytest.raises(ValidationError):
        LoyaltySettingsUpdate.model_validate(payload)

    payload["visit_reward"] = {
        "kind": "menu_item",
        "menu_item_id": str(uuid4()),
        "name": "Client-controlled snapshot",
    }
    with pytest.raises(ValidationError):
        LoyaltySettingsUpdate.model_validate(payload)


@pytest.mark.asyncio
async def test_settings_create_separate_menu_and_custom_reward_templates() -> None:
    repository = RecordingAdminRepository()
    repository.settings = _loyalty_settings()
    repository.menu_item = MenuItem(
        id=uuid4(),
        category_id=uuid4(),
        name="Раф",
        description="Любой раф из меню",
        image_media_id=uuid4(),
        price_minor=35_000,
        labels=[],
        is_available=True,
        is_visible=True,
        sort_order=0,
        archived_at=None,
    )
    service = AdminService(repository=cast(AdminRepository, repository))

    view = await _save_loyalty_settings(
        service,
        visit_reward=LoyaltyRewardConfiguration(
            kind="menu_item",
            menu_item_id=repository.menu_item.id,
        ),
        stamp_reward=LoyaltyRewardConfiguration(
            kind="custom",
            name="Секретный десерт",
            description="Спросите бариста о десерте дня",
        ),
    )

    visit = view.visit_reward_template
    stamp = view.stamp_reward_template
    assert visit is not None
    assert visit.source_program is LoyaltyProgram.VISITS
    assert visit.reward_type is RewardType.FREE_PRODUCT
    assert visit.source_menu_item_id == repository.menu_item.id
    assert visit.name == repository.menu_item.name
    assert visit.image_media_id == repository.menu_item.image_media_id
    assert stamp is not None
    assert stamp.source_program is LoyaltyProgram.STAMPS
    assert stamp.reward_type is RewardType.TEXT
    assert stamp.name == "Секретный десерт"
    assert repository.settings.visit_reward_template_id == visit.id
    assert repository.settings.stamp_reward_template_id == stamp.id


@pytest.mark.asyncio
async def test_points_reward_requires_enabled_points_program_and_replaces_old_template() -> None:
    repository = RecordingAdminRepository()
    settings = _loyalty_settings()
    old = RewardTemplate(
        id=uuid4(),
        name="Старая награда",
        description="Старое описание",
        reward_type=RewardType.TEXT,
        source_program=LoyaltyProgram.VISITS,
        is_active=True,
    )
    settings.visit_reward_template_id = old.id
    repository.settings = settings
    repository.reward_templates[old.id] = old
    service = AdminService(repository=cast(AdminRepository, repository))

    with pytest.raises(AppError) as disabled:
        await _save_loyalty_settings(
            service,
            points_enabled=False,
            visit_reward=LoyaltyRewardConfiguration(kind="points", points=75),
        )
    assert disabled.value.status_code == 422

    old.is_active = True  # The recording transaction does not emulate rollback.
    settings.visit_reward_template_id = old.id
    view = await _save_loyalty_settings(
        service,
        visit_reward=LoyaltyRewardConfiguration(kind="points", points=75),
    )

    template = view.visit_reward_template
    assert template is not None
    assert template.reward_type is RewardType.POINTS
    assert template.value_int == 75
    assert template.validity_days is None
    assert view.settings.visit_reward_validity_days is None
    assert old.is_active is False


def test_admin_patch_forbids_excess_fields_and_promotion_requires_aware_window() -> None:
    with pytest.raises(ValidationError):
        MenuItemUpdate.model_validate({"visible": False, "archived_at": NOW.isoformat()})
    with pytest.raises(ValidationError):
        PromotionCreate(
            title="Акция",
            text="Условия",
            starts_at=NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValidationError, match="https"):
        PromotionCreate(
            title="Акция",
            text="Условия",
            button_url="http://example.com/promotion",
        )
    with pytest.raises(ValidationError, match="https"):
        TipProfileUpdate(
            display_name="Бариста",
            position="Бариста",
            tip_url="http://example.com/tips",
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


def _menu_item(*, template_id: UUID | None = None, archived: bool = False) -> MenuItem:
    return MenuItem(
        id=uuid4(),
        category_id=uuid4(),
        name="Капучино",
        description="Кофе с молоком",
        price_minor=29_000,
        points_price=120 if template_id is not None else None,
        points_reward_template_id=template_id,
        labels=[],
        is_available=not archived,
        is_visible=not archived,
        sort_order=0,
        archived_at=NOW if archived else None,
    )


def _points_reward_template(template_id: UUID) -> RewardTemplate:
    return RewardTemplate(
        id=template_id,
        name="Капучино",
        description="Кофе с молоком",
        reward_type=RewardType.FREE_PRODUCT,
        source_program=LoyaltyProgram.POINTS,
        value_int=120,
        validity_days=30,
        is_active=True,
    )


@pytest.mark.asyncio
async def test_menu_item_archive_and_restore_keep_safe_flags_and_audit() -> None:
    repository = RecordingAdminRepository()
    template_id = uuid4()
    repository.menu_item = _menu_item(template_id=template_id)
    repository.reward_template = _points_reward_template(template_id)
    service = AdminService(repository=cast(AdminRepository, repository))

    archived = await service.hide_menu_item(
        actor=_actor(),
        item_id=repository.menu_item.id,
        now=NOW,
    )

    assert archived.archived_at == NOW
    assert archived.is_visible is False
    assert archived.is_available is False
    assert repository.reward_template.is_active is False
    archive_audit = next(
        item
        for item in repository.added
        if isinstance(item, AuditEvent) and item.event_type == "menu.item_archived"
    )
    assert archive_audit.severity is AuditSeverity.INFO

    restored = await service.restore_menu_item(
        actor=_actor(),
        item_id=repository.menu_item.id,
    )

    assert restored.archived_at is None
    assert restored.is_visible is False
    assert restored.is_available is False
    restore_audit = next(
        item
        for item in repository.added
        if isinstance(item, AuditEvent) and item.event_type == "menu.item_restored"
    )
    assert restore_audit.severity is AuditSeverity.INFO


@pytest.mark.asyncio
async def test_menu_item_delete_requires_archive_and_deactivates_points_template() -> None:
    repository = RecordingAdminRepository()
    template_id = uuid4()
    repository.menu_item = _menu_item(template_id=template_id)
    repository.reward_template = _points_reward_template(template_id)
    service = AdminService(repository=cast(AdminRepository, repository))
    actor = _actor()
    first_key = str(uuid4())

    with pytest.raises(AppError) as conflict:
        await service.delete_menu_item(
            actor=actor,
            item_id=repository.menu_item.id,
            idempotency_key=first_key,
        )
    assert conflict.value.status_code == 409
    assert conflict.value.code == "menu_item_not_archived"
    assert repository.deleted_menu_items == []

    repository.menu_item.archived_at = NOW
    delete_key = str(uuid4())
    await service.delete_menu_item(
        actor=actor,
        item_id=repository.menu_item.id,
        idempotency_key=delete_key,
    )

    assert repository.reward_template.is_active is False
    assert repository.deleted_menu_items == [repository.menu_item]
    delete_audit = next(
        item
        for item in repository.added
        if isinstance(item, AuditEvent) and item.event_type == "menu.item_deleted"
    )
    assert delete_audit.severity is AuditSeverity.WARNING
    assert delete_audit.idempotency_key == delete_key
    assert delete_audit.event_metadata["name"] == "Капучино"
    assert len(delete_audit.event_metadata["request_hash"]) == 64

    await service.delete_menu_item(
        actor=actor,
        item_id=repository.menu_item.id,
        idempotency_key=delete_key,
    )
    assert repository.deleted_menu_items == [repository.menu_item]

    with pytest.raises(AppError) as reused_key:
        await service.delete_menu_item(
            actor=_actor(),
            item_id=repository.menu_item.id,
            idempotency_key=delete_key,
        )
    assert reused_key.value.code == "idempotency_conflict"


@pytest.mark.asyncio
async def test_current_loyalty_reward_blocks_menu_item_archive_and_delete() -> None:
    repository = RecordingAdminRepository()
    repository.menu_item = _menu_item()
    repository.current_loyalty_reward_programs = frozenset(
        {LoyaltyProgram.VISITS, LoyaltyProgram.STAMPS}
    )
    service = AdminService(repository=cast(AdminRepository, repository))

    with pytest.raises(AppError) as archive_conflict:
        await service.hide_menu_item(actor=_actor(), item_id=repository.menu_item.id, now=NOW)
    assert archive_conflict.value.status_code == 409
    assert archive_conflict.value.code == "menu_item_is_current_loyalty_reward"
    assert "посещений подряд" in archive_conflict.value.message
    assert "штампов" in archive_conflict.value.message
    assert repository.menu_item.archived_at is None
    assert repository.menu_item.is_visible is True
    assert repository.menu_item.is_available is True

    repository.menu_item.archived_at = NOW
    with pytest.raises(AppError) as delete_conflict:
        await service.delete_menu_item(
            actor=_actor(),
            item_id=repository.menu_item.id,
            idempotency_key=str(uuid4()),
        )
    assert delete_conflict.value.code == "menu_item_is_current_loyalty_reward"
    assert repository.deleted_menu_items == []


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


@pytest.mark.asyncio
async def test_media_upload_accepts_browser_mime_aliases_and_rejects_mismatch(
    tmp_path: Path,
) -> None:
    repository = RecordingAdminRepository()
    service = AdminService(repository=cast(AdminRepository, repository))

    jpeg = await service.upload_media(
        actor=_actor(),
        content=b"\xff\xd8\xffcontent",
        original_filename="desktop.jpg",
        claimed_content_type="image/jpg; charset=binary",
        kind="menu",
        media_root=tmp_path,
        now=NOW,
    )
    png = await service.upload_media(
        actor=_actor(),
        content=b"\x89PNG\r\n\x1a\ncontent",
        original_filename="desktop.png",
        claimed_content_type="image/x-png",
        kind="menu",
        media_root=tmp_path,
        now=NOW,
    )

    assert jpeg.media.detected_mime == "image/jpeg"
    assert jpeg.media.attributes["claimed_content_type"] == "image/jpeg"
    assert png.media.detected_mime == "image/png"
    assert png.media.attributes["claimed_content_type"] == "image/png"

    with pytest.raises(AppError) as mismatch:
        await service.upload_media(
            actor=_actor(),
            content=b"\xff\xd8\xffcontent",
            original_filename="spoofed.png",
            claimed_content_type="image/png",
            kind="menu",
            media_root=tmp_path,
            now=NOW,
        )
    assert mismatch.value.status_code == 415
    assert mismatch.value.code == "media_type_mismatch"


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
async def test_promotion_publish_keeps_timestamp_loaded_for_response() -> None:
    repository = RecordingAdminRepository()
    promotion = Promotion(
        id=uuid4(),
        title="Летний напиток",
        body="Попробуйте новинку",
        status=PromotionStatus.DRAFT,
        created_by_staff_id=uuid4(),
    )
    repository.promotion = promotion
    service = AdminService(repository=cast(AdminRepository, repository))

    published = await service.publish_promotion(
        actor=_actor(),
        promotion_id=promotion.id,
        now=NOW,
    )

    assert published.status is PromotionStatus.PUBLISHED
    assert published.published_at == NOW
    assert published.updated_at == NOW


@pytest.mark.asyncio
async def test_archived_promotion_can_be_restored_as_a_draft() -> None:
    repository = RecordingAdminRepository()
    promotion = Promotion(
        id=uuid4(),
        title="Летний напиток",
        body="Попробуйте новинку",
        status=PromotionStatus.ARCHIVED,
        published_at=NOW,
        created_by_staff_id=uuid4(),
    )
    repository.promotion = promotion
    service = AdminService(repository=cast(AdminRepository, repository))

    restored = await service.restore_promotion(
        actor=_actor(),
        promotion_id=promotion.id,
        now=NOW,
    )

    assert restored.status is PromotionStatus.DRAFT
    assert restored.published_at is None
    assert restored.updated_at == NOW
    audit = next(
        item
        for item in repository.added
        if isinstance(item, AuditEvent) and item.event_type == "promotion.restored"
    )
    assert audit.object_id == promotion.id


@pytest.mark.asyncio
async def test_promotion_must_be_archived_before_deletion_and_keeps_audit() -> None:
    repository = RecordingAdminRepository()
    promotion = Promotion(
        id=uuid4(),
        title="Летний напиток",
        body="Попробуйте новинку",
        status=PromotionStatus.DRAFT,
        created_by_staff_id=uuid4(),
    )
    repository.promotion = promotion
    service = AdminService(repository=cast(AdminRepository, repository))

    with pytest.raises(AppError) as conflict:
        await service.delete_promotion(actor=_actor(), promotion_id=promotion.id)
    assert conflict.value.status_code == 409
    assert repository.deleted_promotions == []

    promotion.status = PromotionStatus.ARCHIVED
    await service.delete_promotion(actor=_actor(), promotion_id=promotion.id)

    assert repository.deleted_promotions == [promotion]
    audit = next(
        item
        for item in repository.added
        if isinstance(item, AuditEvent) and item.event_type == "promotion.deleted"
    )
    assert audit.object_id == promotion.id


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


@pytest.mark.asyncio
async def test_staff_update_accepts_customer_creation_permission_override() -> None:
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

    await service.update_staff(
        actor=_actor(),
        staff_id=staff.id,
        updates={"position": "Старший бариста"},
        permissions={PermissionCode.CUSTOMERS_CREATE: True},
        now=NOW,
    )

    assert staff.position == "Старший бариста"
    assert repository.permission_overrides == {PermissionCode.CUSTOMERS_CREATE: True}

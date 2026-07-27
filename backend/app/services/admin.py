"""Admin/content/staff/tip/media use cases and their business invariants."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.access import StaffInvite, StaffMember
from app.models.audit import AuditEvent
from app.models.content import MenuCategory, MenuItem, Promotion
from app.models.enums import (
    AuditSeverity,
    FeedbackStatus,
    LoyaltyProgram,
    MediaStatus,
    PermissionCode,
    PromotionStatus,
    RewardType,
    Role,
    TipProfileStatus,
    UserStatus,
)
from app.models.loyalty import LoyaltySettings, RewardTemplate
from app.models.media import MediaFile
from app.models.staff import StaffTipProfile
from app.repositories.admin import (
    AdminRepository,
    FeedbackPage,
    FeedbackRecord,
    MenuCategoryPage,
    MenuItemPage,
    PromotionPage,
    StaffPage,
    TipProfilePage,
    TipProfileRecord,
)
from app.security.rbac import Actor

MAX_MEDIA_BYTES = 5 * 1024 * 1024
MEDIA_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
STAFF_OVERRIDE_PERMISSIONS = frozenset(
    {
        PermissionCode.CARD_LOOKUP,
        PermissionCode.POINTS_ACCRUE,
        PermissionCode.POINTS_REDEEM,
        PermissionCode.VISITS_MARK,
        PermissionCode.STAMPS_ADD,
        PermissionCode.REWARDS_REDEEM,
        PermissionCode.OWN_OPERATIONS_REVERSE,
        PermissionCode.OWN_TIP_PROFILE_MANAGE,
    }
)
PRIVILEGED_ROLES = frozenset({Role.ADMIN, Role.OWNER})


@dataclass(frozen=True, slots=True)
class RequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


EMPTY_METADATA = RequestMetadata()


@dataclass(frozen=True, slots=True)
class StaffInviteResult:
    invite: StaffInvite
    raw_token: str


@dataclass(frozen=True, slots=True)
class TipProfileView:
    profile_id: UUID | None
    staff_id: UUID
    display_name: str
    position: str
    bio: str
    tip_url: str
    photo_media_id: UUID | None
    tip_qr_media_id: UUID | None
    moderation_status: TipProfileStatus
    published_visible: bool


@dataclass(frozen=True, slots=True)
class MediaUploadResult:
    media: MediaFile
    public_url: str


@dataclass(frozen=True, slots=True)
class MediaDownload:
    path: Path
    media_type: str
    sha256: str
    filename: str


class AdminService:
    def __init__(self, *, repository: AdminRepository) -> None:
        self._repository = repository

    async def get_loyalty_settings(self) -> LoyaltySettings:
        settings = await self._repository.get_loyalty_settings(for_update=False)
        if settings is None:
            _not_found("Loyalty settings are not configured")
        return settings

    async def update_loyalty_settings(
        self,
        *,
        actor: Actor,
        points_enabled: bool,
        currency_name: str,
        rubles_per_point: int,
        redemption_rubles_per_point: int,
        minimum_purchase_minor: int,
        maximum_purchase_minor: int,
        rounding: str,
        max_redemption_percent: int,
        minimum_redemption_points: int,
        welcome_bonus_points: int,
        points_validity_days: int | None,
        daily_accrual_limit_points: int | None,
        operation_accrual_limit_points: int | None,
        large_operation_threshold_minor: int | None,
        large_operation_requires_approval: bool,
        visit_enabled: bool,
        visit_goal: int,
        visits_must_be_consecutive: bool,
        visit_daily_limit: int,
        timezone: str,
        business_day_boundary_minutes: int,
        visit_allowed_misses: int,
        visit_reset_on_miss: bool,
        visit_reward_validity_days: int | None,
        visit_restart_cycle: bool,
        stamps_enabled: bool,
        stamp_goal: int,
        stamps_per_purchase: int,
        stamp_operation_limit: int,
        stamp_reward_validity_days: int | None,
        reset_stamps_after_reward: bool,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> LoyaltySettings:
        from app.models.enums import RoundingMode

        async with self._repository.transaction():
            settings = await self._repository.get_loyalty_settings(for_update=True)
            if settings is None:
                settings = LoyaltySettings(id=uuid4(), singleton_key="default")
                self._repository.add(settings)
            settings.points_enabled = points_enabled
            settings.currency_name = currency_name
            settings.minor_units_per_point = rubles_per_point * 100
            settings.redemption_minor_units_per_point = redemption_rubles_per_point * 100
            settings.minimum_purchase_minor = minimum_purchase_minor
            settings.maximum_purchase_minor = maximum_purchase_minor
            settings.rounding_mode = RoundingMode(rounding)
            settings.maximum_redemption_percent = max_redemption_percent
            settings.minimum_redemption_points = minimum_redemption_points
            settings.welcome_bonus_points = welcome_bonus_points
            settings.points_validity_days = points_validity_days
            settings.daily_accrual_limit_points = daily_accrual_limit_points
            settings.operation_accrual_limit_points = operation_accrual_limit_points
            settings.large_operation_threshold_minor = large_operation_threshold_minor
            settings.large_operation_requires_approval = large_operation_requires_approval
            settings.visits_enabled = visit_enabled
            settings.visit_required_count = visit_goal
            settings.visits_must_be_consecutive = visits_must_be_consecutive
            settings.visit_daily_limit = visit_daily_limit
            settings.timezone = timezone
            settings.business_day_boundary_minutes = business_day_boundary_minutes
            settings.visit_allowed_misses = visit_allowed_misses
            settings.visit_reset_on_miss = visit_reset_on_miss
            settings.visit_reward_validity_days = visit_reward_validity_days
            settings.visit_restart_cycle = visit_restart_cycle
            settings.stamps_enabled = stamps_enabled
            settings.stamp_required_count = stamp_goal
            settings.stamps_per_purchase = stamps_per_purchase
            settings.stamp_operation_limit = stamp_operation_limit
            settings.stamp_reward_validity_days = stamp_reward_validity_days
            settings.reset_stamps_after_reward = reset_stamps_after_reward
            settings.updated_by_staff_id = actor.staff_member_id
            self._audit(
                actor=actor,
                event_type="loyalty.settings_updated",
                object_type="loyalty_settings",
                object_id=settings.id,
                event_metadata={
                    "points_enabled": points_enabled,
                    "visits_enabled": visit_enabled,
                    "stamps_enabled": stamps_enabled,
                },
                metadata=metadata,
            )
            await self._repository.flush()
            return settings

    async def list_menu_categories(
        self,
        *,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> MenuCategoryPage:
        return await self._repository.list_menu_categories(
            page=page,
            page_size=page_size,
            include_archived=include_archived,
        )

    async def create_menu_category(
        self,
        *,
        actor: Actor,
        name: str,
        description: str | None,
        icon_media_id: UUID | None,
        sort_order: int,
        visible: bool,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> MenuCategory:
        category = MenuCategory(
            id=uuid4(),
            name=name,
            description=description,
            icon_media_id=icon_media_id,
            sort_order=sort_order,
            is_visible=visible,
        )
        async with self._repository.transaction():
            await self._require_media(icon_media_id)
            self._repository.add(category)
            self._audit(
                actor=actor,
                event_type="menu.category_created",
                object_type="menu_category",
                object_id=category.id,
                event_metadata={"name": name, "visible": visible},
                metadata=metadata,
            )
            await self._repository.flush()
        return category

    async def update_menu_category(
        self,
        *,
        actor: Actor,
        category_id: UUID,
        updates: Mapping[str, Any],
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> MenuCategory:
        allowed = {"name", "description", "icon_media_id", "sort_order", "visible"}
        _require_update_keys(updates, allowed)
        async with self._repository.transaction():
            category = await self._repository.get_menu_category(category_id, for_update=True)
            if category is None:
                _not_found("Menu category was not found")
            if category.archived_at is not None:
                _conflict("archived_content", "Archived menu category cannot be changed")
            if "icon_media_id" in updates:
                await self._require_media(updates["icon_media_id"])
            for key, value in updates.items():
                setattr(category, "is_visible" if key == "visible" else key, value)
            self._audit(
                actor=actor,
                event_type="menu.category_updated",
                object_type="menu_category",
                object_id=category.id,
                event_metadata={"changed_fields": sorted(updates)},
                metadata=metadata,
            )
            await self._repository.flush()
            return category

    async def hide_menu_category(
        self,
        *,
        actor: Actor,
        category_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> MenuCategory:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            category = await self._repository.get_menu_category(category_id, for_update=True)
            if category is None:
                _not_found("Menu category was not found")
            category.is_visible = False
            category.archived_at = category.archived_at or current_time
            self._audit(
                actor=actor,
                event_type="menu.category_hidden",
                object_type="menu_category",
                object_id=category.id,
                event_metadata={},
                metadata=metadata,
            )
            await self._repository.flush()
            return category

    async def list_menu_items(
        self,
        *,
        category_id: UUID | None,
        page: int,
        page_size: int,
        include_archived: bool,
    ) -> MenuItemPage:
        return await self._repository.list_menu_items(
            category_id=category_id,
            page=page,
            page_size=page_size,
            include_archived=include_archived,
        )

    async def create_menu_item(
        self,
        *,
        actor: Actor,
        category_id: UUID,
        name: str,
        description: str | None,
        image_media_id: UUID | None,
        price_minor: int,
        old_price_minor: int | None,
        points_price: int | None,
        composition: str | None,
        volume: str | None,
        labels: list[str],
        available: bool,
        visible: bool,
        sort_order: int,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> MenuItem:
        item = MenuItem(
            id=uuid4(),
            category_id=category_id,
            name=name,
            description=description,
            image_media_id=image_media_id,
            price_minor=price_minor,
            old_price_minor=old_price_minor,
            points_price=points_price,
            composition=composition,
            volume=volume,
            labels=labels,
            is_available=available,
            is_visible=visible,
            sort_order=sort_order,
        )
        async with self._repository.transaction():
            await self._require_category(category_id)
            await self._require_media(image_media_id)
            objects: list[object] = [item]
            if points_price is not None:
                template = self._points_menu_template(item=item, actor=actor)
                item.points_reward_template_id = template.id
                objects.append(template)
            self._repository.add_all(objects)
            self._audit(
                actor=actor,
                event_type="menu.item_created",
                object_type="menu_item",
                object_id=item.id,
                event_metadata={"name": name, "category_id": str(category_id)},
                metadata=metadata,
            )
            await self._repository.flush()
        return item

    async def update_menu_item(
        self,
        *,
        actor: Actor,
        item_id: UUID,
        updates: Mapping[str, Any],
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> MenuItem:
        allowed = {
            "category_id",
            "name",
            "description",
            "image_media_id",
            "price_minor",
            "old_price_minor",
            "points_price",
            "composition",
            "volume",
            "labels",
            "available",
            "visible",
            "sort_order",
        }
        _require_update_keys(updates, allowed)
        async with self._repository.transaction():
            item = await self._repository.get_menu_item(item_id, for_update=True)
            if item is None:
                _not_found("Menu item was not found")
            if item.archived_at is not None:
                _conflict("archived_content", "Archived menu item cannot be changed")
            if "category_id" in updates:
                await self._require_category(updates["category_id"])
            if "image_media_id" in updates:
                await self._require_media(updates["image_media_id"])
            attribute_names = {"available": "is_available", "visible": "is_visible"}
            for key, value in updates.items():
                setattr(item, attribute_names.get(key, key), value)
            await self._sync_points_menu_template(item=item, actor=actor)
            self._audit(
                actor=actor,
                event_type="menu.item_updated",
                object_type="menu_item",
                object_id=item.id,
                event_metadata={"changed_fields": sorted(updates)},
                metadata=metadata,
            )
            await self._repository.flush()
            return item

    def _points_menu_template(self, *, item: MenuItem, actor: Actor) -> RewardTemplate:
        return RewardTemplate(
            id=uuid4(),
            name=item.name,
            description=item.description or f"Награда: {item.name}",
            image_media_id=item.image_media_id,
            reward_type=RewardType.FREE_PRODUCT,
            source_program=LoyaltyProgram.POINTS,
            value_int=item.points_price,
            terms="Покажите QR-код бариста до получения товара.",
            validity_days=30,
            is_active=True,
            created_by_staff_id=actor.staff_member_id,
        )

    async def _sync_points_menu_template(self, *, item: MenuItem, actor: Actor) -> None:
        template = (
            await self._repository.get_reward_template(item.points_reward_template_id)
            if item.points_reward_template_id is not None
            else None
        )
        if item.points_price is None:
            if template is not None:
                template.is_active = False
            return
        if template is None:
            template = self._points_menu_template(item=item, actor=actor)
            item.points_reward_template_id = template.id
            self._repository.add(template)
            return
        template.name = item.name
        template.description = item.description or f"Награда: {item.name}"
        template.image_media_id = item.image_media_id
        template.value_int = item.points_price
        template.is_active = True

    async def hide_menu_item(
        self,
        *,
        actor: Actor,
        item_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> MenuItem:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            item = await self._repository.get_menu_item(item_id, for_update=True)
            if item is None:
                _not_found("Menu item was not found")
            item.is_visible = False
            item.is_available = False
            item.archived_at = item.archived_at or current_time
            self._audit(
                actor=actor,
                event_type="menu.item_hidden",
                object_type="menu_item",
                object_id=item.id,
                event_metadata={},
                metadata=metadata,
            )
            await self._repository.flush()
            return item

    async def list_promotions(
        self,
        *,
        promotion_status: PromotionStatus | None,
        page: int,
        page_size: int,
    ) -> PromotionPage:
        return await self._repository.list_promotions(
            promotion_status=promotion_status,
            page=page,
            page_size=page_size,
        )

    async def create_promotion(
        self,
        *,
        actor: Actor,
        title: str,
        body: str,
        image_media_id: UUID | None,
        button_label: str | None,
        button_url: str | None,
        starts_at: datetime | None,
        ends_at: datetime | None,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> Promotion:
        _validate_window(starts_at, ends_at)
        if actor.staff_member_id is None:
            _forbidden("Staff identity is required")
        promotion = Promotion(
            id=uuid4(),
            title=title,
            body=body,
            image_media_id=image_media_id,
            button_label=button_label,
            button_url=button_url,
            status=PromotionStatus.DRAFT,
            starts_at=starts_at,
            ends_at=ends_at,
            created_by_staff_id=actor.staff_member_id,
        )
        async with self._repository.transaction():
            await self._require_media(image_media_id)
            self._repository.add(promotion)
            self._audit(
                actor=actor,
                event_type="promotion.created",
                object_type="promotion",
                object_id=promotion.id,
                event_metadata={"title": title},
                metadata=metadata,
            )
            await self._repository.flush()
        return promotion

    async def update_promotion(
        self,
        *,
        actor: Actor,
        promotion_id: UUID,
        updates: Mapping[str, Any],
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> Promotion:
        allowed = {
            "title",
            "body",
            "image_media_id",
            "button_label",
            "button_url",
            "starts_at",
            "ends_at",
        }
        _require_update_keys(updates, allowed)
        async with self._repository.transaction():
            promotion = await self._repository.get_promotion(promotion_id, for_update=True)
            if promotion is None:
                _not_found("Promotion was not found")
            if promotion.status is PromotionStatus.ARCHIVED:
                _conflict("archived_content", "Archived promotion cannot be changed")
            starts_at = updates.get("starts_at", promotion.starts_at)
            ends_at = updates.get("ends_at", promotion.ends_at)
            _validate_window(starts_at, ends_at)
            if "image_media_id" in updates:
                await self._require_media(updates["image_media_id"])
            for key, value in updates.items():
                setattr(promotion, key, value)
            self._audit(
                actor=actor,
                event_type="promotion.updated",
                object_type="promotion",
                object_id=promotion.id,
                event_metadata={"changed_fields": sorted(updates)},
                metadata=metadata,
            )
            await self._repository.flush()
            return promotion

    async def publish_promotion(
        self,
        *,
        actor: Actor,
        promotion_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> Promotion:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            promotion = await self._repository.get_promotion(promotion_id, for_update=True)
            if promotion is None:
                _not_found("Promotion was not found")
            if promotion.status is PromotionStatus.ARCHIVED:
                _conflict("archived_content", "Archived promotion cannot be published")
            _validate_window(promotion.starts_at, promotion.ends_at)
            if promotion.ends_at is not None and promotion.ends_at <= current_time:
                _conflict("promotion_window_elapsed", "Promotion end time is in the past")
            promotion.status = PromotionStatus.PUBLISHED
            promotion.published_at = current_time
            self._audit(
                actor=actor,
                event_type="promotion.published",
                object_type="promotion",
                object_id=promotion.id,
                event_metadata={
                    "starts_at": _iso(promotion.starts_at),
                    "ends_at": _iso(promotion.ends_at),
                },
                metadata=metadata,
            )
            await self._repository.flush()
            return promotion

    async def archive_promotion(
        self,
        *,
        actor: Actor,
        promotion_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> Promotion:
        async with self._repository.transaction():
            promotion = await self._repository.get_promotion(promotion_id, for_update=True)
            if promotion is None:
                _not_found("Promotion was not found")
            promotion.status = PromotionStatus.ARCHIVED
            self._audit(
                actor=actor,
                event_type="promotion.archived",
                object_type="promotion",
                object_id=promotion.id,
                event_metadata={},
                metadata=metadata,
            )
            await self._repository.flush()
            return promotion

    async def list_feedback(
        self,
        *,
        feedback_status: FeedbackStatus | None,
        page: int,
        page_size: int,
    ) -> FeedbackPage:
        return await self._repository.list_feedback(
            feedback_status=feedback_status,
            page=page,
            page_size=page_size,
        )

    async def update_feedback(
        self,
        *,
        actor: Actor,
        feedback_id: UUID,
        feedback_status: FeedbackStatus,
        internal_note: str | None,
        assigned_to_staff_id: UUID | None,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> FeedbackRecord:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            record = await self._repository.get_feedback(feedback_id, for_update=True)
            if record is None:
                _not_found("Feedback was not found")
            if assigned_to_staff_id is not None:
                assignee = await self._repository.get_staff(
                    assigned_to_staff_id,
                    for_update=False,
                )
                if assignee is None or not assignee.is_active:
                    _conflict("invalid_feedback_assignee", "Feedback assignee is unavailable")
            previous_status = record.feedback.status
            record.feedback.status = feedback_status
            record.feedback.internal_note = internal_note
            record.feedback.assigned_to_staff_id = assigned_to_staff_id
            record.feedback.resolved_at = (
                current_time if feedback_status is FeedbackStatus.RESOLVED else None
            )
            self._audit(
                actor=actor,
                event_type="feedback.updated",
                subject_user_id=record.feedback.user_id,
                object_type="feedback",
                object_id=record.feedback.id,
                event_metadata={
                    "previous_status": previous_status.value,
                    "status": feedback_status.value,
                    "assigned_to_staff_id": (
                        str(assigned_to_staff_id) if assigned_to_staff_id else None
                    ),
                },
                metadata=metadata,
            )
            await self._repository.flush()
            return record

    async def delete_feedback(
        self,
        *,
        actor: Actor,
        feedback_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> None:
        async with self._repository.transaction():
            record = await self._repository.get_feedback(feedback_id, for_update=True)
            if record is None:
                _not_found("Feedback was not found")
            if record.feedback.status is not FeedbackStatus.ARCHIVED:
                _conflict(
                    "feedback_not_archived",
                    "Feedback must be archived before permanent deletion",
                )
            self._audit(
                actor=actor,
                event_type="feedback.deleted",
                subject_user_id=record.feedback.user_id,
                object_type="feedback",
                object_id=record.feedback.id,
                event_metadata={
                    "rating": record.feedback.rating,
                    "category": record.feedback.category.value,
                },
                severity=AuditSeverity.WARNING,
                metadata=metadata,
            )
            await self._repository.delete_feedback(record.feedback)
            await self._repository.flush()

    async def list_staff(
        self,
        *,
        role: Role | None,
        active: bool | None,
        query: str | None,
        page: int,
        page_size: int,
    ) -> StaffPage:
        if role is Role.CUSTOMER:
            _validation("staff_role_required", "Customer is not a staff role")
        return await self._repository.list_staff(
            role=role,
            active=active,
            query=query,
            page=page,
            page_size=page_size,
        )

    async def create_staff(
        self,
        *,
        actor: Actor,
        user_id: UUID,
        role: Role,
        display_name: str | None,
        position: str | None,
        bio: str | None,
        can_edit_tip_profile: bool,
        permissions: Mapping[PermissionCode, bool],
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> StaffMember:
        self._validate_role_assignment(actor, current_role=None, new_role=role)
        self._validate_permission_overrides(role, permissions)
        current_time = _aware_now(now)
        async with self._repository.transaction():
            user = await self._repository.get_user_for_staff_creation(user_id)
            if user is None or user.status in {UserStatus.INACTIVE, UserStatus.ANONYMIZED}:
                _not_found("User was not found")
            existing = await self._repository.get_staff_by_user(user_id, for_update=True)
            if existing is not None:
                if existing.archived_at is None:
                    _conflict("staff_exists", "User already has a staff profile")
                existing.role = role
                existing.display_name = display_name
                existing.position = position
                existing.bio = bio
                existing.is_active = True
                existing.can_edit_tip_profile = can_edit_tip_profile
                existing.disabled_at = None
                existing.archived_at = None
                existing.updated_at = current_time
                self._repository.replace_staff_permissions(existing, dict(permissions))
                self._audit(
                    actor=actor,
                    event_type="staff.restored",
                    subject_user_id=user_id,
                    object_type="staff_member",
                    object_id=existing.id,
                    event_metadata={"role": role.value},
                    metadata=metadata,
                )
                await self._repository.flush()
                return existing
            staff = StaffMember(
                id=uuid4(),
                user_id=user_id,
                user=user,
                role=role,
                display_name=display_name,
                position=position,
                bio=bio,
                is_active=True,
                can_edit_tip_profile=can_edit_tip_profile,
                permissions=[],
            )
            self._repository.add(staff)
            await self._repository.flush()
            self._repository.replace_staff_permissions(staff, dict(permissions))
            self._audit(
                actor=actor,
                event_type="staff.created",
                subject_user_id=user_id,
                object_type="staff_member",
                object_id=staff.id,
                event_metadata={"role": role.value},
                metadata=metadata,
            )
            await self._repository.flush()
            return staff

    async def update_staff(
        self,
        *,
        actor: Actor,
        staff_id: UUID,
        updates: Mapping[str, Any],
        permissions: Mapping[PermissionCode, bool] | None,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> StaffMember:
        allowed = {"display_name", "position", "bio", "can_edit_tip_profile", "is_active"}
        _require_update_keys(updates, allowed)
        current_time = _aware_now(now)
        async with self._repository.transaction():
            locked = await self._repository.lock_staff_management(staff_id)
            if locked is None:
                _not_found("Staff member was not found")
            staff = locked.target
            if staff.archived_at is not None:
                _not_found("Staff member was not found")
            self._validate_role_assignment(actor, current_role=staff.role, new_role=staff.role)
            if permissions is not None:
                self._validate_permission_overrides(staff.role, permissions)
            activating = updates.get("is_active")
            if activating is False and staff.is_active:
                self._guard_last_owner(staff, locked.active_owner_count)
            for key, value in updates.items():
                setattr(staff, key, value)
            if activating is False:
                staff.disabled_at = current_time
                await self._repository.revoke_user_sessions(
                    user_id=staff.user_id,
                    now=current_time,
                    reason="staff_disabled",
                )
            elif activating is True:
                staff.disabled_at = None
            if permissions is not None:
                self._repository.replace_staff_permissions(staff, dict(permissions))
            staff.updated_at = current_time
            self._audit(
                actor=actor,
                event_type="staff.updated",
                subject_user_id=staff.user_id,
                object_type="staff_member",
                object_id=staff.id,
                event_metadata={
                    "changed_fields": sorted(
                        [*updates, *(["permissions"] if permissions is not None else [])]
                    )
                },
                metadata=metadata,
            )
            await self._repository.flush()
            return staff

    async def change_staff_role(
        self,
        *,
        actor: Actor,
        staff_id: UUID,
        new_role: Role,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> StaffMember:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            locked = await self._repository.lock_staff_management(staff_id)
            if locked is None:
                _not_found("Staff member was not found")
            staff = locked.target
            if staff.archived_at is not None:
                _not_found("Staff member was not found")
            self._validate_role_assignment(actor, current_role=staff.role, new_role=new_role)
            if staff.role is Role.OWNER and new_role is not Role.OWNER and staff.is_active:
                self._guard_last_owner(staff, locked.active_owner_count)
            old_role = staff.role
            staff.role = new_role
            if new_role is not Role.STAFF:
                self._repository.replace_staff_permissions(staff, {})
            staff.updated_at = current_time
            self._audit(
                actor=actor,
                event_type="staff.role_changed",
                subject_user_id=staff.user_id,
                object_type="staff_member",
                object_id=staff.id,
                event_metadata={"previous_role": old_role.value, "role": new_role.value},
                severity=AuditSeverity.WARNING,
                metadata=metadata,
            )
            await self._repository.flush()
            return staff

    async def archive_staff(
        self,
        *,
        actor: Actor,
        staff_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> None:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            locked = await self._repository.lock_staff_management(staff_id)
            if locked is None:
                _not_found("Staff member was not found")
            staff = locked.target
            if staff.archived_at is not None:
                return
            self._validate_role_assignment(actor, current_role=staff.role, new_role=staff.role)
            if staff.user_id == actor.user_id:
                _conflict("self_staff_archive", "You cannot delete your own staff profile")
            if staff.role is Role.OWNER and staff.is_active:
                self._guard_last_owner(staff, locked.active_owner_count)
            staff.is_active = False
            staff.disabled_at = current_time
            staff.archived_at = current_time
            revoked = await self._repository.revoke_user_sessions(
                user_id=staff.user_id,
                now=current_time,
                reason="staff_archived",
            )
            self._audit(
                actor=actor,
                event_type="staff.archived",
                subject_user_id=staff.user_id,
                object_type="staff_member",
                object_id=staff.id,
                event_metadata={"revoked_sessions": revoked},
                severity=AuditSeverity.WARNING,
                metadata=metadata,
            )
            await self._repository.flush()

    async def revoke_staff_sessions(
        self,
        *,
        actor: Actor,
        staff_id: UUID,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> int:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            staff = await self._repository.get_staff(staff_id, for_update=True)
            if staff is None:
                _not_found("Staff member was not found")
            if staff.archived_at is not None:
                _not_found("Staff member was not found")
            self._validate_role_assignment(actor, current_role=staff.role, new_role=staff.role)
            revoked = await self._repository.revoke_user_sessions(
                user_id=staff.user_id,
                now=current_time,
                reason="admin_staff_session_revoke",
            )
            self._audit(
                actor=actor,
                event_type="staff.sessions_revoked",
                subject_user_id=staff.user_id,
                object_type="staff_member",
                object_id=staff.id,
                event_metadata={"revoked_sessions": revoked},
                severity=AuditSeverity.WARNING,
                metadata=metadata,
            )
            return revoked

    async def create_staff_invite(
        self,
        *,
        actor: Actor,
        role: Role,
        target_telegram_id: int | None,
        expires_in_minutes: int,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> StaffInviteResult:
        self._validate_role_assignment(actor, current_role=None, new_role=role)
        if actor.staff_member_id is None:
            _forbidden("Staff identity is required")
        current_time = _aware_now(now)
        raw_token = "cbi_" + secrets.token_urlsafe(32)
        invite = StaffInvite(
            id=uuid4(),
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            target_telegram_id=target_telegram_id,
            role=role,
            invited_by_staff_id=actor.staff_member_id,
            expires_at=current_time + timedelta(minutes=expires_in_minutes),
        )
        async with self._repository.transaction():
            if target_telegram_id is not None:
                await self._repository.revoke_open_invites_for_target(
                    target_telegram_id=target_telegram_id,
                    now=current_time,
                )
            self._repository.add(invite)
            self._audit(
                actor=actor,
                event_type="staff.invite_created",
                object_type="staff_invite",
                object_id=invite.id,
                event_metadata={
                    "role": role.value,
                    "target_telegram_id": target_telegram_id,
                    "expires_at": invite.expires_at.isoformat(),
                },
                metadata=metadata,
            )
            await self._repository.flush()
        return StaffInviteResult(invite=invite, raw_token=raw_token)

    async def get_own_tip_profile(self, *, actor: Actor) -> TipProfileView:
        staff_id = self._require_staff_actor(actor)
        record = await self._repository.get_tip_profile_for_staff(staff_id, for_update=False)
        if record is not None:
            return _tip_profile_view(record)
        staff = await self._repository.get_staff_for_tip_profile(staff_id, for_update=False)
        if staff is None or not staff.is_active:
            _forbidden("Staff profile is unavailable")
        return TipProfileView(
            profile_id=None,
            staff_id=staff.id,
            display_name=staff.display_name or staff.user.first_name,
            position=staff.position or "",
            bio="",
            tip_url="",
            photo_media_id=None,
            tip_qr_media_id=None,
            moderation_status=TipProfileStatus.DRAFT,
            published_visible=False,
        )

    async def update_own_tip_profile(
        self,
        *,
        actor: Actor,
        display_name: str,
        position: str,
        bio: str,
        tip_url: str,
        photo_media_id: UUID | None,
        tip_qr_media_id: UUID | None,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> TipProfileView:
        staff_id = self._require_staff_actor(actor)
        current_time = _aware_now(now)
        async with self._repository.transaction():
            staff = await self._repository.get_staff_for_tip_profile(staff_id, for_update=True)
            if staff is None or not staff.is_active or not staff.can_edit_tip_profile:
                _forbidden("Tip profile editing is unavailable")
            if position != (staff.position or ""):
                _conflict(
                    "tip_position_not_moderated",
                    "Position cannot be changed through the moderated tip profile",
                )
            await self._require_media(photo_media_id)
            await self._require_media(tip_qr_media_id)
            record = await self._repository.get_tip_profile_for_staff(staff_id, for_update=True)
            if record is None:
                profile = StaffTipProfile(
                    id=uuid4(),
                    staff_member_id=staff_id,
                    status=TipProfileStatus.DRAFT,
                    is_visible=False,
                )
                self._repository.add(profile)
            else:
                profile = record.profile
            profile.pending_name = display_name
            profile.pending_bio = bio or None
            profile.pending_tip_url = tip_url or None
            profile.pending_photo_media_id = photo_media_id
            profile.pending_tip_qr_media_id = tip_qr_media_id
            profile.status = TipProfileStatus.PENDING_REVIEW
            profile.submitted_at = current_time
            profile.reviewed_at = None
            profile.reviewed_by_staff_id = None
            profile.moderation_note = None
            self._audit(
                actor=actor,
                event_type="tip_profile.submitted",
                subject_user_id=staff.user_id,
                object_type="staff_tip_profile",
                object_id=profile.id,
                event_metadata={
                    "has_tip_url": bool(tip_url),
                    "has_photo": photo_media_id is not None,
                    "has_tip_qr": tip_qr_media_id is not None,
                },
                metadata=metadata,
            )
            await self._repository.flush()
            refreshed = await self._repository.get_tip_profile_for_staff(
                staff_id,
                for_update=False,
            )
            if refreshed is None:
                raise RuntimeError("Tip profile was not persisted")
            return _tip_profile_view(refreshed)

    async def list_pending_tip_profiles(self, *, page: int, page_size: int) -> TipProfilePage:
        return await self._repository.list_pending_tip_profiles(page=page, page_size=page_size)

    async def cancel_own_tip_profile_review(
        self,
        *,
        actor: Actor,
        metadata: RequestMetadata = EMPTY_METADATA,
    ) -> TipProfileView:
        staff_id = self._require_staff_actor(actor)
        async with self._repository.transaction():
            record = await self._repository.get_tip_profile_for_staff(staff_id, for_update=True)
            if record is None or record.profile.status is not TipProfileStatus.PENDING_REVIEW:
                _conflict("tip_profile_not_pending", "Профиль не ожидает модерации")
            profile = record.profile
            profile.pending_name = None
            profile.pending_bio = None
            profile.pending_tip_url = None
            profile.pending_photo_media_id = None
            profile.pending_tip_qr_media_id = None
            profile.submitted_at = None
            profile.status = (
                TipProfileStatus.APPROVED if profile.published_name else TipProfileStatus.DRAFT
            )
            if profile.status is TipProfileStatus.DRAFT:
                profile.is_visible = False
            self._audit(
                actor=actor,
                event_type="tip_profile.review_cancelled",
                subject_user_id=record.staff.user_id,
                object_type="staff_tip_profile",
                object_id=profile.id,
                event_metadata={},
                metadata=metadata,
            )
            await self._repository.flush()
            return _tip_profile_view(record)

    async def approve_tip_profile(
        self,
        *,
        actor: Actor,
        profile_id: UUID,
        moderation_note: str | None,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> TipProfileRecord:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            record = await self._repository.get_tip_profile(profile_id, for_update=True)
            if record is None:
                _not_found("Tip profile was not found")
            profile = record.profile
            if profile.status is not TipProfileStatus.PENDING_REVIEW:
                _conflict("tip_profile_not_pending", "Tip profile is not awaiting review")
            if not profile.pending_name:
                _conflict("tip_profile_incomplete", "Pending profile name is required")
            profile.published_name = profile.pending_name
            profile.published_bio = profile.pending_bio
            profile.published_tip_url = profile.pending_tip_url
            profile.published_photo_media_id = profile.pending_photo_media_id
            profile.published_tip_qr_media_id = profile.pending_tip_qr_media_id
            profile.pending_name = None
            profile.pending_bio = None
            profile.pending_tip_url = None
            profile.pending_photo_media_id = None
            profile.pending_tip_qr_media_id = None
            profile.status = TipProfileStatus.APPROVED
            profile.is_visible = True
            profile.reviewed_at = current_time
            profile.reviewed_by_staff_id = actor.staff_member_id
            profile.moderation_note = moderation_note
            self._audit(
                actor=actor,
                event_type="tip_profile.approved",
                subject_user_id=record.staff.user_id,
                object_type="staff_tip_profile",
                object_id=profile.id,
                event_metadata={},
                metadata=metadata,
            )
            await self._repository.flush()
            return record

    async def hide_tip_profile(
        self,
        *,
        actor: Actor,
        profile_id: UUID,
        moderation_note: str | None,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> TipProfileRecord:
        current_time = _aware_now(now)
        async with self._repository.transaction():
            record = await self._repository.get_tip_profile(profile_id, for_update=True)
            if record is None:
                _not_found("Tip profile was not found")
            record.profile.status = TipProfileStatus.HIDDEN
            record.profile.is_visible = False
            record.profile.reviewed_at = current_time
            record.profile.reviewed_by_staff_id = actor.staff_member_id
            record.profile.moderation_note = moderation_note
            self._audit(
                actor=actor,
                event_type="tip_profile.hidden",
                subject_user_id=record.staff.user_id,
                object_type="staff_tip_profile",
                object_id=record.profile.id,
                event_metadata={},
                metadata=metadata,
            )
            await self._repository.flush()
            return record

    async def upload_media(
        self,
        *,
        actor: Actor,
        content: bytes,
        original_filename: str | None,
        claimed_content_type: str | None,
        kind: str,
        media_root: Path,
        metadata: RequestMetadata = EMPTY_METADATA,
        now: datetime | None = None,
    ) -> MediaUploadResult:
        if not content:
            _validation("empty_media", "Uploaded image is empty")
        if len(content) > MAX_MEDIA_BYTES:
            raise AppError(
                code="media_too_large",
                message="Uploaded image exceeds 5 MiB",
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            )
        detected_mime = detect_image_mime(content)
        normalized_claim = (claimed_content_type or "").split(";", 1)[0].strip().lower()
        if normalized_claim not in {"", "application/octet-stream", detected_mime}:
            raise AppError(
                code="media_type_mismatch",
                message="Declared and detected image types do not match",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        current_time = _aware_now(now)
        media_id = uuid4()
        extension = MEDIA_EXTENSIONS[detected_mime]
        storage_key = PurePosixPath(
            "uploads",
            f"{current_time.year:04d}",
            f"{current_time.month:02d}",
            f"{secrets.token_hex(24)}{extension}",
        ).as_posix()
        destination = await asyncio.to_thread(_safe_media_path, media_root, storage_key, False)
        if destination is None:
            raise RuntimeError("Generated media path is unavailable")
        await asyncio.to_thread(_atomic_write, destination, content)
        media = MediaFile(
            id=media_id,
            storage_key=storage_key,
            original_filename=safe_original_filename(original_filename),
            detected_mime=detected_mime,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            kind=kind,
            status=MediaStatus.ACTIVE,
            uploaded_by_user_id=actor.user_id,
            attributes={"claimed_content_type": normalized_claim or None},
        )
        try:
            async with self._repository.transaction():
                self._repository.add(media)
                self._audit(
                    actor=actor,
                    event_type="media.uploaded",
                    object_type="media_file",
                    object_id=media.id,
                    event_metadata={
                        "kind": kind,
                        "detected_mime": detected_mime,
                        "byte_size": len(content),
                    },
                    metadata=metadata,
                )
                await self._repository.flush()
        except BaseException:
            await asyncio.to_thread(_unlink_if_exists, destination)
            raise
        return MediaUploadResult(media=media, public_url=f"/api/v1/media/{media.id}")

    async def get_media_download(self, *, media_id: UUID, media_root: Path) -> MediaDownload:
        media = await self._repository.get_media(media_id, active_only=True)
        if media is None:
            _not_found("Media file was not found")
        candidate = await asyncio.to_thread(
            _safe_media_path,
            media_root,
            media.storage_key,
            True,
        )
        if candidate is None:
            _not_found("Media file was not found")
        extension = MEDIA_EXTENSIONS.get(media.detected_mime)
        if extension is None:
            _not_found("Media file was not found")
        return MediaDownload(
            path=candidate,
            media_type=media.detected_mime,
            sha256=media.sha256,
            filename=f"{media.id}{extension}",
        )

    async def _require_category(self, category_id: UUID) -> MenuCategory:
        category = await self._repository.get_menu_category(category_id, for_update=False)
        if category is None or category.archived_at is not None:
            _conflict("invalid_menu_category", "Menu category is unavailable")
        return category

    async def _require_media(self, media_id: UUID | None) -> MediaFile | None:
        if media_id is None:
            return None
        media = await self._repository.get_media(media_id, active_only=True)
        if media is None:
            _conflict("invalid_media", "Referenced media is unavailable")
        return media

    @staticmethod
    def _validate_permission_overrides(
        role: Role,
        permissions: Mapping[PermissionCode, bool],
    ) -> None:
        if role is not Role.STAFF and permissions:
            _validation(
                "role_permissions_derived",
                "Admin and owner permissions are derived from their role",
            )
        unsupported = set(permissions) - STAFF_OVERRIDE_PERMISSIONS
        if unsupported:
            _validation(
                "invalid_staff_permission",
                "Only operational staff permissions may be overridden",
            )

    @staticmethod
    def _validate_role_assignment(
        actor: Actor,
        *,
        current_role: Role | None,
        new_role: Role,
    ) -> None:
        if new_role is Role.CUSTOMER:
            _validation("staff_role_required", "Customer is not a staff role")
        if (
            current_role in PRIVILEGED_ROLES or new_role in PRIVILEGED_ROLES
        ) and actor.role is not Role.OWNER:
            _forbidden("Only an owner may manage admin or owner roles")

    @staticmethod
    def _guard_last_owner(staff: StaffMember, active_owner_count: int) -> None:
        if staff.role is Role.OWNER and staff.is_active and active_owner_count <= 1:
            _conflict("last_owner", "The last active owner cannot be demoted or disabled")

    @staticmethod
    def _require_staff_actor(actor: Actor) -> UUID:
        if actor.staff_member_id is None:
            _forbidden("Staff identity is required")
        return actor.staff_member_id

    def _audit(
        self,
        *,
        actor: Actor,
        event_type: str,
        object_type: str,
        object_id: UUID,
        event_metadata: dict[str, Any],
        metadata: RequestMetadata,
        subject_user_id: UUID | None = None,
        severity: AuditSeverity = AuditSeverity.INFO,
    ) -> None:
        self._repository.add(
            AuditEvent(
                id=uuid4(),
                event_type=event_type,
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                subject_user_id=subject_user_id,
                object_type=object_type,
                object_id=object_id,
                event_metadata=event_metadata,
                severity=severity,
                is_suspicious=False,
                ip_address=_truncate(metadata.ip_address, 45),
                user_agent=_truncate(metadata.user_agent, 512),
            )
        )


def detect_image_mime(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        declared_size = int.from_bytes(content[4:8], "little") + 8
        if declared_size > len(content):
            _unsupported_media()
        return "image/webp"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    _unsupported_media()


def safe_original_filename(value: str | None) -> str | None:
    if not value:
        return None
    basename = PurePosixPath(value.replace("\\", "/")).name
    cleaned = "".join(
        character for character in basename if character.isprintable() and character != "\x00"
    )
    cleaned = cleaned.strip().strip(".")[:255]
    return cleaned or None


def _atomic_write(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o640)
        os.replace(temporary, destination)
        destination.chmod(0o640)
    finally:
        _unlink_if_exists(temporary)


def _safe_media_path(root_path: Path, storage_key: str, require_file: bool) -> Path | None:
    root = root_path.resolve()
    candidate = (root / storage_key).resolve()
    if not candidate.is_relative_to(root):
        if require_file:
            return None
        raise RuntimeError("Generated media path escaped MEDIA_ROOT")
    if require_file and not candidate.is_file():
        return None
    return candidate


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _tip_profile_view(record: TipProfileRecord) -> TipProfileView:
    profile = record.profile
    use_pending = profile.status is TipProfileStatus.PENDING_REVIEW
    return TipProfileView(
        profile_id=profile.id,
        staff_id=record.staff.id,
        display_name=(profile.pending_name if use_pending else profile.published_name)
        or record.staff.display_name
        or record.user.first_name,
        position=record.staff.position or "",
        bio=(profile.pending_bio if use_pending else profile.published_bio) or "",
        tip_url=(profile.pending_tip_url if use_pending else profile.published_tip_url) or "",
        photo_media_id=(
            profile.pending_photo_media_id if use_pending else profile.published_photo_media_id
        ),
        tip_qr_media_id=(
            profile.pending_tip_qr_media_id if use_pending else profile.published_tip_qr_media_id
        ),
        moderation_status=profile.status,
        published_visible=profile.is_visible,
    )


def _validate_window(starts_at: datetime | None, ends_at: datetime | None) -> None:
    for value in (starts_at, ends_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            _validation("timezone_required", "Promotion timestamps must include a timezone")
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        _validation("invalid_promotion_window", "Promotion end time must be after start time")


def _require_update_keys(updates: Mapping[str, Any], allowed: set[str]) -> None:
    if not updates:
        _validation("empty_update", "At least one field must be supplied")
    if set(updates) - allowed:
        _validation("invalid_update_fields", "Unsupported update fields were supplied")


def _aware_now(value: datetime | None) -> datetime:
    current_time = value or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current_time


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _truncate(value: str | None, maximum: int) -> str | None:
    return None if value is None else value[:maximum]


def _unsupported_media() -> NoReturn:
    raise AppError(
        code="unsupported_media_type",
        message="Only JPEG, PNG, and WebP images are allowed",
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    )


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _not_found(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.NOT_FOUND,
        message=message,
        status_code=status.HTTP_404_NOT_FOUND,
    )


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _forbidden(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.FORBIDDEN,
        message=message,
        status_code=status.HTTP_403_FORBIDDEN,
    )

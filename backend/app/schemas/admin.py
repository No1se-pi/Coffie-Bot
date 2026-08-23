"""Strict API contracts for admin content, staff, tips, feedback, and media."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.access import StaffMember
from app.models.content import MenuCategory, MenuItem, Promotion
from app.models.enums import (
    FeedbackCategory,
    FeedbackStatus,
    PermissionCode,
    PromotionStatus,
    RewardType,
    Role,
    RoundingMode,
    TipProfileStatus,
)
from app.models.loyalty import LoyaltySettings, RewardTemplate
from app.repositories.admin import (
    FeedbackPage,
    MenuCategoryPage,
    MenuItemPage,
    PromotionPage,
    StaffPage,
    TipProfilePage,
    TipProfileRecord,
)
from app.services.admin import MediaUploadResult, StaffInviteResult, TipProfileView


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MenuItemLoyaltyRewardConfig(ApiSchema):
    kind: Literal["menu_item"]
    menu_item_id: UUID


class CustomLoyaltyRewardConfig(ApiSchema):
    kind: Literal["custom"]
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8_000)


class PointsLoyaltyRewardConfig(ApiSchema):
    kind: Literal["points"]
    points: int = Field(gt=0, le=1_000_000_000)


LoyaltyRewardConfig = Annotated[
    MenuItemLoyaltyRewardConfig | CustomLoyaltyRewardConfig | PointsLoyaltyRewardConfig,
    Field(discriminator="kind"),
]


class LoyaltySettingsResponse(ApiSchema):
    points_enabled: bool
    currency_name: str
    rubles_per_point: int
    redemption_rubles_per_point: int
    minimum_purchase_minor: int
    maximum_purchase_minor: int
    rounding: RoundingMode
    max_redemption_percent: int
    minimum_redemption_points: int
    welcome_bonus_points: int
    points_validity_days: int | None
    daily_accrual_limit_points: int | None
    operation_accrual_limit_points: int | None
    large_operation_threshold_minor: int | None
    large_operation_requires_approval: bool
    visit_enabled: bool
    visit_goal: int
    visits_must_be_consecutive: bool
    visit_daily_limit: int
    timezone: str
    business_day_boundary: str
    visit_allowed_misses: int
    visit_reset_on_miss: bool
    visit_reward_validity_days: int | None
    visit_restart_cycle: bool
    visit_reward: LoyaltyRewardConfig | None = None
    stamps_enabled: bool
    stamp_goal: int
    stamps_per_purchase: int
    stamp_operation_limit: int
    stamp_reward_validity_days: int | None
    reset_stamps_after_reward: bool
    stamp_reward: LoyaltyRewardConfig | None = None

    @field_validator("business_day_boundary")
    @classmethod
    def validate_boundary(cls, value: str) -> str:
        boundary_minutes(value)
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("unknown timezone") from exc
        return value


class LoyaltySettingsUpdate(LoyaltySettingsResponse):
    currency_name: str = Field(min_length=1, max_length=64)
    rubles_per_point: int = Field(ge=1, le=1_000_000)
    redemption_rubles_per_point: int = Field(ge=1, le=1_000_000)
    minimum_purchase_minor: int = Field(ge=0, le=1_000_000_000)
    maximum_purchase_minor: int = Field(gt=0, le=1_000_000_000)
    max_redemption_percent: int = Field(ge=0, le=100)
    minimum_redemption_points: int = Field(ge=0, le=1_000_000_000)
    welcome_bonus_points: int = Field(ge=0, le=1_000_000_000)
    points_validity_days: int | None = Field(default=None, gt=0, le=3_650)
    daily_accrual_limit_points: int | None = Field(default=None, gt=0)
    operation_accrual_limit_points: int | None = Field(default=None, gt=0)
    large_operation_threshold_minor: int | None = Field(default=None, gt=0)
    visit_goal: int = Field(ge=1, le=365)
    visit_daily_limit: int = Field(ge=1, le=100)
    timezone: str = Field(min_length=1, max_length=64)
    visit_allowed_misses: int = Field(ge=0, le=365)
    visit_reward_validity_days: int | None = Field(default=None, gt=0, le=3_650)
    stamp_goal: int = Field(ge=1, le=1_000)
    stamps_per_purchase: int = Field(ge=1, le=100)
    stamp_operation_limit: int = Field(ge=1, le=100)
    stamp_reward_validity_days: int | None = Field(default=None, gt=0, le=3_650)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.maximum_purchase_minor < self.minimum_purchase_minor:
            raise ValueError("maximum purchase must not be below minimum purchase")
        if self.large_operation_requires_approval and self.large_operation_threshold_minor is None:
            raise ValueError("approval threshold is required when approval is enabled")
        return self


class MenuCategoryResponse(ApiSchema):
    id: UUID
    name: str
    description: str | None
    icon_media_id: UUID | None
    icon_url: str | None
    sort_order: int
    visible: bool
    archived_at: datetime | None


class MenuCategoryListResponse(ApiSchema):
    items: list[MenuCategoryResponse]
    page: int
    page_size: int
    total: int


class MenuCategoryCreate(ApiSchema):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    icon_media_id: UUID | None = None
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)
    visible: bool = True


class MenuCategoryUpdate(ApiSchema):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    icon_media_id: UUID | None = None
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)
    visible: bool | None = None


class MenuItemResponse(ApiSchema):
    id: UUID
    category_id: UUID
    name: str
    description: str | None
    image_media_id: UUID | None
    image_url: str | None
    price_minor: int
    old_price_minor: int | None
    points_price: int | None
    composition: str | None
    volume: str | None
    labels: list[str]
    available: bool
    visible: bool
    sort_order: int
    archived_at: datetime | None


class MenuItemListResponse(ApiSchema):
    items: list[MenuItemResponse]
    page: int
    page_size: int
    total: int


class MenuItemCreate(ApiSchema):
    category_id: UUID
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8_000)
    image_media_id: UUID | None = None
    price_minor: int = Field(ge=0, le=1_000_000_000)
    old_price_minor: int | None = Field(default=None, ge=0, le=1_000_000_000)
    points_price: int | None = Field(default=None, gt=0, le=1_000_000_000)
    composition: str | None = Field(default=None, max_length=8_000)
    volume: str | None = Field(default=None, max_length=80)
    labels: list[str] = Field(default_factory=list, max_length=20)
    available: bool = True
    visible: bool = True
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[str]) -> list[str]:
        normalized = [label.strip() for label in value if label.strip()]
        if any(len(label) > 64 for label in normalized):
            raise ValueError("labels must be at most 64 characters")
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_prices(self) -> Self:
        if self.old_price_minor is not None and self.old_price_minor <= self.price_minor:
            raise ValueError("old_price_minor must exceed price_minor")
        return self


class MenuItemUpdate(ApiSchema):
    category_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=8_000)
    image_media_id: UUID | None = None
    price_minor: int | None = Field(default=None, ge=0, le=1_000_000_000)
    old_price_minor: int | None = Field(default=None, ge=0, le=1_000_000_000)
    points_price: int | None = Field(default=None, gt=0, le=1_000_000_000)
    composition: str | None = Field(default=None, max_length=8_000)
    volume: str | None = Field(default=None, max_length=80)
    labels: list[str] | None = Field(default=None, max_length=20)
    available: bool | None = None
    visible: bool | None = None
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else MenuItemCreate.normalize_labels(value)


class PromotionResponse(ApiSchema):
    id: UUID
    title: str
    text: str
    image_media_id: UUID | None
    image_url: str | None
    button_label: str | None
    button_url: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    status: PromotionStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PromotionListResponse(ApiSchema):
    items: list[PromotionResponse]
    page: int
    page_size: int
    total: int


class PromotionCreate(ApiSchema):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20_000)
    image_media_id: UUID | None = None
    button_label: str | None = Field(default=None, max_length=80)
    button_url: str | None = Field(default=None, max_length=2_048)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("button_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return optional_http_url(value)

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        promotion_window(self.starts_at, self.ends_at)
        return self


class PromotionUpdate(ApiSchema):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=20_000)
    image_media_id: UUID | None = None
    button_label: str | None = Field(default=None, max_length=80)
    button_url: str | None = Field(default=None, max_length=2_048)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("button_url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        return optional_http_url(value)


class FeedbackAdminResponse(ApiSchema):
    id: UUID
    user_id: UUID
    user_display_name: str
    rating: int
    category: FeedbackCategory
    message: str
    may_contact: bool
    status: FeedbackStatus
    assigned_to_staff_id: UUID | None
    internal_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class FeedbackListResponse(ApiSchema):
    items: list[FeedbackAdminResponse]
    page: int
    page_size: int
    total: int


class FeedbackUpdate(ApiSchema):
    status: FeedbackStatus
    internal_note: str | None = Field(default=None, max_length=4_000)
    assigned_to_staff_id: UUID | None = None


class PermissionOverride(ApiSchema):
    permission: PermissionCode
    allowed: bool


class StaffResponse(ApiSchema):
    id: UUID
    user_id: UUID
    telegram_id: int | None
    username: str | None
    display_name: str
    position: str | None
    bio: str | None
    role: Role
    is_active: bool
    can_edit_tip_profile: bool
    permissions: list[PermissionOverride]
    created_at: datetime
    updated_at: datetime


class StaffListResponse(ApiSchema):
    items: list[StaffResponse]
    page: int
    page_size: int
    total: int


class StaffCreate(ApiSchema):
    user_id: UUID
    role: Role = Role.STAFF
    display_name: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)
    bio: str | None = Field(default=None, max_length=8_000)
    can_edit_tip_profile: bool = True
    permissions: dict[PermissionCode, bool] = Field(default_factory=dict)


class StaffUpdate(ApiSchema):
    display_name: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)
    bio: str | None = Field(default=None, max_length=8_000)
    can_edit_tip_profile: bool | None = None
    is_active: bool | None = None
    permissions: dict[PermissionCode, bool] | None = None


class StaffRoleUpdate(ApiSchema):
    role: Role


class StaffInviteCreate(ApiSchema):
    role: Role = Role.STAFF
    target_telegram_id: int | None = Field(default=None, gt=0)
    expires_in_minutes: int = Field(default=1_440, ge=5, le=10_080)


class StaffInviteResponse(ApiSchema):
    id: UUID
    token: str
    role: Role
    target_telegram_id: int | None
    expires_at: datetime


class SessionsRevokedResponse(ApiSchema):
    revoked_sessions: int


class TipProfileUpdate(ApiSchema):
    display_name: str = Field(min_length=1, max_length=128)
    position: str = Field(max_length=128)
    bio: str = Field(default="", max_length=8_000)
    tip_url: str = Field(default="", max_length=2_048)
    tip_qr_url: str | None = None
    moderation_status: TipProfileStatus | None = None
    photo_media_id: UUID | None = None
    tip_qr_media_id: UUID | None = None

    @field_validator("tip_url")
    @classmethod
    def validate_tip_url(cls, value: str) -> str:
        return optional_http_url(value) or ""


class TipProfileResponse(ApiSchema):
    id: UUID | None
    display_name: str
    position: str
    bio: str
    tip_url: str
    photo_url: str | None
    tip_qr_url: str | None
    photo_media_id: UUID | None
    tip_qr_media_id: UUID | None
    moderation_status: TipProfileStatus
    published_visible: bool


class PendingTipProfileResponse(ApiSchema):
    id: UUID
    staff_id: UUID
    user_id: UUID
    staff_display_name: str
    position: str | None
    pending_name: str | None
    pending_bio: str | None
    pending_tip_url: str | None
    pending_photo_media_id: UUID | None
    pending_tip_qr_media_id: UUID | None
    published_name: str | None
    published_bio: str | None
    published_tip_url: str | None
    status: TipProfileStatus
    submitted_at: datetime | None


class PendingTipProfileListResponse(ApiSchema):
    items: list[PendingTipProfileResponse]
    page: int
    page_size: int
    total: int


class TipModerationRequest(ApiSchema):
    moderation_note: str | None = Field(default=None, max_length=2_000)


class MediaUploadResponse(ApiSchema):
    id: UUID
    url: str
    original_filename: str | None
    detected_mime: str
    byte_size: int
    sha256: str
    kind: str
    created_at: datetime


def loyalty_settings_response(
    settings: LoyaltySettings,
    *,
    visit_reward_template: RewardTemplate | None = None,
    stamp_reward_template: RewardTemplate | None = None,
) -> LoyaltySettingsResponse:
    return LoyaltySettingsResponse(
        points_enabled=settings.points_enabled,
        currency_name=settings.currency_name,
        rubles_per_point=max(1, settings.minor_units_per_point // 100),
        redemption_rubles_per_point=max(
            1, (settings.redemption_minor_units_per_point or 100) // 100
        ),
        minimum_purchase_minor=settings.minimum_purchase_minor,
        maximum_purchase_minor=settings.maximum_purchase_minor or 1_000_000,
        rounding=settings.rounding_mode,
        max_redemption_percent=settings.maximum_redemption_percent,
        minimum_redemption_points=settings.minimum_redemption_points or 0,
        welcome_bonus_points=settings.welcome_bonus_points or 0,
        points_validity_days=settings.points_validity_days,
        daily_accrual_limit_points=settings.daily_accrual_limit_points,
        operation_accrual_limit_points=settings.operation_accrual_limit_points,
        large_operation_threshold_minor=settings.large_operation_threshold_minor,
        large_operation_requires_approval=settings.large_operation_requires_approval or False,
        visit_enabled=settings.visits_enabled,
        visit_goal=settings.visit_required_count,
        visits_must_be_consecutive=settings.visits_must_be_consecutive is not False,
        visit_daily_limit=settings.visit_daily_limit or 1,
        timezone=settings.timezone,
        business_day_boundary=boundary_string(settings.business_day_boundary_minutes),
        visit_allowed_misses=settings.visit_allowed_misses or 0,
        visit_reset_on_miss=settings.visit_reset_on_miss is not False,
        visit_reward_validity_days=settings.visit_reward_validity_days,
        visit_restart_cycle=settings.visit_restart_cycle is not False,
        visit_reward=_loyalty_reward_config(visit_reward_template),
        stamps_enabled=settings.stamps_enabled,
        stamp_goal=settings.stamp_required_count,
        stamps_per_purchase=settings.stamps_per_purchase or 1,
        stamp_operation_limit=settings.stamp_operation_limit or 1,
        stamp_reward_validity_days=settings.stamp_reward_validity_days,
        reset_stamps_after_reward=settings.reset_stamps_after_reward is not False,
        stamp_reward=_loyalty_reward_config(stamp_reward_template),
    )


def _loyalty_reward_config(template: RewardTemplate | None) -> LoyaltyRewardConfig | None:
    if template is None:
        return None
    if template.source_menu_item_id is not None:
        return MenuItemLoyaltyRewardConfig(
            kind="menu_item",
            menu_item_id=template.source_menu_item_id,
        )
    if template.reward_type is RewardType.POINTS:
        return PointsLoyaltyRewardConfig(
            kind="points",
            points=template.value_int or 0,
        )
    return CustomLoyaltyRewardConfig(
        kind="custom",
        name=template.name,
        description=template.description,
    )


def menu_category_response(item: MenuCategory) -> MenuCategoryResponse:
    return MenuCategoryResponse(
        id=item.id,
        name=item.name,
        description=item.description,
        icon_media_id=item.icon_media_id,
        icon_url=media_url(item.icon_media_id),
        sort_order=item.sort_order,
        visible=item.is_visible,
        archived_at=item.archived_at,
    )


def menu_category_list_response(
    result: MenuCategoryPage, *, page: int, page_size: int
) -> MenuCategoryListResponse:
    return MenuCategoryListResponse(
        items=[menu_category_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


def menu_item_response(item: MenuItem) -> MenuItemResponse:
    return MenuItemResponse(
        id=item.id,
        category_id=item.category_id,
        name=item.name,
        description=item.description,
        image_media_id=item.image_media_id,
        image_url=media_url(item.image_media_id),
        price_minor=item.price_minor,
        old_price_minor=item.old_price_minor,
        points_price=item.points_price,
        composition=item.composition,
        volume=item.volume,
        labels=item.labels,
        available=item.is_available,
        visible=item.is_visible,
        sort_order=item.sort_order,
        archived_at=item.archived_at,
    )


def menu_item_list_response(
    result: MenuItemPage, *, page: int, page_size: int
) -> MenuItemListResponse:
    return MenuItemListResponse(
        items=[menu_item_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


def promotion_response(item: Promotion) -> PromotionResponse:
    return PromotionResponse(
        id=item.id,
        title=item.title,
        text=item.body,
        image_media_id=item.image_media_id,
        image_url=media_url(item.image_media_id),
        button_label=item.button_label,
        button_url=item.button_url,
        starts_at=item.starts_at,
        ends_at=item.ends_at,
        status=item.status,
        published_at=item.published_at,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def promotion_list_response(
    result: PromotionPage, *, page: int, page_size: int
) -> PromotionListResponse:
    return PromotionListResponse(
        items=[promotion_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


def feedback_list_response(
    result: FeedbackPage, *, page: int, page_size: int
) -> FeedbackListResponse:
    return FeedbackListResponse(
        items=[feedback_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


def feedback_response(record: Any) -> FeedbackAdminResponse:
    feedback = record.feedback
    user = record.user
    return FeedbackAdminResponse(
        id=feedback.id,
        user_id=user.id,
        user_display_name=" ".join(value for value in (user.first_name, user.last_name) if value),
        rating=feedback.rating,
        category=feedback.category,
        message=feedback.message,
        may_contact=feedback.may_contact,
        status=feedback.status,
        assigned_to_staff_id=feedback.assigned_to_staff_id,
        internal_note=feedback.internal_note,
        resolved_at=feedback.resolved_at,
        created_at=feedback.created_at,
    )


def staff_response(item: StaffMember) -> StaffResponse:
    user = item.user
    return StaffResponse(
        id=item.id,
        user_id=item.user_id,
        telegram_id=user.telegram_id,
        username=user.username,
        display_name=item.display_name or user.first_name,
        position=item.position,
        bio=item.bio,
        role=item.role,
        is_active=item.is_active,
        can_edit_tip_profile=item.can_edit_tip_profile,
        permissions=[
            PermissionOverride(permission=value.permission, allowed=value.allowed)
            for value in sorted(item.permissions, key=lambda value: value.permission.value)
        ],
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def staff_list_response(result: StaffPage, *, page: int, page_size: int) -> StaffListResponse:
    return StaffListResponse(
        items=[staff_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


def staff_invite_response(result: StaffInviteResult) -> StaffInviteResponse:
    invite = result.invite
    return StaffInviteResponse(
        id=invite.id,
        token=result.raw_token,
        role=invite.role,
        target_telegram_id=invite.target_telegram_id,
        expires_at=invite.expires_at,
    )


def tip_profile_response(view: TipProfileView) -> TipProfileResponse:
    return TipProfileResponse(
        id=view.profile_id,
        display_name=view.display_name,
        position=view.position,
        bio=view.bio,
        tip_url=view.tip_url,
        photo_url=media_url(view.photo_media_id),
        tip_qr_url=media_url(view.tip_qr_media_id),
        photo_media_id=view.photo_media_id,
        tip_qr_media_id=view.tip_qr_media_id,
        moderation_status=view.moderation_status,
        published_visible=view.published_visible,
    )


def pending_tip_profile_response(record: TipProfileRecord) -> PendingTipProfileResponse:
    profile = record.profile
    return PendingTipProfileResponse(
        id=profile.id,
        staff_id=record.staff.id,
        user_id=record.user.id,
        staff_display_name=record.staff.display_name or record.user.first_name,
        position=record.staff.position,
        pending_name=profile.pending_name,
        pending_bio=profile.pending_bio,
        pending_tip_url=profile.pending_tip_url,
        pending_photo_media_id=profile.pending_photo_media_id,
        pending_tip_qr_media_id=profile.pending_tip_qr_media_id,
        published_name=profile.published_name,
        published_bio=profile.published_bio,
        published_tip_url=profile.published_tip_url,
        status=profile.status,
        submitted_at=profile.submitted_at,
    )


def pending_tip_profile_list_response(
    result: TipProfilePage, *, page: int, page_size: int
) -> PendingTipProfileListResponse:
    return PendingTipProfileListResponse(
        items=[pending_tip_profile_response(item) for item in result.items],
        page=page,
        page_size=page_size,
        total=result.total,
    )


def media_upload_response(result: MediaUploadResult) -> MediaUploadResponse:
    item = result.media
    return MediaUploadResponse(
        id=item.id,
        url=result.public_url,
        original_filename=item.original_filename,
        detected_mime=item.detected_mime,
        byte_size=item.byte_size,
        sha256=item.sha256,
        kind=item.kind,
        created_at=item.created_at,
    )


def media_url(media_id: UUID | None) -> str | None:
    return None if media_id is None else f"/api/v1/media/{media_id}"


def boundary_minutes(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("business_day_boundary must be HH:MM")
    hour, minute = (int(part) for part in parts)
    if hour > 23 or minute > 59:
        raise ValueError("business_day_boundary must be HH:MM")
    return hour * 60 + minute


def boundary_string(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def promotion_window(starts_at: datetime | None, ends_at: datetime | None) -> None:
    for value in (starts_at, ends_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("promotion timestamps must include timezone")
    if starts_at is not None and ends_at is not None and ends_at <= starts_at:
        raise ValueError("ends_at must be after starts_at")


def optional_http_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.lower().startswith(("https://", "http://")):
        raise ValueError("URL must use http or https")
    return normalized

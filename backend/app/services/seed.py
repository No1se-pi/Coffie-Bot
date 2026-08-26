"""Validated, idempotent installation seed orchestration."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import AppEnvironment
from app.models.enums import (
    LoyaltyProgram,
    PermissionCode,
    PromotionActionType,
    PromotionStatus,
    RewardType,
    Role,
    RoundingMode,
    WalletMode,
)


class SeedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstallationSeed(SeedModel):
    mode: Literal["single_organization"] = "single_organization"
    timezone: str = Field(min_length=1, max_length=64)
    currency_code: str = Field(min_length=3, max_length=8)
    currency_minor_unit: int = Field(ge=0, le=6)


class BrandSeed(SeedModel):
    name: str = Field(min_length=1, max_length=160)
    short_name: str = Field(min_length=1, max_length=80)
    description: str | None = None
    welcome_text: str = Field(min_length=1, max_length=2_000)
    loyalty_currency_name: str = Field(min_length=1, max_length=64)
    primary_color: str
    secondary_color: str
    background_color: str
    logo_media_key: str | None = None
    hero_media_key: str | None = None


class ContactsSeed(SeedModel):
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    telegram: str | None = None
    support_contact: str | None = None
    privacy_policy_url: str | None = None
    privacy_policy_text: str | None = None


class VenueSeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    phone: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    website: str | None = Field(default=None, max_length=2_048)
    telegram: str | None = Field(default=None, max_length=2_048)
    logo_media_key: str | None = None
    loyalty_points_enabled: bool = True
    accrual_basis_points: int = Field(default=1_000, ge=0, le=10_000)
    loyalty_rounding_mode: RoundingMode = RoundingMode.FLOOR
    is_active: bool = True
    sort_order: int = 0


class LocationSeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    venue_slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
    )
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    address: str = Field(min_length=1)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str = Field(min_length=1, max_length=64)
    business_day_boundary: str = "00:00"
    phone: str | None = None
    map_url: str | None = None
    opening_hours: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0


class PointsSeed(SeedModel):
    enabled: bool = True
    minor_units_per_point: int = Field(gt=0)
    redemption_minor_units_per_point: int = Field(default=100, gt=0)
    minimum_purchase_minor: int = Field(default=0, ge=0)
    maximum_purchase_minor: int = Field(default=1_000_000, gt=0)
    rounding: RoundingMode = RoundingMode.FLOOR
    maximum_redemption_percent: int = Field(default=50, ge=0, le=100)
    minimum_redemption_points: int = Field(default=1, ge=0)
    welcome_bonus_points: int = Field(default=0, ge=0)
    expiry_days: int | None = Field(default=None, gt=0)
    expiry_months: int = Field(default=6, gt=0, le=120)
    expiry_reminder_days: int = Field(default=14, ge=0, le=365)
    wallet_mode: WalletMode = WalletMode.SHARED
    default_bonus_venue_slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9-]{0,63}$",
    )
    daily_accrual_limit_points: int | None = Field(default=None, gt=0)
    per_operation_limit_points: int | None = Field(default=None, gt=0)
    approval_threshold_minor: int | None = Field(default=None, gt=0)


class VisitsSeed(SeedModel):
    enabled: bool = True
    required_visits: int = Field(gt=0)
    consecutive_days: bool = True
    visits_per_business_day: int = Field(default=1, gt=0)
    business_day_boundary: str = "00:00"
    allowed_missed_days: int = Field(default=0, ge=0)
    reset_after_miss: bool = True
    reward_template_slug: str | None = None
    reward_validity_days: int | None = Field(default=None, gt=0)
    restart_cycle_after_reward: bool = True


class StampsSeed(SeedModel):
    enabled: bool = True
    required_paid_items: int = Field(gt=0)
    stamps_per_purchase: int = Field(default=1, gt=0)
    per_operation_limit: int = Field(default=1, gt=0)
    reward_template_slug: str | None = None
    reward_validity_days: int | None = Field(default=None, gt=0)
    reset_after_reward: bool = True


class BirthdaySeed(SeedModel):
    enabled: bool = True
    discount_percent: int = Field(default=10, ge=0, le=100)
    window_days: int = Field(default=1, ge=1, le=31)
    stackable: bool = False
    eligible_venue_slugs: list[str] = Field(default_factory=list)


class LoyaltySeed(SeedModel):
    points: PointsSeed
    visits: VisitsSeed
    stamps: StampsSeed
    birthday: BirthdaySeed = Field(default_factory=BirthdaySeed)


class RewardTemplateSeed(SeedModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    reward_type: RewardType = Field(alias="type")
    discount_percent: int | None = Field(default=None, ge=0, le=100)
    value_int: int | None = Field(default=None, ge=0)
    terms: str | None = None
    validity_days: int | None = Field(default=None, gt=0)
    image_media_key: str | None = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_percentage_value(self) -> RewardTemplateSeed:
        if self.reward_type == RewardType.PERCENT_DISCOUNT and self.discount_percent is None:
            raise ValueError("discount_percent is required for a percent discount")
        if self.reward_type == RewardType.POINTS and (
            self.value_int is None or self.value_int <= 0
        ):
            raise ValueError("value_int must be positive for a points reward")
        return self


class MenuCategorySeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    venue_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class MenuItemSeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    category_slug: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    price_minor: int = Field(ge=0)
    old_price_minor: int | None = Field(default=None, ge=0)
    composition: str | None = None
    volume: str | None = None
    labels: list[str] = Field(default_factory=list)
    image_media_key: str | None = None
    sort_order: int = 0
    is_active: bool = True


class ModifierOptionSeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    price_delta_minor: int = Field(default=0, ge=0)
    allows_quantity: bool = False
    max_quantity: int = Field(default=1, ge=1, le=100)
    is_enabled: bool = True
    sort_order: int = 0


class ModifierGroupSeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    venue_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4_000)
    min_selections: int = Field(default=0, ge=0, le=100)
    max_selections: int = Field(default=1, ge=0, le=100)
    required: bool = False
    sort_order: int = 0
    is_enabled: bool = True
    applicable_item_slugs: list[str] = Field(default_factory=list)
    options: list[ModifierOptionSeed] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_range(self) -> ModifierGroupSeed:
        if self.max_selections < self.min_selections:
            raise ValueError("modifier max selections must not be below minimum")
        if self.required and self.min_selections == 0:
            raise ValueError("required modifier group must select at least one option")
        return self


class MenuSeed(SeedModel):
    categories: list[MenuCategorySeed] = Field(default_factory=list)
    items: list[MenuItemSeed] = Field(default_factory=list)
    modifier_groups: list[ModifierGroupSeed] = Field(default_factory=list)


class PromotionSeed(SeedModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    venue_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = None
    body: str = Field(min_length=1)
    image_media_key: str | None = None
    button_label: str | None = None
    button_url: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: PromotionStatus = PromotionStatus.DRAFT
    pricing_enabled: bool = False
    action_type: PromotionActionType | None = None
    discount_value: int | None = Field(default=None, gt=0)
    priority: int = Field(default=0, ge=-100_000, le=100_000)
    stackable: bool = False
    active_from_date: date | None = None
    active_to_date: date | None = None
    active_weekdays: list[int] = Field(default_factory=list)
    active_time_from: time | None = None
    active_time_to: time | None = None
    fulfillment_modes: list[Literal["pickup", "delivery"]] = Field(default_factory=list)
    customer_birthday_only: bool = False
    minimum_order_minor: int = Field(default=0, ge=0)
    category_slugs: list[str] = Field(default_factory=list)
    menu_item_slugs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_window(self) -> PromotionSeed:
        if self.starts_at is not None and self.ends_at is not None:
            if self.ends_at <= self.starts_at:
                raise ValueError("promotion ends_at must be after starts_at")
        if self.pricing_enabled and (self.action_type is None or self.discount_value is None):
            raise ValueError("pricing promotion requires action_type and discount_value")
        if (
            self.action_type == PromotionActionType.PERCENT_DISCOUNT
            and self.discount_value is not None
            and self.discount_value > 10_000
        ):
            raise ValueError("percent discount basis points must not exceed 10000")
        if any(day < 0 or day > 6 for day in self.active_weekdays):
            raise ValueError("active weekdays must use 0..6")
        if (
            self.active_from_date is not None
            and self.active_to_date is not None
            and self.active_to_date < self.active_from_date
        ):
            raise ValueError("pricing active_to_date must not precede active_from_date")
        return self


class DevelopmentStaffSeed(SeedModel):
    telegram_id: int = Field(gt=0)
    display_name: str = Field(min_length=1, max_length=128)
    role: Role
    permissions: set[PermissionCode] = Field(default_factory=set)
    is_active: bool = True
    synthetic: Literal[True]

    @model_validator(mode="after")
    def reject_owner(self) -> DevelopmentStaffSeed:
        if self.role in {Role.CUSTOMER, Role.OWNER}:
            raise ValueError("development seed staff role must be staff or admin")
        return self


class DevelopmentOnlySeed(SeedModel):
    staff_members: list[DevelopmentStaffSeed] = Field(default_factory=list)


class SeedDocument(SeedModel):
    schema_version: Literal[1]
    installation: InstallationSeed
    brand: BrandSeed
    contacts: ContactsSeed
    # Optional for schema-v1 compatibility.  A missing collection preserves
    # the Venue assignment already present in an upgraded installation.
    venues: list[VenueSeed] = Field(default_factory=list)
    locations: list[LocationSeed] = Field(default_factory=list)
    loyalty: LoyaltySeed
    reward_templates: list[RewardTemplateSeed] = Field(default_factory=list)
    menu: MenuSeed
    promotions: list[PromotionSeed] = Field(default_factory=list)
    development_only: DevelopmentOnlySeed = Field(default_factory=DevelopmentOnlySeed)

    @model_validator(mode="after")
    def validate_references(self) -> SeedDocument:
        venue_slugs = [item.slug for item in self.venues]
        _unique(venue_slugs, "venue slug")
        venue_set = set(venue_slugs)
        _unique([item.slug for item in self.locations], "location slug")
        for location in self.locations:
            if location.venue_slug is not None and location.venue_slug not in venue_set:
                raise ValueError(f"unknown venue slug: {location.venue_slug}")
        if (
            venue_set
            and self.loyalty.points.default_bonus_venue_slug is not None
            and self.loyalty.points.default_bonus_venue_slug not in venue_set
        ):
            raise ValueError("unknown default bonus venue slug")
        _unique(self.loyalty.birthday.eligible_venue_slugs, "birthday venue slug")
        for venue_slug in self.loyalty.birthday.eligible_venue_slugs:
            if venue_set and venue_slug not in venue_set:
                raise ValueError(f"unknown birthday venue slug: {venue_slug}")
        reward_slugs = [item.slug for item in self.reward_templates]
        _unique(reward_slugs, "reward template slug")
        reward_set = set(reward_slugs)
        for reference in (
            self.loyalty.visits.reward_template_slug,
            self.loyalty.stamps.reward_template_slug,
        ):
            if reference is not None and reference not in reward_set:
                raise ValueError(f"unknown reward template slug: {reference}")
        category_slugs = [item.slug for item in self.menu.categories]
        _unique(category_slugs, "menu category slug")
        category_set = set(category_slugs)
        _unique([item.slug for item in self.menu.items], "menu item slug")
        category_venues = {item.slug: item.venue_slug for item in self.menu.categories}
        for category in self.menu.categories:
            if venue_set and category.venue_slug not in venue_set:
                raise ValueError(f"unknown menu category venue slug: {category.venue_slug}")
        for item in self.menu.items:
            if item.category_slug not in category_set:
                raise ValueError(f"unknown menu category slug: {item.category_slug}")
        item_slugs = {item.slug for item in self.menu.items}
        item_venues = {item.slug: category_venues[item.category_slug] for item in self.menu.items}
        _unique([group.slug for group in self.menu.modifier_groups], "modifier group slug")
        for group in self.menu.modifier_groups:
            if venue_set and group.venue_slug not in venue_set:
                raise ValueError(f"unknown modifier venue slug: {group.venue_slug}")
            _unique([option.slug for option in group.options], "modifier option slug")
            for item_slug in group.applicable_item_slugs:
                if item_slug not in item_slugs:
                    raise ValueError(f"unknown modifier menu item slug: {item_slug}")
                if item_venues[item_slug] != group.venue_slug:
                    raise ValueError("modifier item belongs to another venue")
        _unique([item.slug for item in self.promotions], "promotion slug")
        for promotion in self.promotions:
            if venue_set and promotion.venue_slug not in venue_set:
                raise ValueError(f"unknown promotion venue slug: {promotion.venue_slug}")
            for slug in promotion.category_slugs:
                if slug not in category_set:
                    raise ValueError(f"unknown promotion category slug: {slug}")
                if category_venues[slug] != promotion.venue_slug:
                    raise ValueError("promotion category belongs to another venue")
            for slug in promotion.menu_item_slugs:
                if slug not in item_slugs:
                    raise ValueError(f"unknown promotion menu item slug: {slug}")
                if item_venues[slug] != promotion.venue_slug:
                    raise ValueError("promotion menu item belongs to another venue")
        if sum(location.is_default for location in self.locations) > 1:
            raise ValueError("only one location may be the default")
        return self

    @classmethod
    def from_file(cls, path: Path) -> SeedDocument:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class SeedRepositoryPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def acquire_lock(self) -> None: ...

    async def lock_existing_loyalty_settings(self) -> None: ...

    async def load_seed_entity_ids(self) -> dict[str, UUID]: ...

    async def save_seed_entity_ids(self, values: dict[str, UUID]) -> None: ...

    async def upsert_app_setting(self, key: str, value: Any, *, is_public: bool) -> None: ...

    async def upsert_venue(
        self,
        entity_id: UUID,
        slug: str,
        values: dict[str, Any],
    ) -> UUID: ...

    async def upsert_location(self, slug: str, values: dict[str, Any]) -> UUID: ...

    async def find_media_id(self, storage_key: str | None) -> UUID | None: ...

    async def upsert_reward_template(self, entity_id: UUID, values: dict[str, Any]) -> UUID: ...

    async def upsert_loyalty_settings(self, values: dict[str, Any]) -> UUID: ...

    async def replace_birthday_promotion_venues(
        self,
        settings_id: UUID,
        venue_ids: list[UUID],
    ) -> None: ...

    async def upsert_menu_category(self, entity_id: UUID, values: dict[str, Any]) -> UUID: ...

    async def upsert_menu_item(self, entity_id: UUID, values: dict[str, Any]) -> UUID: ...

    async def upsert_modifier_group(self, entity_id: UUID, values: dict[str, Any]) -> UUID: ...

    async def upsert_modifier_option(self, entity_id: UUID, values: dict[str, Any]) -> UUID: ...

    async def replace_modifier_group_items(
        self,
        group_id: UUID,
        *,
        venue_id: UUID,
        item_ids: list[UUID],
        sort_order: int,
    ) -> None: ...

    async def upsert_promotion(self, entity_id: UUID, values: dict[str, Any]) -> UUID: ...

    async def replace_promotion_targets(
        self,
        promotion_id: UUID,
        *,
        venue_id: UUID,
        category_ids: list[UUID],
        menu_item_ids: list[UUID],
    ) -> None: ...

    async def find_active_staff_id(self) -> UUID | None: ...

    async def upsert_seed_staff(
        self,
        *,
        telegram_id: int,
        display_name: str,
        role: Role,
        permissions: set[PermissionCode],
        is_active: bool,
    ) -> UUID: ...

    async def export_configuration(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SeedReport:
    venues: int
    locations: int
    reward_templates: int
    menu_categories: int
    menu_items: int
    promotions: int
    development_staff: int


class SeedConfigurationError(RuntimeError):
    pass


class SeedService:
    def __init__(self, repository: SeedRepositoryPort) -> None:
        self._repository = repository

    async def apply(
        self,
        document: SeedDocument,
        *,
        environment: AppEnvironment,
        now: datetime | None = None,
    ) -> SeedReport:
        current_time = now or datetime.now(UTC)
        async with self._repository.transaction():
            await self._repository.acquire_lock()
            # Live seed reruns and owner wallet-mode changes touch both the
            # singleton settings row and venues.  Take the shared global lock
            # order (settings -> venues) before any venue upsert to avoid a
            # settings/venue deadlock under concurrent administration.
            await self._repository.lock_existing_loyalty_settings()
            entity_ids = await self._repository.load_seed_entity_ids()
            await self._repository.upsert_app_setting(
                "installation",
                document.installation.model_dump(mode="json"),
                is_public=True,
            )
            await self._repository.upsert_app_setting(
                "brand", document.brand.model_dump(mode="json"), is_public=True
            )
            await self._repository.upsert_app_setting(
                "contacts", document.contacts.model_dump(mode="json"), is_public=True
            )

            venue_ids: dict[str, UUID] = {}
            for venue in document.venues:
                entity_key = f"venue:{venue.slug}"
                entity_id = _stable_id(entity_ids, entity_key)
                persisted_id = await self._repository.upsert_venue(
                    entity_id,
                    venue.slug,
                    {
                        "name": venue.name,
                        "description": venue.description,
                        "phone": venue.phone,
                        "email": venue.email,
                        "website": venue.website,
                        "telegram": venue.telegram,
                        "logo_media_id": await self._repository.find_media_id(venue.logo_media_key),
                        "loyalty_points_enabled": venue.loyalty_points_enabled,
                        "loyalty_accrual_basis_points": venue.accrual_basis_points,
                        "loyalty_rounding_mode": venue.loyalty_rounding_mode,
                        "is_active": venue.is_active,
                        "sort_order": venue.sort_order,
                        "archived_at": None if venue.is_active else current_time,
                    },
                )
                # If an administrator created the same slug before the first
                # seed run, adopt that row instead of fighting its unique key.
                entity_ids[entity_key] = persisted_id
                venue_ids[venue.slug] = persisted_id

            for location in document.locations:
                values: dict[str, Any] = {
                    "name": location.name,
                    "description": location.description,
                    "address": location.address,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "timezone": location.timezone,
                    "business_day_boundary_minutes": _boundary_minutes(
                        location.business_day_boundary
                    ),
                    "phone": location.phone,
                    "map_url": location.map_url,
                    "opening_hours": location.opening_hours,
                    "is_default": location.is_default,
                    "is_active": location.is_active,
                    "sort_order": location.sort_order,
                }
                if location.venue_slug is not None:
                    values["venue_id"] = venue_ids[location.venue_slug]
                await self._repository.upsert_location(
                    location.slug,
                    values,
                )

            development_staff = 0
            if environment == AppEnvironment.DEVELOPMENT:
                for staff in document.development_only.staff_members:
                    await self._repository.upsert_seed_staff(
                        telegram_id=staff.telegram_id,
                        display_name=staff.display_name,
                        role=staff.role,
                        permissions=staff.permissions,
                        is_active=staff.is_active,
                    )
                    development_staff += 1

            creator_id = await self._repository.find_active_staff_id()
            reward_ids: dict[str, UUID] = {}
            for template in document.reward_templates:
                entity_id = _stable_id(entity_ids, f"reward:{template.slug}")
                source_program = _reward_source(document, template.slug)
                reward_ids[template.slug] = await self._repository.upsert_reward_template(
                    entity_id,
                    {
                        "name": template.name,
                        "description": template.description,
                        "image_media_id": await self._repository.find_media_id(
                            template.image_media_key
                        ),
                        "reward_type": template.reward_type,
                        "source_program": source_program,
                        "value_int": template.discount_percent
                        if template.reward_type == RewardType.PERCENT_DISCOUNT
                        else template.value_int,
                        "terms": template.terms,
                        "validity_days": template.validity_days,
                        "is_active": template.is_active,
                        "created_by_staff_id": creator_id,
                    },
                )

            points = document.loyalty.points
            visits = document.loyalty.visits
            stamps = document.loyalty.stamps
            birthday = document.loyalty.birthday
            settings_id = await self._repository.upsert_loyalty_settings(
                {
                    "currency_name": document.brand.loyalty_currency_name,
                    "currency_code": document.installation.currency_code,
                    "points_enabled": points.enabled,
                    "minor_units_per_point": points.minor_units_per_point,
                    "redemption_minor_units_per_point": (points.redemption_minor_units_per_point),
                    "minimum_purchase_minor": points.minimum_purchase_minor,
                    "maximum_purchase_minor": points.maximum_purchase_minor,
                    "rounding_mode": points.rounding,
                    "maximum_redemption_percent": points.maximum_redemption_percent,
                    "minimum_redemption_points": points.minimum_redemption_points,
                    "welcome_bonus_points": points.welcome_bonus_points,
                    "points_validity_days": points.expiry_days,
                    "points_expiry_months": points.expiry_months,
                    "expiry_reminder_days": points.expiry_reminder_days,
                    "wallet_mode": points.wallet_mode,
                    "default_bonus_venue_id": (
                        venue_ids[points.default_bonus_venue_slug]
                        if points.default_bonus_venue_slug is not None
                        else None
                    ),
                    "daily_accrual_limit_points": points.daily_accrual_limit_points,
                    "operation_accrual_limit_points": points.per_operation_limit_points,
                    "large_operation_threshold_minor": points.approval_threshold_minor,
                    "large_operation_requires_approval": (
                        points.approval_threshold_minor is not None
                    ),
                    "visits_enabled": visits.enabled,
                    "visit_required_count": visits.required_visits,
                    "visits_must_be_consecutive": visits.consecutive_days,
                    "visit_daily_limit": visits.visits_per_business_day,
                    "timezone": document.installation.timezone,
                    "business_day_boundary_minutes": _boundary_minutes(
                        visits.business_day_boundary
                    ),
                    "visit_allowed_misses": visits.allowed_missed_days,
                    "visit_reset_on_miss": visits.reset_after_miss,
                    "visit_reward_template_id": _optional_reference(
                        reward_ids, visits.reward_template_slug
                    ),
                    "visit_reward_validity_days": visits.reward_validity_days,
                    "visit_restart_cycle": visits.restart_cycle_after_reward,
                    "stamps_enabled": stamps.enabled,
                    "stamp_required_count": stamps.required_paid_items,
                    "stamps_per_purchase": stamps.stamps_per_purchase,
                    "stamp_operation_limit": stamps.per_operation_limit,
                    "stamp_reward_template_id": _optional_reference(
                        reward_ids, stamps.reward_template_slug
                    ),
                    "stamp_reward_validity_days": stamps.reward_validity_days,
                    "reset_stamps_after_reward": stamps.reset_after_reward,
                    "birthday_promotion_enabled": birthday.enabled,
                    "birthday_discount_basis_points": birthday.discount_percent * 100,
                    "birthday_window_days": birthday.window_days,
                    "birthday_stackable": birthday.stackable,
                    "updated_by_staff_id": creator_id,
                }
            )
            await self._repository.replace_birthday_promotion_venues(
                settings_id,
                [venue_ids[slug] for slug in birthday.eligible_venue_slugs],
            )

            category_ids: dict[str, UUID] = {}
            for category in document.menu.categories:
                entity_id = _stable_id(entity_ids, f"menu-category:{category.slug}")
                category_ids[category.slug] = await self._repository.upsert_menu_category(
                    entity_id,
                    {
                        "name": category.name,
                        "venue_id": venue_ids[category.venue_slug],
                        "description": category.description,
                        "sort_order": category.sort_order,
                        "is_visible": category.is_active,
                        "archived_at": None if category.is_active else current_time,
                    },
                )
            item_ids: dict[str, UUID] = {}
            for item in document.menu.items:
                entity_id = _stable_id(entity_ids, f"menu-item:{item.slug}")
                category = next(
                    value for value in document.menu.categories if value.slug == item.category_slug
                )
                item_ids[item.slug] = await self._repository.upsert_menu_item(
                    entity_id,
                    {
                        "category_id": category_ids[item.category_slug],
                        "venue_id": venue_ids[category.venue_slug],
                        "name": item.name,
                        "description": item.description,
                        "image_media_id": await self._repository.find_media_id(
                            item.image_media_key
                        ),
                        "price_minor": item.price_minor,
                        "old_price_minor": item.old_price_minor,
                        "composition": item.composition,
                        "volume": item.volume,
                        "labels": item.labels,
                        "is_available": item.is_active,
                        "is_visible": item.is_active,
                        "sort_order": item.sort_order,
                        "archived_at": None if item.is_active else current_time,
                    },
                )

            for group in document.menu.modifier_groups:
                group_id = await self._repository.upsert_modifier_group(
                    _stable_id(entity_ids, f"modifier-group:{group.slug}"),
                    {
                        "venue_id": venue_ids[group.venue_slug],
                        "name": group.name,
                        "description": group.description,
                        "min_selections": group.min_selections,
                        "max_selections": group.max_selections,
                        "is_required": group.required,
                        "sort_order": group.sort_order,
                        "is_enabled": group.is_enabled,
                        "archived_at": None if group.is_enabled else current_time,
                    },
                )
                for option in group.options:
                    await self._repository.upsert_modifier_option(
                        _stable_id(
                            entity_ids,
                            f"modifier-option:{group.slug}:{option.slug}",
                        ),
                        {
                            "group_id": group_id,
                            "name": option.name,
                            "price_delta_minor": option.price_delta_minor,
                            "allows_quantity": option.allows_quantity,
                            "max_quantity": option.max_quantity,
                            "is_enabled": option.is_enabled,
                            "sort_order": option.sort_order,
                        },
                    )
                await self._repository.replace_modifier_group_items(
                    group_id,
                    venue_id=venue_ids[group.venue_slug],
                    item_ids=[item_ids[slug] for slug in group.applicable_item_slugs],
                    sort_order=group.sort_order,
                )

            if document.promotions and creator_id is None:
                raise SeedConfigurationError(
                    "An active staff member is required before importing promotions; "
                    "run create-owner first"
                )
            for promotion in document.promotions:
                entity_id = _stable_id(entity_ids, f"promotion:{promotion.slug}")
                body = (
                    f"{promotion.summary}\n\n{promotion.body}"
                    if promotion.summary
                    else promotion.body
                )
                promotion_id = await self._repository.upsert_promotion(
                    entity_id,
                    {
                        "venue_id": venue_ids[promotion.venue_slug],
                        "title": promotion.title,
                        "body": body,
                        "image_media_id": await self._repository.find_media_id(
                            promotion.image_media_key
                        ),
                        "button_label": promotion.button_label,
                        "button_url": promotion.button_url,
                        "status": promotion.status,
                        "starts_at": promotion.starts_at,
                        "ends_at": promotion.ends_at,
                        "published_at": current_time
                        if promotion.status == PromotionStatus.PUBLISHED
                        else None,
                        "created_by_staff_id": creator_id,
                        "pricing_enabled": promotion.pricing_enabled,
                        "action_type": promotion.action_type,
                        "discount_value": promotion.discount_value,
                        "priority": promotion.priority,
                        "stackable": promotion.stackable,
                        "active_from_date": promotion.active_from_date,
                        "active_to_date": promotion.active_to_date,
                        "active_weekdays": promotion.active_weekdays,
                        "active_time_from": promotion.active_time_from,
                        "active_time_to": promotion.active_time_to,
                        "fulfillment_modes": promotion.fulfillment_modes,
                        "customer_birthday_only": promotion.customer_birthday_only,
                        "minimum_order_minor": promotion.minimum_order_minor,
                    },
                )
                await self._repository.replace_promotion_targets(
                    promotion_id,
                    venue_id=venue_ids[promotion.venue_slug],
                    category_ids=[category_ids[slug] for slug in promotion.category_slugs],
                    menu_item_ids=[item_ids[slug] for slug in promotion.menu_item_slugs],
                )

            await self._repository.save_seed_entity_ids(entity_ids)

        return SeedReport(
            venues=len(document.venues),
            locations=len(document.locations),
            reward_templates=len(document.reward_templates),
            menu_categories=len(document.menu.categories),
            menu_items=len(document.menu.items),
            promotions=len(document.promotions),
            development_staff=development_staff,
        )

    async def export(self) -> dict[str, Any]:
        return await self._repository.export_configuration()


def _unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def _boundary_minutes(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise SeedConfigurationError(f"invalid business day boundary: {value}")
    hours, minutes = (int(part) for part in parts)
    if hours > 23 or minutes > 59:
        raise SeedConfigurationError(f"invalid business day boundary: {value}")
    return hours * 60 + minutes


def _stable_id(values: dict[str, UUID], key: str) -> UUID:
    if key not in values:
        values[key] = uuid4()
    return values[key]


def _reward_source(document: SeedDocument, slug: str) -> LoyaltyProgram:
    visit = document.loyalty.visits.reward_template_slug == slug
    stamp = document.loyalty.stamps.reward_template_slug == slug
    if visit and not stamp:
        return LoyaltyProgram.VISITS
    if stamp and not visit:
        return LoyaltyProgram.STAMPS
    return LoyaltyProgram.MANUAL


def _optional_reference(values: dict[str, UUID], key: str | None) -> UUID | None:
    if key is None:
        return None
    return values[key]

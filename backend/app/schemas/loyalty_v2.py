"""Transport contracts for wallets, birthdays, and Loyalty V2 settings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RoundingMode, WalletMode
from app.services.loyalty_v2 import (
    AdminBirthdayView,
    AdminLoyaltySettingsView,
    BirthdaySettingsUpdate,
    BirthdayView,
    VenueRateUpdate,
    WalletsView,
)
from app.services.wallet_mode import WalletModeChangeResult, WalletModePreview


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VenueSummaryResponse(ApiSchema):
    id: UUID
    name: str
    available: bool


class WalletEntryResponse(ApiSchema):
    wallet_id: UUID
    venue: VenueSummaryResponse | None
    balance: int
    expiring_amount: int
    expires_at: datetime | None


class WalletsResponse(ApiSchema):
    mode: WalletMode
    total_balance: int
    point_value_minor: int
    max_redemption_percent: int
    entries: list[WalletEntryResponse]


class BirthdayValueSchema(ApiSchema):
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)


class BirthdayUpdateRequest(ApiSchema):
    birthday: BirthdayValueSchema


class BirthdayOfferResponse(ApiSchema):
    enabled: bool
    discount_percent: int
    window_days: int
    eligible_venues: list[VenueSummaryResponse]
    stackable: bool
    active_now: bool
    starts_on: date | None
    ends_on: date | None


class BirthdayResponse(ApiSchema):
    birthday: BirthdayValueSchema | None
    locked: bool
    offer: BirthdayOfferResponse | None


class VenueRateSchema(ApiSchema):
    venue_id: UUID
    venue_name: str
    available: bool
    loyalty_points_enabled: bool
    accrual_basis_points: int = Field(ge=0, le=10_000)
    rounding_mode: RoundingMode


class VenueRateUpdateSchema(ApiSchema):
    venue_id: UUID
    loyalty_points_enabled: bool
    accrual_basis_points: int = Field(ge=0, le=10_000)
    rounding_mode: RoundingMode


class BirthdaySettingsSchema(ApiSchema):
    enabled: bool
    discount_percent: int = Field(ge=0, le=100)
    window_days: int = Field(ge=1, le=31)
    eligible_venue_ids: list[UUID]
    stackable: bool


class AdminLoyaltySettingsResponse(ApiSchema):
    wallet_mode: WalletMode
    point_value_minor: int
    max_redemption_percent: int
    expiry_months: int
    expiry_days_override: int | None
    expiry_reminder_days: int
    default_bonus_venue_id: UUID | None
    rounding: RoundingMode
    venue_rates: list[VenueRateSchema]
    birthday: BirthdaySettingsSchema


class AdminLoyaltySettingsUpdateRequest(ApiSchema):
    point_value_minor: int = Field(gt=0)
    max_redemption_percent: int = Field(ge=0, le=100)
    expiry_months: int = Field(ge=1, le=120)
    expiry_days_override: int | None = Field(ge=1, le=3_650)
    expiry_reminder_days: int = Field(ge=0, le=365)
    default_bonus_venue_id: UUID | None
    rounding: RoundingMode
    venue_rates: list[VenueRateUpdateSchema]
    birthday: BirthdaySettingsSchema


class AdminBirthdayUpdateRequest(ApiSchema):
    birthday: BirthdayValueSchema
    reason: str = Field(min_length=3, max_length=1_000)


class AdminBirthdayResponse(ApiSchema):
    user_id: UUID
    birthday: BirthdayValueSchema
    locked: bool
    updated_at: datetime


class WalletModePreviewRequest(ApiSchema):
    target_mode: WalletMode
    fallback_venue_id: UUID | None = None


class WalletModePreviewResponse(ApiSchema):
    current_mode: WalletMode
    target_mode: WalletMode
    preview_hash: str
    customers_affected: int
    wallets_affected: int
    total_balance_points: int
    transfer_operations: int
    fallback_required: bool
    fallback_venue_id: UUID | None
    unresolved_points: int
    eligible_fallback_venues: list[VenueSummaryResponse]
    warnings: list[str]


class WalletModeConfirmRequest(ApiSchema):
    target_mode: WalletMode
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    fallback_venue_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=1_000)
    confirm: Literal[True]


class WalletModeChangeResponse(ApiSchema):
    wallet_mode: WalletMode
    wallets_created: int
    transfer_operations: int
    total_balance_points: int
    completed_at: datetime
    idempotent_replay: bool


def wallets_response(value: WalletsView) -> WalletsResponse:
    return WalletsResponse(
        mode=value.mode,
        total_balance=value.total_balance,
        point_value_minor=value.point_value_minor,
        max_redemption_percent=value.max_redemption_percent,
        entries=[
            WalletEntryResponse(
                wallet_id=item.wallet_id,
                venue=(
                    VenueSummaryResponse(
                        id=item.venue.id,
                        name=item.venue.name,
                        available=item.venue.available,
                    )
                    if item.venue is not None
                    else None
                ),
                balance=item.balance,
                expiring_amount=item.expiring_amount,
                expires_at=item.expires_at,
            )
            for item in value.entries
        ],
    )


def birthday_response(value: BirthdayView) -> BirthdayResponse:
    return BirthdayResponse(
        birthday=(
            BirthdayValueSchema(month=value.birthday.month, day=value.birthday.day)
            if value.birthday is not None
            else None
        ),
        locked=value.locked,
        offer=(
            BirthdayOfferResponse(
                enabled=value.offer.enabled,
                discount_percent=value.offer.discount_percent,
                window_days=value.offer.window_days,
                eligible_venues=[
                    VenueSummaryResponse(
                        id=venue.id,
                        name=venue.name,
                        available=venue.available,
                    )
                    for venue in value.offer.eligible_venues
                ],
                stackable=value.offer.stackable,
                active_now=value.offer.active_now,
                starts_on=value.offer.starts_on,
                ends_on=value.offer.ends_on,
            )
            if value.offer is not None
            else None
        ),
    )


def admin_settings_response(
    value: AdminLoyaltySettingsView,
) -> AdminLoyaltySettingsResponse:
    return AdminLoyaltySettingsResponse(
        wallet_mode=value.wallet_mode,
        point_value_minor=value.point_value_minor,
        max_redemption_percent=value.max_redemption_percent,
        expiry_months=value.expiry_months,
        expiry_days_override=value.expiry_days_override,
        expiry_reminder_days=value.expiry_reminder_days,
        default_bonus_venue_id=value.default_bonus_venue_id,
        rounding=value.rounding,
        venue_rates=[
            VenueRateSchema(
                venue_id=item.venue_id,
                venue_name=item.venue_name,
                available=item.available,
                loyalty_points_enabled=item.loyalty_points_enabled,
                accrual_basis_points=item.accrual_basis_points,
                rounding_mode=item.rounding_mode,
            )
            for item in value.venue_rates
        ],
        birthday=BirthdaySettingsSchema(
            enabled=value.birthday.enabled,
            discount_percent=value.birthday.discount_percent,
            window_days=value.birthday.window_days,
            eligible_venue_ids=list(value.birthday.eligible_venue_ids),
            stackable=value.birthday.stackable,
        ),
    )


def venue_rate_updates(
    values: list[VenueRateUpdateSchema],
) -> tuple[VenueRateUpdate, ...]:
    return tuple(
        VenueRateUpdate(
            venue_id=item.venue_id,
            loyalty_points_enabled=item.loyalty_points_enabled,
            accrual_basis_points=item.accrual_basis_points,
            rounding_mode=item.rounding_mode,
        )
        for item in values
    )


def birthday_settings_update(value: BirthdaySettingsSchema) -> BirthdaySettingsUpdate:
    return BirthdaySettingsUpdate(
        enabled=value.enabled,
        discount_percent=value.discount_percent,
        window_days=value.window_days,
        eligible_venue_ids=tuple(value.eligible_venue_ids),
        stackable=value.stackable,
    )


def admin_birthday_response(value: AdminBirthdayView) -> AdminBirthdayResponse:
    return AdminBirthdayResponse(
        user_id=value.user_id,
        birthday=BirthdayValueSchema(
            month=value.birthday.month,
            day=value.birthday.day,
        ),
        locked=value.locked,
        updated_at=value.updated_at,
    )


def wallet_mode_preview_response(value: WalletModePreview) -> WalletModePreviewResponse:
    return WalletModePreviewResponse(
        current_mode=value.current_mode,
        target_mode=value.target_mode,
        preview_hash=value.preview_hash,
        customers_affected=value.customers_affected,
        wallets_affected=value.wallets_affected,
        total_balance_points=value.total_balance_points,
        transfer_operations=value.transfer_operations,
        fallback_required=value.fallback_required,
        fallback_venue_id=value.fallback_venue_id,
        unresolved_points=value.unresolved_points,
        eligible_fallback_venues=[
            VenueSummaryResponse(id=item.id, name=item.name, available=item.available)
            for item in value.eligible_fallback_venues
        ],
        warnings=list(value.warnings),
    )


def wallet_mode_change_response(value: WalletModeChangeResult) -> WalletModeChangeResponse:
    return WalletModeChangeResponse(
        wallet_mode=value.wallet_mode,
        wallets_created=value.wallets_created,
        transfer_operations=value.transfer_operations,
        total_balance_points=value.total_balance_points,
        completed_at=value.completed_at,
        idempotent_replay=value.idempotent_replay,
    )

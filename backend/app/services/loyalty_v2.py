"""Customer and owner use cases for Loyalty V2 configuration and wallets."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, NoReturn, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.content import Venue
from app.models.enums import (
    AuditSeverity,
    PermissionCode,
    RoundingMode,
    UserStatus,
    WalletMode,
)
from app.models.loyalty import LoyaltySettings
from app.models.loyalty_v2 import LoyaltyWallet, PointLot
from app.security.rbac import Actor
from app.services.loyalty_calculations import LoyaltyRuleViolation
from app.services.loyalty_v2_calculations import (
    is_birthday_window_active,
    validate_birthday,
)


@dataclass(frozen=True, slots=True)
class VenueSummary:
    id: UUID
    name: str
    available: bool


@dataclass(frozen=True, slots=True)
class WalletEntryView:
    wallet_id: UUID
    venue: VenueSummary | None
    balance: int
    expiring_amount: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class WalletsView:
    mode: WalletMode
    total_balance: int
    point_value_minor: int
    max_redemption_percent: int
    entries: tuple[WalletEntryView, ...]


@dataclass(frozen=True, slots=True)
class BirthdayValue:
    month: int
    day: int


@dataclass(frozen=True, slots=True)
class BirthdayOfferView:
    enabled: bool
    discount_percent: int
    window_days: int
    eligible_venues: tuple[VenueSummary, ...]
    stackable: bool
    active_now: bool
    starts_on: date | None
    ends_on: date | None


@dataclass(frozen=True, slots=True)
class BirthdayView:
    birthday: BirthdayValue | None
    locked: bool
    offer: BirthdayOfferView | None


@dataclass(frozen=True, slots=True)
class VenueRateView:
    venue_id: UUID
    venue_name: str
    available: bool
    loyalty_points_enabled: bool
    accrual_basis_points: int
    rounding_mode: RoundingMode


@dataclass(frozen=True, slots=True)
class VenueRateUpdate:
    venue_id: UUID
    loyalty_points_enabled: bool
    accrual_basis_points: int
    rounding_mode: RoundingMode


@dataclass(frozen=True, slots=True)
class BirthdaySettingsView:
    enabled: bool
    discount_percent: int
    window_days: int
    eligible_venue_ids: tuple[UUID, ...]
    stackable: bool


@dataclass(frozen=True, slots=True)
class BirthdaySettingsUpdate:
    enabled: bool
    discount_percent: int
    window_days: int
    eligible_venue_ids: tuple[UUID, ...]
    stackable: bool


@dataclass(frozen=True, slots=True)
class AdminLoyaltySettingsView:
    wallet_mode: WalletMode
    point_value_minor: int
    max_redemption_percent: int
    expiry_months: int
    expiry_days_override: int | None
    expiry_reminder_days: int
    default_bonus_venue_id: UUID | None
    rounding: RoundingMode
    venue_rates: tuple[VenueRateView, ...]
    birthday: BirthdaySettingsView


@dataclass(frozen=True, slots=True)
class AdminBirthdayView:
    user_id: UUID
    birthday: BirthdayValue
    locked: bool
    updated_at: datetime


class LoyaltyV2RepositoryPort(Protocol):
    """Persistence operations needed by customer/admin Loyalty V2 use cases."""

    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def get_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"] = "none",
    ) -> LoyaltySettings | None: ...

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None: ...

    async def list_wallet_views(
        self,
        user_id: UUID,
    ) -> list[tuple[LoyaltyWallet, Venue | None]]: ...

    async def list_lots_for_wallets(
        self,
        wallet_ids: list[UUID],
        *,
        for_update: bool,
    ) -> list[PointLot]: ...

    async def list_birthday_venues(self, settings_id: UUID) -> list[Venue]: ...

    async def list_venues(self, *, for_update: bool = False) -> list[Venue]: ...

    async def replace_birthday_venues(
        self,
        *,
        settings_id: UUID,
        venue_ids: list[UUID],
    ) -> None: ...

    def add(self, value: object) -> None: ...

    async def flush(self) -> None: ...


class LoyaltyV2Service:
    """Orchestrate V2 reads and configuration without bypassing the ledger."""

    def __init__(self, repository: LoyaltyV2RepositoryPort) -> None:
        self._repository = repository

    async def get_wallets(
        self,
        actor: Actor,
        *,
        now: datetime | None = None,
    ) -> WalletsView:
        current_time = _aware_now(now)
        settings = await self._required_settings(lock_mode="none")
        all_rows = await self._repository.list_wallet_views(actor.user_id)
        rows = _wallet_rows_for_mode(all_rows, settings.wallet_mode)
        lots_by_wallet = _group_lots_by_wallet(
            await self._repository.list_lots_for_wallets(
                [wallet.id for wallet, _venue in rows],
                for_update=False,
            )
        )
        entries: list[WalletEntryView] = []
        for wallet, venue in rows:
            available_lots = [
                lot
                for lot in lots_by_wallet.get(wallet.id, ())
                if lot.remaining_points > 0
                and (lot.expires_at is None or lot.expires_at > current_time)
            ]
            effective_balance = sum(lot.remaining_points for lot in available_lots)
            dated = [lot for lot in available_lots if lot.expires_at is not None]
            next_expiry = min(
                (lot.expires_at for lot in dated if lot.expires_at is not None),
                default=None,
            )
            expiring = sum(lot.remaining_points for lot in dated if lot.expires_at == next_expiry)
            entries.append(
                WalletEntryView(
                    wallet_id=wallet.id,
                    venue=(_venue_summary(venue) if venue is not None else None),
                    balance=effective_balance,
                    expiring_amount=expiring,
                    expires_at=next_expiry,
                )
            )
        return WalletsView(
            mode=settings.wallet_mode,
            total_balance=sum(item.balance for item in entries),
            point_value_minor=settings.redemption_minor_units_per_point,
            max_redemption_percent=settings.maximum_redemption_percent,
            entries=tuple(entries),
        )

    async def get_birthday(
        self,
        actor: Actor,
        *,
        now: datetime | None = None,
    ) -> BirthdayView:
        user = await self._repository.get_user(actor.user_id, for_update=False)
        if user is None:
            _not_found("User profile is unavailable")
        settings = await self._required_settings(lock_mode="none")
        return await self._birthday_view(user, settings, now=_aware_now(now))

    async def set_birthday(
        self,
        actor: Actor,
        *,
        month: int,
        day: int,
        now: datetime | None = None,
    ) -> BirthdayView:
        _validate_birthday_input(month, day)
        current_time = _aware_now(now)
        async with self._repository.transaction():
            settings = await self._required_settings(lock_mode="share")
            user = await self._repository.get_user(actor.user_id, for_update=True)
            if user is None:
                _not_found("User profile is unavailable")
            if user.status not in {UserStatus.ACTIVE, UserStatus.BLOCKED}:
                _conflict("account_unavailable", "Account is unavailable")
            if user.birthday_month is not None or user.birthday_day is not None:
                if user.birthday_month == month and user.birthday_day == day:
                    # A retried PUT after an ambiguous response is replay-safe;
                    # unlike a changed value it does not consume a second audit.
                    return await self._birthday_view(user, settings, now=current_time)
                _conflict(
                    "birthday_locked",
                    "Birthday is already set; contact an administrator to change it",
                )
            user.birthday_month = month
            user.birthday_day = day
            user.birthday_set_at = current_time
            user.birthday_updated_at = current_time
            user.birthday_updated_by_staff_id = None
            self._repository.add(
                AuditEvent(
                    id=uuid4(),
                    event_type="customer.birthday_set",
                    actor_user_id=actor.user_id,
                    subject_user_id=actor.user_id,
                    object_type="user",
                    object_id=user.id,
                    # Birthday values stay only on the customer row.  General
                    # audit/event streams must not duplicate this personal data.
                    event_metadata={"birthday_set": True},
                    severity=AuditSeverity.INFO,
                    is_suspicious=False,
                )
            )
            await self._repository.flush()
            return await self._birthday_view(user, settings, now=current_time)

    async def get_admin_settings(self, actor: Actor) -> AdminLoyaltySettingsView:
        _require_permission(actor, PermissionCode.ADMIN_SETTINGS_MANAGE)
        settings = await self._required_settings(lock_mode="none")
        return await self._admin_settings_view(settings)

    async def update_admin_settings(
        self,
        actor: Actor,
        *,
        point_value_minor: int,
        max_redemption_percent: int,
        expiry_months: int,
        expiry_days_override: int | None,
        expiry_reminder_days: int,
        default_bonus_venue_id: UUID | None,
        rounding: RoundingMode,
        venue_rates: tuple[VenueRateUpdate, ...],
        birthday: BirthdaySettingsUpdate,
        now: datetime | None = None,
    ) -> AdminLoyaltySettingsView:
        _require_permission(actor, PermissionCode.ADMIN_SETTINGS_MANAGE)
        _validate_admin_settings(
            point_value_minor=point_value_minor,
            max_redemption_percent=max_redemption_percent,
            expiry_months=expiry_months,
            expiry_days_override=expiry_days_override,
            expiry_reminder_days=expiry_reminder_days,
            venue_rates=venue_rates,
            birthday=birthday,
        )
        current_time = _aware_now(now)
        async with self._repository.transaction():
            settings = await self._required_settings(lock_mode="update")
            venues = await self._repository.list_venues(for_update=True)
            venues_by_id = {venue.id: venue for venue in venues}
            requested_ids = {item.venue_id for item in venue_rates}
            if requested_ids != set(venues_by_id):
                _validation(
                    "venue_rates_incomplete",
                    "Venue rates must contain every configured venue exactly once",
                )
            eligible_ids = set(birthday.eligible_venue_ids)
            if not eligible_ids.issubset(venues_by_id):
                _validation("birthday_venue_unknown", "Birthday venue is unknown")
            if any(not _venue_available(venues_by_id[value]) for value in eligible_ids):
                _validation(
                    "birthday_venue_unavailable",
                    "Birthday promotion can only target active venues",
                )
            if default_bonus_venue_id is not None and (
                default_bonus_venue_id not in venues_by_id
                or not _venue_available(venues_by_id[default_bonus_venue_id])
            ):
                _validation(
                    "default_bonus_venue_unavailable",
                    "Default bonus venue must be active",
                )
            if (
                settings.wallet_mode is WalletMode.SEPARATE
                and settings.welcome_bonus_points > 0
                and default_bonus_venue_id is None
            ):
                _validation(
                    "default_bonus_venue_required",
                    "Separate wallets require an active default venue for the welcome bonus",
                )
            settings.redemption_minor_units_per_point = point_value_minor
            settings.maximum_redemption_percent = max_redemption_percent
            settings.points_expiry_months = expiry_months
            settings.points_validity_days = expiry_days_override
            settings.expiry_reminder_days = expiry_reminder_days
            settings.default_bonus_venue_id = default_bonus_venue_id
            settings.rounding_mode = rounding
            settings.birthday_promotion_enabled = birthday.enabled
            settings.birthday_discount_basis_points = birthday.discount_percent * 100
            settings.birthday_window_days = birthday.window_days
            settings.birthday_stackable = birthday.stackable
            settings.updated_by_staff_id = actor.staff_member_id
            settings.updated_at = current_time
            for update in sorted(venue_rates, key=lambda item: item.venue_id.int):
                venue = venues_by_id[update.venue_id]
                venue.loyalty_points_enabled = update.loyalty_points_enabled
                venue.loyalty_accrual_basis_points = update.accrual_basis_points
                venue.loyalty_rounding_mode = update.rounding_mode
            await self._repository.replace_birthday_venues(
                settings_id=settings.id,
                venue_ids=list(eligible_ids),
            )
            self._repository.add(
                AuditEvent(
                    id=uuid4(),
                    event_type="loyalty.v2_settings_updated",
                    actor_user_id=actor.user_id,
                    actor_staff_id=actor.staff_member_id,
                    object_type="loyalty_settings",
                    object_id=settings.id,
                    event_metadata={
                        "point_value_minor": point_value_minor,
                        "max_redemption_percent": max_redemption_percent,
                        "expiry_months": expiry_months,
                        "expiry_days_override": expiry_days_override,
                        "expiry_reminder_days": expiry_reminder_days,
                        "default_bonus_venue_id": (
                            str(default_bonus_venue_id)
                            if default_bonus_venue_id is not None
                            else None
                        ),
                        "rounding": rounding.value,
                        "venue_rates": [
                            {
                                "venue_id": str(item.venue_id),
                                "enabled": item.loyalty_points_enabled,
                                "basis_points": item.accrual_basis_points,
                                "rounding": item.rounding_mode.value,
                            }
                            for item in venue_rates
                        ],
                        "birthday": {
                            "enabled": birthday.enabled,
                            "discount_percent": birthday.discount_percent,
                            "window_days": birthday.window_days,
                            "eligible_venue_ids": sorted(str(value) for value in eligible_ids),
                            "stackable": birthday.stackable,
                        },
                    },
                    severity=AuditSeverity.WARNING,
                    is_suspicious=False,
                )
            )
            await self._repository.flush()
            return await self._admin_settings_view(settings, venues=venues)

    async def admin_set_birthday(
        self,
        actor: Actor,
        *,
        user_id: UUID,
        month: int,
        day: int,
        reason: str,
        now: datetime | None = None,
    ) -> AdminBirthdayView:
        _require_permission(actor, PermissionCode.ADMIN_USERS_MANAGE)
        _validate_birthday_input(month, day)
        normalized_reason = " ".join(reason.split())
        if len(normalized_reason) < 3:
            _validation("birthday_reason_required", "A visible change reason is required")
        current_time = _aware_now(now)
        async with self._repository.transaction():
            user = await self._repository.get_user(user_id, for_update=True)
            if user is None:
                _not_found("User profile is unavailable")
            if user.status not in {UserStatus.ACTIVE, UserStatus.BLOCKED}:
                _conflict("account_unavailable", "Account is unavailable")
            if user.birthday_month == month and user.birthday_day == day:
                # An administrator can safely retry the same PUT after an
                # ambiguous response without creating a duplicate PII audit.
                updated_at = (
                    user.birthday_updated_at
                    or user.birthday_set_at
                    or user.updated_at
                    or current_time
                )
                return AdminBirthdayView(
                    user_id=user.id,
                    birthday=BirthdayValue(month=month, day=day),
                    locked=True,
                    updated_at=updated_at,
                )
            previous = (
                {"month": user.birthday_month, "day": user.birthday_day}
                if user.birthday_month is not None and user.birthday_day is not None
                else None
            )
            user.birthday_month = month
            user.birthday_day = day
            user.birthday_set_at = user.birthday_set_at or current_time
            user.birthday_updated_at = current_time
            user.birthday_updated_by_staff_id = actor.staff_member_id
            self._repository.add(
                AuditEvent(
                    id=uuid4(),
                    event_type="customer.birthday_changed_by_admin",
                    actor_user_id=actor.user_id,
                    actor_staff_id=actor.staff_member_id,
                    subject_user_id=user.id,
                    object_type="user",
                    object_id=user.id,
                    event_metadata={
                        "previous_was_set": previous is not None,
                        "changed": True,
                        "reason": normalized_reason,
                    },
                    severity=AuditSeverity.WARNING,
                    is_suspicious=False,
                )
            )
            await self._repository.flush()
            return AdminBirthdayView(
                user_id=user.id,
                birthday=BirthdayValue(month=month, day=day),
                locked=True,
                updated_at=current_time,
            )

    async def _required_settings(
        self,
        *,
        lock_mode: Literal["none", "share", "update"],
    ) -> LoyaltySettings:
        settings = await self._repository.get_settings(lock_mode=lock_mode)
        if settings is None:
            raise RuntimeError("Loyalty settings are not initialized")
        return settings

    async def _birthday_view(
        self,
        user: User,
        settings: LoyaltySettings,
        *,
        now: datetime,
    ) -> BirthdayView:
        if user.birthday_month is None or user.birthday_day is None:
            return BirthdayView(birthday=None, locked=False, offer=None)
        birthday = BirthdayValue(month=user.birthday_month, day=user.birthday_day)
        eligible = await self._repository.list_birthday_venues(settings.id)
        if not eligible:
            eligible = [
                venue for venue in await self._repository.list_venues() if _venue_available(venue)
            ]
        starts_on, ends_on = _birthday_window_dates(
            month=birthday.month,
            day=birthday.day,
            at=now,
            timezone_name=settings.timezone,
            window_days=settings.birthday_window_days,
        )
        try:
            active_now = settings.birthday_promotion_enabled and is_birthday_window_active(
                birthday.month,
                birthday.day,
                at=now,
                timezone_name=settings.timezone,
                window_days=settings.birthday_window_days,
            )
        except LoyaltyRuleViolation as exc:
            _validation(exc.code, exc.message)
        return BirthdayView(
            birthday=birthday,
            locked=True,
            offer=BirthdayOfferView(
                enabled=settings.birthday_promotion_enabled,
                discount_percent=settings.birthday_discount_basis_points // 100,
                window_days=settings.birthday_window_days,
                eligible_venues=tuple(_venue_summary(venue) for venue in eligible),
                stackable=settings.birthday_stackable,
                active_now=active_now,
                starts_on=starts_on,
                ends_on=ends_on,
            ),
        )

    async def _admin_settings_view(
        self,
        settings: LoyaltySettings,
        *,
        venues: list[Venue] | None = None,
    ) -> AdminLoyaltySettingsView:
        all_venues = venues if venues is not None else await self._repository.list_venues()
        eligible = await self._repository.list_birthday_venues(settings.id)
        return AdminLoyaltySettingsView(
            wallet_mode=settings.wallet_mode,
            point_value_minor=settings.redemption_minor_units_per_point,
            max_redemption_percent=settings.maximum_redemption_percent,
            expiry_months=settings.points_expiry_months,
            expiry_days_override=settings.points_validity_days,
            expiry_reminder_days=settings.expiry_reminder_days,
            default_bonus_venue_id=settings.default_bonus_venue_id,
            rounding=settings.rounding_mode,
            venue_rates=tuple(
                VenueRateView(
                    venue_id=venue.id,
                    venue_name=venue.name,
                    available=_venue_available(venue),
                    loyalty_points_enabled=venue.loyalty_points_enabled,
                    accrual_basis_points=venue.loyalty_accrual_basis_points,
                    rounding_mode=venue.loyalty_rounding_mode,
                )
                for venue in all_venues
            ),
            birthday=BirthdaySettingsView(
                enabled=settings.birthday_promotion_enabled,
                discount_percent=settings.birthday_discount_basis_points // 100,
                window_days=settings.birthday_window_days,
                eligible_venue_ids=tuple(venue.id for venue in eligible),
                stackable=settings.birthday_stackable,
            ),
        )


def _validate_admin_settings(
    *,
    point_value_minor: int,
    max_redemption_percent: int,
    expiry_months: int,
    expiry_days_override: int | None,
    expiry_reminder_days: int,
    venue_rates: tuple[VenueRateUpdate, ...],
    birthday: BirthdaySettingsUpdate,
) -> None:
    if point_value_minor <= 0:
        _validation("invalid_point_value", "Point value must be positive")
    if not 0 <= max_redemption_percent <= 100:
        _validation("invalid_redemption_percent", "Redemption percent must be 0..100")
    if not 1 <= expiry_months <= 120:
        _validation("invalid_expiry_months", "Expiry months must be 1..120")
    if expiry_days_override is not None and not 1 <= expiry_days_override <= 3_650:
        _validation("invalid_expiry_days_override", "Expiry day override must be 1..3650")
    if not 0 <= expiry_reminder_days <= 365:
        _validation("invalid_expiry_reminder_days", "Expiry reminder must be 0..365 days")
    if len({item.venue_id for item in venue_rates}) != len(venue_rates):
        _validation("duplicate_venue_rate", "Venue rates contain duplicates")
    if any(not 0 <= item.accrual_basis_points <= 10_000 for item in venue_rates):
        _validation("invalid_accrual_rate", "Accrual basis points must be 0..10000")
    if not 0 <= birthday.discount_percent <= 100:
        _validation("invalid_birthday_discount", "Birthday discount must be 0..100")
    if not 1 <= birthday.window_days <= 31:
        _validation("invalid_birthday_window", "Birthday window must be 1..31 days")
    if len(set(birthday.eligible_venue_ids)) != len(birthday.eligible_venue_ids):
        _validation("duplicate_birthday_venue", "Birthday venues contain duplicates")


def _validate_birthday_input(month: int, day: int) -> None:
    try:
        validate_birthday(month, day)
    except LoyaltyRuleViolation as exc:
        _validation(exc.code, exc.message)


def _birthday_window_dates(
    *,
    month: int,
    day: int,
    at: datetime,
    timezone_name: str,
    window_days: int,
) -> tuple[date, date]:
    try:
        local_day = at.astimezone(ZoneInfo(timezone_name)).date()
    except ZoneInfoNotFoundError:
        _validation("invalid_timezone", "Unknown loyalty timezone")
    candidates: list[tuple[date, date]] = []
    for year in (local_day.year - 1, local_day.year, local_day.year + 1):
        observed_day = 28 if month == 2 and day == 29 and not calendar.isleap(year) else day
        starts_on = date(year, month, observed_day)
        candidates.append((starts_on, starts_on + timedelta(days=window_days - 1)))
    active = [window for window in candidates if window[0] <= local_day <= window[1]]
    if active:
        return active[-1]
    return min(
        (window for window in candidates if window[0] > local_day),
        key=lambda window: window[0],
    )


def _wallet_rows_for_mode(
    rows: list[tuple[LoyaltyWallet, Venue | None]],
    mode: WalletMode,
) -> list[tuple[LoyaltyWallet, Venue | None]]:
    """Hide drained historical scopes while rejecting conservation drift."""

    inactive = [
        wallet
        for wallet, _venue in rows
        if (mode is WalletMode.SHARED and wallet.venue_id is not None)
        or (mode is WalletMode.SEPARATE and wallet.venue_id is None)
    ]
    if any(wallet.balance_points != 0 for wallet in inactive):
        raise RuntimeError("inactive loyalty wallet scope has a non-zero balance")
    if mode is WalletMode.SHARED:
        return [(wallet, venue) for wallet, venue in rows if wallet.venue_id is None]
    return [
        (wallet, venue)
        for wallet, venue in rows
        if wallet.venue_id is not None
        and (wallet.balance_points != 0 or (venue is not None and _venue_available(venue)))
    ]


def _group_lots_by_wallet(lots: Iterable[PointLot]) -> dict[UUID, list[PointLot]]:
    grouped: dict[UUID, list[PointLot]] = {}
    for lot in lots:
        grouped.setdefault(lot.wallet_id, []).append(lot)
    return grouped


def _venue_available(venue: Venue) -> bool:
    return venue.is_active and venue.archived_at is None


def _venue_summary(venue: Venue) -> VenueSummary:
    return VenueSummary(id=venue.id, name=venue.name, available=_venue_available(venue))


def _require_permission(actor: Actor, permission: PermissionCode) -> None:
    if not actor.can(permission):
        raise AppError(
            code=ErrorCode.FORBIDDEN,
            message="Insufficient permissions",
            status_code=status.HTTP_403_FORBIDDEN,
        )


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(
        code=code,
        message=message,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _not_found(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.NOT_FOUND,
        message=message,
        status_code=status.HTTP_404_NOT_FOUND,
    )

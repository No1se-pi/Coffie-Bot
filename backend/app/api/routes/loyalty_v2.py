"""Loyalty V2 wallet, birthday, and owner configuration endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.loyalty_v2 import PointLedgerRepository
from app.schemas.loyalty_v2 import (
    AdminBirthdayResponse,
    AdminBirthdayUpdateRequest,
    AdminLoyaltySettingsResponse,
    AdminLoyaltySettingsUpdateRequest,
    BirthdayResponse,
    BirthdayUpdateRequest,
    WalletModeChangeResponse,
    WalletModeConfirmRequest,
    WalletModePreviewRequest,
    WalletModePreviewResponse,
    WalletsResponse,
    admin_birthday_response,
    admin_settings_response,
    birthday_response,
    birthday_settings_update,
    venue_rate_updates,
    wallet_mode_change_response,
    wallet_mode_preview_response,
    wallets_response,
)
from app.security.rbac import Actor, get_current_actor, require_permissions
from app.services.loyalty_v2 import LoyaltyV2Service
from app.services.wallet_mode import WalletModeService

me_router = APIRouter(prefix="/me", tags=["current-user"])
admin_router = APIRouter(prefix="/admin", tags=["admin-loyalty"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def _service(session: AsyncSession) -> LoyaltyV2Service:
    return LoyaltyV2Service(PointLedgerRepository(session))


def _wallet_mode_service(session: AsyncSession) -> WalletModeService:
    return WalletModeService(PointLedgerRepository(session))


@me_router.get("/wallets", response_model=WalletsResponse)
async def current_wallets(
    session: DatabaseSession,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> WalletsResponse:
    return wallets_response(await _service(session).get_wallets(actor))


@me_router.get("/birthday", response_model=BirthdayResponse)
async def current_birthday(
    session: DatabaseSession,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> BirthdayResponse:
    return birthday_response(await _service(session).get_birthday(actor))


@me_router.put("/birthday", response_model=BirthdayResponse)
async def set_current_birthday(
    payload: BirthdayUpdateRequest,
    session: DatabaseSession,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> BirthdayResponse:
    value = await _service(session).set_birthday(
        actor,
        month=payload.birthday.month,
        day=payload.birthday.day,
    )
    return birthday_response(value)


@admin_router.get("/loyalty", response_model=AdminLoyaltySettingsResponse)
async def admin_loyalty_settings(
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_SETTINGS_MANAGE)),
    ],
) -> AdminLoyaltySettingsResponse:
    return admin_settings_response(await _service(session).get_admin_settings(actor))


@admin_router.put("/loyalty", response_model=AdminLoyaltySettingsResponse)
async def update_admin_loyalty_settings(
    payload: AdminLoyaltySettingsUpdateRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_SETTINGS_MANAGE)),
    ],
) -> AdminLoyaltySettingsResponse:
    value = await _service(session).update_admin_settings(
        actor,
        point_value_minor=payload.point_value_minor,
        max_redemption_percent=payload.max_redemption_percent,
        expiry_months=payload.expiry_months,
        expiry_days_override=payload.expiry_days_override,
        expiry_reminder_days=payload.expiry_reminder_days,
        default_bonus_venue_id=payload.default_bonus_venue_id,
        rounding=payload.rounding,
        venue_rates=venue_rate_updates(payload.venue_rates),
        birthday=birthday_settings_update(payload.birthday),
    )
    return admin_settings_response(value)


@admin_router.put("/users/{user_id}/birthday", response_model=AdminBirthdayResponse)
async def update_admin_birthday(
    user_id: UUID,
    payload: AdminBirthdayUpdateRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.ADMIN_USERS_MANAGE)),
    ],
) -> AdminBirthdayResponse:
    value = await _service(session).admin_set_birthday(
        actor,
        user_id=user_id,
        month=payload.birthday.month,
        day=payload.birthday.day,
        reason=payload.reason,
    )
    return admin_birthday_response(value)


@admin_router.post(
    "/loyalty/wallet-mode/preview",
    response_model=WalletModePreviewResponse,
)
async def preview_wallet_mode(
    payload: WalletModePreviewRequest,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.OWNER_CRITICAL_SETTINGS)),
    ],
) -> WalletModePreviewResponse:
    value = await _wallet_mode_service(session).preview(
        actor,
        target_mode=payload.target_mode,
        fallback_venue_id=payload.fallback_venue_id,
    )
    return wallet_mode_preview_response(value)


@admin_router.post(
    "/loyalty/wallet-mode/confirm",
    response_model=WalletModeChangeResponse,
)
async def confirm_wallet_mode(
    payload: WalletModeConfirmRequest,
    idempotency_key: IdempotencyKey,
    session: DatabaseSession,
    actor: Annotated[
        Actor,
        Depends(require_permissions(PermissionCode.OWNER_CRITICAL_SETTINGS)),
    ],
) -> WalletModeChangeResponse:
    value = await _wallet_mode_service(session).confirm(
        actor,
        target_mode=payload.target_mode,
        fallback_venue_id=payload.fallback_venue_id,
        preview_hash=payload.preview_hash,
        reason=payload.reason,
        idempotency_key=str(idempotency_key),
    )
    return wallet_mode_change_response(value)

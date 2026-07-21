"""Identity registration, Telegram authentication, sessions, and self-service reads."""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol
from uuid import UUID

from fastapi import status

from app.core.config import AppEnvironment, Settings
from app.core.errors import AppError, ErrorCode
from app.models.access import StaffMember, User
from app.models.enums import (
    LoyaltyOperationType,
    PermissionCode,
    RewardStatus,
    Role,
    UserStatus,
)
from app.models.loyalty import LoyaltySettings
from app.repositories.identity import (
    CardViewRecord,
    HistoryPageRecord,
    IdentityAccessRecord,
    RewardPageRecord,
)
from app.security.rbac import resolve_permissions
from app.security.sessions import IssuedSessionToken, issue_session_token
from app.security.telegram import (
    TelegramInitDataVerifier,
    TelegramUserData,
    VerifiedTelegramInitData,
)

SHORT_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
SHORT_CODE_LENGTH = 8


class TelegramVerifier(Protocol):
    def verify(
        self,
        init_data: str,
        *,
        now: datetime | None = None,
    ) -> VerifiedTelegramInitData: ...


class IdentityRepositoryPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def upsert_telegram_user(
        self,
        telegram_user: TelegramUserData,
        *,
        now: datetime,
    ) -> tuple[User, bool]: ...

    async def get_loyalty_settings(self) -> LoyaltySettings | None: ...

    def initialize_customer(
        self,
        *,
        user_id: UUID,
        qr_token: str,
        short_code: str,
        welcome_bonus_points: int,
        now: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None: ...

    def create_session(
        self,
        *,
        user_id: UUID,
        issued: IssuedSessionToken,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def get_identity_access(self, user_id: UUID) -> IdentityAccessRecord | None: ...

    async def get_card_view(self, user_id: UUID) -> CardViewRecord | None: ...

    async def revoke_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> None: ...

    async def list_history(
        self,
        *,
        user_id: UUID,
        operation_type: LoyaltyOperationType | None,
        page: int,
        page_size: int,
    ) -> HistoryPageRecord: ...

    async def list_rewards(
        self,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPageRecord: ...


@dataclass(frozen=True, slots=True)
class IdentityView:
    user: User
    staff: StaffMember | None
    role: Role
    available_roles: tuple[Role, ...]
    permissions: frozenset[PermissionCode]


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    identity: IdentityView
    card: CardViewRecord
    created: bool


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    access_token: str
    expires_at: datetime
    registration: RegistrationResult


class IdentityService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: IdentityRepositoryPort,
        verifier: TelegramVerifier | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._verifier = verifier

    async def authenticate(
        self,
        init_data: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> AuthenticationResult:
        """Verify Telegram data and atomically register plus issue an opaque session."""

        current_time = _aware_now(now)
        telegram_user = self._verified_telegram_user(init_data, now=current_time)
        issued = issue_session_token(
            ttl=timedelta(seconds=self._settings.session_ttl_seconds),
            pepper=_session_pepper(self._settings),
            now=current_time,
        )
        safe_ip = _truncate(ip_address, 45)
        safe_user_agent = _truncate(user_agent, 512)

        async with self._repository.transaction():
            registration = await self._register_in_current_transaction(
                telegram_user,
                ip_address=safe_ip,
                user_agent=safe_user_agent,
                now=current_time,
            )
            self._repository.create_session(
                user_id=registration.identity.user.id,
                issued=issued,
                ip_address=safe_ip,
                user_agent=safe_user_agent,
            )
            await self._repository.flush()

        return AuthenticationResult(
            access_token=issued.raw_token,
            expires_at=issued.expires_at,
            registration=registration,
        )

    async def register_telegram_user(
        self,
        telegram_user: TelegramUserData,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> RegistrationResult:
        """Reusable bot/API registration without creating an application session."""

        current_time = _aware_now(now)
        safe_ip = _truncate(ip_address, 45)
        safe_user_agent = _truncate(user_agent, 512)
        async with self._repository.transaction():
            return await self._register_in_current_transaction(
                telegram_user,
                ip_address=safe_ip,
                user_agent=safe_user_agent,
                now=current_time,
            )

    async def logout(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        now: datetime | None = None,
    ) -> None:
        async with self._repository.transaction():
            await self._repository.revoke_session(
                session_id=session_id,
                user_id=user_id,
                now=_aware_now(now),
            )

    async def get_identity(self, user_id: UUID) -> IdentityView:
        access = await self._repository.get_identity_access(user_id)
        if access is None:
            _raise_not_found("User profile is unavailable")
        return _identity_view(access)

    async def get_card(self, user_id: UUID) -> CardViewRecord:
        card = await self._repository.get_card_view(user_id)
        if card is None:
            _raise_not_found("Active customer card is unavailable")
        return card

    async def list_history(
        self,
        *,
        user_id: UUID,
        operation_type: LoyaltyOperationType | None,
        page: int,
        page_size: int,
    ) -> HistoryPageRecord:
        return await self._repository.list_history(
            user_id=user_id,
            operation_type=operation_type,
            page=page,
            page_size=page_size,
        )

    async def list_rewards(
        self,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPageRecord:
        return await self._repository.list_rewards(
            user_id=user_id,
            reward_status=reward_status,
            page=page,
            page_size=page_size,
        )

    async def _register_in_current_transaction(
        self,
        telegram_user: TelegramUserData,
        *,
        ip_address: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> RegistrationResult:
        if telegram_user.is_bot:
            raise AppError(
                code=ErrorCode.INVALID_TELEGRAM_DATA,
                message="Invalid Telegram authorization data",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

        user, created = await self._repository.upsert_telegram_user(
            telegram_user,
            now=now,
        )
        if user.status in {UserStatus.INACTIVE, UserStatus.ANONYMIZED}:
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="Account is unavailable",
                status_code=status.HTTP_403_FORBIDDEN,
            )

        customer_aggregate_missing = (
            created or await self._repository.get_card_view(user.id) is None
        )
        if customer_aggregate_missing:
            loyalty_settings = await self._repository.get_loyalty_settings()
            welcome_bonus = (
                loyalty_settings.welcome_bonus_points
                if loyalty_settings is not None and loyalty_settings.points_enabled
                else 0
            )
            self._repository.initialize_customer(
                user_id=user.id,
                qr_token=secrets.token_urlsafe(32),
                short_code="".join(
                    secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH)
                ),
                welcome_bonus_points=welcome_bonus,
                now=now,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        await self._repository.flush()
        access = await self._repository.get_identity_access(user.id)
        card = await self._repository.get_card_view(user.id)
        if access is None or card is None:
            raise RuntimeError("Registration aggregate is incomplete")
        return RegistrationResult(
            identity=_identity_view(access),
            card=card,
            created=created,
        )

    def _verified_telegram_user(
        self,
        init_data: str,
        *,
        now: datetime,
    ) -> TelegramUserData:
        if self._settings.dev_auth_enabled:
            if self._settings.app_env is not AppEnvironment.DEVELOPMENT:
                raise RuntimeError("Development authentication is only allowed in development")
            telegram_id = self._settings.dev_auth_telegram_id
            if telegram_id is None:
                raise RuntimeError("Development Telegram ID is not configured")
            return TelegramUserData(
                id=telegram_id,
                first_name="Development User",
                language_code="en",
            )

        verifier = self._verifier or self._build_verifier()
        return verifier.verify(init_data, now=now).user

    def _build_verifier(self) -> TelegramInitDataVerifier:
        if self._settings.bot_token is None:
            raise RuntimeError("BOT_TOKEN is required for Telegram authentication")
        return TelegramInitDataVerifier(
            bot_token=self._settings.bot_token.get_secret_value(),
            ttl=timedelta(seconds=self._settings.telegram_init_data_ttl_seconds),
            future_skew=timedelta(seconds=self._settings.telegram_auth_future_skew_seconds),
            max_bytes=self._settings.telegram_init_data_max_bytes,
        )


def _identity_view(access: IdentityAccessRecord) -> IdentityView:
    staff = access.staff
    if staff is None:
        return IdentityView(
            user=access.user,
            staff=None,
            role=Role.CUSTOMER,
            available_roles=(Role.CUSTOMER,),
            permissions=frozenset(),
        )
    overrides: Mapping[PermissionCode, bool] = {
        item.permission: item.allowed for item in staff.permissions
    }
    return IdentityView(
        user=access.user,
        staff=staff,
        role=staff.role,
        available_roles=(Role.CUSTOMER, staff.role),
        permissions=resolve_permissions(staff.role, overrides),
    )


def _session_pepper(settings: Settings) -> str | None:
    if settings.session_token_pepper is None:
        return None
    return settings.session_token_pepper.get_secret_value()


def _aware_now(value: datetime | None) -> datetime:
    current_time = value or datetime.now(UTC)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current_time


def _truncate(value: str | None, maximum: int) -> str | None:
    return None if value is None else value[:maximum]


def _raise_not_found(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.NOT_FOUND,
        message=message,
        status_code=status.HTTP_404_NOT_FOUND,
    )

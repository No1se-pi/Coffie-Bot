"""Phone-only customer registration and provider-neutral identity reads."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, NoReturn, Protocol
from uuid import UUID, uuid4

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.models.access import User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.customers import CustomerIdentity
from app.models.enums import (
    AuditSeverity,
    IdentityProvider,
    PermissionCode,
    UserStatus,
)
from app.models.loyalty import LoyaltySettings
from app.repositories.customers import CustomerCreationReceipt
from app.repositories.identity import CardViewRecord
from app.security.rbac import Actor
from app.services.identity import SHORT_CODE_ALPHABET, SHORT_CODE_LENGTH

_PHONE_ALLOWED = re.compile(r"^[+\d\s().-]+$")


class CustomerRepositoryPort(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]: ...

    async def acquire_namespace_lock(self, namespace: str, value: str) -> None: ...

    async def get_identity(
        self,
        *,
        provider: IdentityProvider,
        subject: str,
        for_update: bool = False,
    ) -> CustomerIdentity | None: ...

    async def list_identities(self, user_id: UUID) -> list[CustomerIdentity]: ...

    async def get_user(self, user_id: UUID, *, for_update: bool) -> User | None: ...

    async def get_card(self, card_id: UUID) -> UserCard | None: ...

    def add(self, value: object) -> None: ...

    async def get_creation_receipt(self, key: str) -> CustomerCreationReceipt | None: ...

    async def get_loyalty_settings(self) -> LoyaltySettings | None: ...

    def create_phone_profile(
        self,
        *,
        phone: str,
        display_name: str,
        actor_staff_id: UUID,
        now: datetime,
    ) -> User: ...

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
        actor_user_id: UUID | None = None,
        actor_staff_id: UUID | None = None,
        event_type: str = "user.registered",
        event_idempotency_key: str | None = None,
        event_metadata: dict[str, Any] | None = None,
        enqueue_telegram_notification: bool = True,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def get_card_view(self, user_id: UUID) -> CardViewRecord | None: ...


@dataclass(frozen=True, slots=True)
class CustomerRequestMetadata:
    ip_address: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class PhoneCustomerResult:
    user_id: UUID
    card_id: UUID
    display_name: str
    masked_phone: str
    short_code: str
    points_balance: int
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class CustomerIdentityView:
    id: UUID
    provider: IdentityProvider
    subject: str
    verified: bool
    verified_at: datetime | None


@dataclass(frozen=True, slots=True)
class VerifiedPhoneLinkResult:
    """Outcome safe to show in Telegram without exposing the matched profile."""

    status: str
    masked_phone: str


class CustomerService:
    def __init__(self, repository: CustomerRepositoryPort) -> None:
        self._repository = repository

    async def create_phone_customer(
        self,
        actor: Actor,
        *,
        phone: str,
        display_name: str | None,
        idempotency_key: str,
        metadata: CustomerRequestMetadata | None = None,
        now: datetime | None = None,
    ) -> PhoneCustomerResult:
        """Create the same card/loyalty aggregate as Telegram registration, once."""

        _require_permission(actor, PermissionCode.CUSTOMERS_CREATE)
        if actor.staff_member_id is None:
            _forbidden("Профиль сотрудника недоступен")
        normalized_phone = normalize_phone(phone)
        normalized_name = normalize_customer_name(display_name)
        current_time = _aware_now(now)
        request_metadata = metadata or CustomerRequestMetadata()
        event_key = f"customer.phone.create:{idempotency_key}"
        request_hash = _request_hash(
            actor,
            phone=normalized_phone,
            display_name=normalized_name,
        )

        async with self._repository.transaction():
            # The idempotency lock is always acquired before the identity lock so
            # concurrent retries cannot deadlock with a different phone request.
            await self._repository.acquire_namespace_lock("customer.phone.create", idempotency_key)
            receipt = await self._repository.get_creation_receipt(event_key)
            if receipt is not None:
                if (
                    receipt.event_type != "customer.created.phone"
                    or receipt.request_hash != request_hash
                    or receipt.user_id is None
                ):
                    _conflict(
                        "idempotency_conflict",
                        "Idempotency key уже использован с другими данными",
                    )
                return await self._replay_result(receipt, normalized_phone)

            await self._repository.acquire_namespace_lock(
                "customer.identity.phone", normalized_phone
            )
            existing = await self._repository.get_identity(
                provider=IdentityProvider.PHONE,
                subject=normalized_phone,
                for_update=True,
            )
            if existing is not None:
                _conflict("phone_already_registered", "Клиент с этим телефоном уже существует")

            settings = await self._repository.get_loyalty_settings()
            welcome_bonus = (
                settings.welcome_bonus_points
                if settings is not None and settings.points_enabled
                else 0
            )
            user = self._repository.create_phone_profile(
                phone=normalized_phone,
                display_name=normalized_name,
                actor_staff_id=actor.staff_member_id,
                now=current_time,
            )
            self._repository.initialize_customer(
                user_id=user.id,
                qr_token=secrets.token_urlsafe(32),
                short_code="".join(
                    secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH)
                ),
                welcome_bonus_points=welcome_bonus,
                now=current_time,
                ip_address=_truncate(request_metadata.ip_address, 45),
                user_agent=_truncate(request_metadata.user_agent, 512),
                actor_user_id=actor.user_id,
                actor_staff_id=actor.staff_member_id,
                event_type="customer.created.phone",
                event_idempotency_key=event_key,
                event_metadata={
                    "identity_provider": IdentityProvider.PHONE.value,
                    "phone_last4": normalized_phone[-4:],
                    "request_hash": request_hash,
                    # Store a least-PII response receipt. Replays must not drift
                    # after card rotation, profile edits or balance operations.
                    "display_name": normalized_name,
                    "masked_phone": mask_phone(normalized_phone),
                    "points_balance": welcome_bonus,
                },
                enqueue_telegram_notification=False,
            )
            await self._repository.flush()
            return await self._result(user.id, normalized_phone, replay=False)

    async def list_identities(self, user_id: UUID) -> tuple[CustomerIdentityView, ...]:
        if await self._repository.get_user(user_id, for_update=False) is None:
            raise AppError(
                code=ErrorCode.NOT_FOUND,
                message="Профиль клиента не найден",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        values = await self._repository.list_identities(user_id)
        return tuple(
            CustomerIdentityView(
                id=value.id,
                provider=value.provider,
                subject=value.subject,
                verified=value.is_verified,
                verified_at=value.verified_at,
            )
            for value in values
        )

    async def _replay_result(
        self,
        receipt: CustomerCreationReceipt,
        normalized_phone: str,
    ) -> PhoneCustomerResult:
        if (
            receipt.user_id is not None
            and receipt.card_id is not None
            and receipt.display_name is not None
            and receipt.masked_phone is not None
            and receipt.points_balance is not None
        ):
            card = await self._repository.get_card(receipt.card_id)
            if card is None or card.user_id != receipt.user_id:
                raise RuntimeError("Phone customer idempotency receipt is incomplete")
            return PhoneCustomerResult(
                user_id=receipt.user_id,
                card_id=card.id,
                display_name=receipt.display_name,
                masked_phone=receipt.masked_phone,
                short_code=card.short_code,
                points_balance=receipt.points_balance,
                idempotent_replay=True,
            )

        # Compatibility for receipts created during the pre-release Phase 1
        # development window; production 0009 writes the snapshot above.
        if receipt.user_id is None:
            raise RuntimeError("Phone customer idempotency receipt has no user")
        return await self._result(receipt.user_id, normalized_phone, replay=True)

    async def link_verified_telegram_contact(
        self,
        *,
        telegram_id: int,
        contact_user_id: int,
        phone: str,
        now: datetime | None = None,
    ) -> VerifiedPhoneLinkResult:
        """Attach a phone only when Telegram proves that the contact is self-owned.

        If that phone already belongs to another profile, this method deliberately
        leaves both profiles untouched. The audited merge workflow can then combine
        them without silently moving balances or immutable history.
        """

        if contact_user_id != telegram_id:
            _forbidden("Можно подтвердить только собственный контакт Telegram")
        normalized_phone = normalize_phone(phone)
        current_time = _aware_now(now)
        telegram_subject = str(telegram_id)

        async with self._repository.transaction():
            # Use the same namespace as staff phone creation so linking and creation
            # cannot both claim an as-yet missing unique identity.
            await self._repository.acquire_namespace_lock(
                "customer.identity.phone", normalized_phone
            )
            telegram_identity = await self._repository.get_identity(
                provider=IdentityProvider.TELEGRAM,
                subject=telegram_subject,
                for_update=True,
            )
            if telegram_identity is None or not telegram_identity.is_verified:
                _forbidden("Сначала зарегистрируйтесь через Telegram")
            user = await self._repository.get_user(
                telegram_identity.user_id,
                for_update=True,
            )
            if user is None or user.status is not UserStatus.ACTIVE:
                _forbidden("Профиль недоступен")

            phone_identity = await self._repository.get_identity(
                provider=IdentityProvider.PHONE,
                subject=normalized_phone,
                for_update=True,
            )
            if phone_identity is not None and phone_identity.user_id != user.id:
                self._repository.add(
                    _phone_link_audit(
                        user_id=user.id,
                        event_type="customer.phone_link.merge_required",
                        phone=normalized_phone,
                        now=current_time,
                        merge_candidate_user_id=phone_identity.user_id,
                    )
                )
                await self._repository.flush()
                return VerifiedPhoneLinkResult(
                    status="merge_required",
                    masked_phone=mask_phone(normalized_phone),
                )

            if phone_identity is None:
                phone_identity = CustomerIdentity(
                    id=uuid4(),
                    user_id=user.id,
                    provider=IdentityProvider.PHONE,
                    subject=normalized_phone,
                    is_verified=True,
                    verified_at=current_time,
                    last_used_at=current_time,
                    provider_metadata={"verification_method": "telegram_contact"},
                )
                self._repository.add(phone_identity)
                event_type = "customer.phone_linked"
                result_status = "linked"
            else:
                phone_identity.is_verified = True
                phone_identity.verified_at = current_time
                phone_identity.last_used_at = current_time
                phone_identity.provider_metadata = {
                    **phone_identity.provider_metadata,
                    "verification_method": "telegram_contact",
                }
                event_type = "customer.phone_link.confirmed"
                result_status = "already_linked"

            self._repository.add(
                _phone_link_audit(
                    user_id=user.id,
                    event_type=event_type,
                    phone=normalized_phone,
                    now=current_time,
                )
            )
            await self._repository.flush()
            return VerifiedPhoneLinkResult(
                status=result_status,
                masked_phone=mask_phone(normalized_phone),
            )

    async def _result(
        self,
        user_id: UUID,
        phone: str,
        *,
        replay: bool,
    ) -> PhoneCustomerResult:
        record = await self._repository.get_card_view(user_id)
        if record is None:
            raise RuntimeError("Phone customer aggregate is incomplete")
        return PhoneCustomerResult(
            user_id=user_id,
            card_id=record.card.id,
            display_name=" ".join(
                value for value in (record.user.first_name, record.user.last_name) if value
            ),
            masked_phone=mask_phone(phone),
            short_code=record.card.short_code,
            points_balance=record.loyalty_state.points_balance,
            idempotent_replay=replay,
        )


def normalize_phone(value: str) -> str:
    """Normalize Russian local forms and require `+` for other country codes."""

    raw = value.strip()
    if not raw or not _PHONE_ALLOWED.fullmatch(raw):
        _validation("invalid_phone", "Укажите корректный номер телефона")
    digits = "".join(character for character in raw if character.isdigit())
    if raw.startswith("+"):
        normalized = f"+{digits}"
    elif len(digits) == 10:
        normalized = f"+7{digits}"
    elif len(digits) == 11 and digits.startswith("8"):
        normalized = f"+7{digits[1:]}"
    elif len(digits) == 11 and digits.startswith("7"):
        normalized = f"+{digits}"
    else:
        _validation(
            "invalid_phone",
            "Для международного номера укажите код страны со знаком +",
        )
    if not re.fullmatch(r"\+[1-9]\d{7,14}", normalized):
        _validation("invalid_phone", "Укажите корректный номер телефона")
    return normalized


def normalize_customer_name(value: str | None) -> str:
    normalized = " ".join((value or "").split())
    return (normalized or "Гость")[:128]


def mask_phone(value: str) -> str:
    visible = value[-4:]
    return f"{value[:2]}{'*' * max(0, len(value) - 6)}{visible}"


def _request_hash(actor: Actor, *, phone: str, display_name: str) -> str:
    payload = json.dumps(
        {
            "actor_user_id": str(actor.user_id),
            "phone": phone,
            "display_name": display_name,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _phone_link_audit(
    *,
    user_id: UUID,
    event_type: str,
    phone: str,
    now: datetime,
    merge_candidate_user_id: UUID | None = None,
) -> AuditEvent:
    # Only the last four digits are useful for support correlation; the full
    # verified phone remains protected in customer_identities.
    return AuditEvent(
        id=uuid4(),
        event_type=event_type,
        actor_user_id=user_id,
        subject_user_id=user_id,
        object_type="customer_identity",
        event_metadata={
            "provider": "phone",
            "phone_last4": phone[-4:],
            **(
                {"merge_candidate_user_id": str(merge_candidate_user_id)}
                if merge_candidate_user_id is not None
                else {}
            ),
        },
        severity=AuditSeverity.INFO,
        is_suspicious=False,
        created_at=now,
        updated_at=now,
    )


def _require_permission(actor: Actor, permission: PermissionCode) -> None:
    if not actor.can(permission):
        _forbidden("Недостаточно прав")


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return current


def _truncate(value: str | None, maximum: int) -> str | None:
    return None if value is None else value[:maximum]


def _validation(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def _conflict(code: str, message: str) -> NoReturn:
    raise AppError(code=code, message=message, status_code=status.HTTP_409_CONFLICT)


def _forbidden(message: str) -> NoReturn:
    raise AppError(
        code=ErrorCode.FORBIDDEN,
        message=message,
        status_code=status.HTTP_403_FORBIDDEN,
    )

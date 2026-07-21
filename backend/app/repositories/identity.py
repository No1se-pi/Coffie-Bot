"""Persistence operations for identity and customer self-service reads."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.access import Session, StaffMember, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.delivery import NotificationOutbox
from app.models.enums import (
    AuditSeverity,
    CardStatus,
    LoyaltyOperationType,
    OperationStatus,
    OutboxStatus,
    RewardStatus,
    UserStatus,
)
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    Reward,
    UserLoyaltyState,
)
from app.security.sessions import IssuedSessionToken
from app.security.telegram import TelegramUserData


@dataclass(frozen=True, slots=True)
class IdentityAccessRecord:
    user: User
    staff: StaffMember | None


@dataclass(frozen=True, slots=True)
class CardViewRecord:
    user: User
    card: UserCard
    loyalty_state: UserLoyaltyState
    settings: LoyaltySettings | None


@dataclass(frozen=True, slots=True)
class HistoryPageRecord:
    items: list[LoyaltyOperation]
    total: int


@dataclass(frozen=True, slots=True)
class RewardPageRecord:
    items: list[Reward]
    total: int


class IdentityRepository:
    """SQLAlchemy adapter. Transaction ownership remains with the service."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return self._transaction()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        """Commit writes even when an auth dependency already triggered autobegin."""

        if not self._session.in_transaction():
            async with self._session.begin():
                yield
            return
        try:
            yield
        except BaseException:
            await self._session.rollback()
            raise
        else:
            await self._session.commit()

    async def upsert_telegram_user(
        self,
        telegram_user: TelegramUserData,
        *,
        now: datetime,
    ) -> tuple[User, bool]:
        """Insert exactly once by Telegram ID, then lock and refresh public fields."""

        user_id = uuid4()
        values = {
            "id": user_id,
            "telegram_id": telegram_user.id,
            "username": _truncate(telegram_user.username, 64),
            "first_name": _truncate(telegram_user.first_name, 128) or "Telegram user",
            "last_name": _truncate(telegram_user.last_name, 128),
            "language_code": _truncate(telegram_user.language_code, 16),
            "photo_url": _truncate(telegram_user.photo_url, 2048),
            "status": UserStatus.ACTIVE,
            "last_seen_at": now,
        }
        statement = (
            pg_insert(User)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
            .returning(User.id)
        )
        inserted_id = await self._session.scalar(statement)
        created = inserted_id is not None

        if created:
            user = await self._session.get(User, inserted_id)
        else:
            user = await self._session.scalar(
                select(User).where(User.telegram_id == telegram_user.id).with_for_update()
            )
        if user is None:  # Defensive: ON CONFLICT must identify the existing row.
            raise RuntimeError("Telegram user upsert did not return a user")

        user.username = _truncate(telegram_user.username, 64)
        user.first_name = _truncate(telegram_user.first_name, 128) or user.first_name
        user.last_name = _truncate(telegram_user.last_name, 128)
        user.language_code = _truncate(telegram_user.language_code, 16)
        user.photo_url = _truncate(telegram_user.photo_url, 2048)
        user.last_seen_at = now
        return user, created

    async def get_loyalty_settings(self) -> LoyaltySettings | None:
        settings: LoyaltySettings | None = await self._session.scalar(
            select(LoyaltySettings).where(LoyaltySettings.singleton_key == "default")
        )
        return settings

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
    ) -> None:
        """Stage the complete first-registration aggregate in the current transaction."""

        card_id = uuid4()
        loyalty_state = UserLoyaltyState(
            id=uuid4(),
            user_id=user_id,
            points_balance=welcome_bonus_points,
            visit_streak=0,
            allowed_misses_used=0,
            stamp_count=0,
            version=1,
        )
        card = UserCard(
            id=card_id,
            user_id=user_id,
            qr_token=qr_token,
            short_code=short_code,
            status=CardStatus.ACTIVE,
        )
        staged: list[object] = [loyalty_state, card]

        if welcome_bonus_points > 0:
            operation_id = uuid4()
            request_hash = hashlib.sha256(
                f"welcome:{user_id}:{welcome_bonus_points}".encode()
            ).hexdigest()
            operation = LoyaltyOperation(
                id=operation_id,
                user_id=user_id,
                actor_user_id=user_id,
                operation_type=LoyaltyOperationType.WELCOME_BONUS,
                status=OperationStatus.COMMITTED,
                idempotency_key=f"welcome:{user_id}",
                request_hash=request_hash,
                points_delta=welcome_bonus_points,
                balance_before=0,
                balance_after=welcome_bonus_points,
                occurred_at=now,
            )
            transaction = PointTransaction(
                id=uuid4(),
                operation_id=operation_id,
                user_id=user_id,
                delta=welcome_bonus_points,
                balance_before=0,
                balance_after=welcome_bonus_points,
                created_at=now,
            )
            staged.extend([operation, transaction])

        audit = AuditEvent(
            id=uuid4(),
            event_type="user.registered",
            actor_user_id=user_id,
            subject_user_id=user_id,
            object_type="user_card",
            object_id=card_id,
            event_metadata={"welcome_bonus_points": welcome_bonus_points},
            severity=AuditSeverity.INFO,
            is_suspicious=False,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        notification = NotificationOutbox(
            id=uuid4(),
            user_id=user_id,
            event_type="user.registered",
            payload={"welcome_bonus_points": welcome_bonus_points},
            idempotency_key=f"registration:{user_id}",
            status=OutboxStatus.PENDING,
            attempts=0,
        )
        staged.extend([audit, notification])
        self._session.add_all(staged)

    def create_session(
        self,
        *,
        user_id: UUID,
        issued: IssuedSessionToken,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        self._session.add(
            Session(
                id=uuid4(),
                user_id=user_id,
                token_hash=issued.token_hash,
                created_at=issued.created_at,
                expires_at=issued.expires_at,
                created_ip=ip_address,
                user_agent=user_agent,
            )
        )

    async def flush(self) -> None:
        await self._session.flush()

    async def get_identity_access(self, user_id: UUID) -> IdentityAccessRecord | None:
        user = await self._session.scalar(
            select(User)
            .options(selectinload(User.staff_member).selectinload(StaffMember.permissions))
            .where(User.id == user_id)
        )
        if user is None:
            return None
        staff = user.staff_member
        if staff is not None and not staff.is_active:
            staff = None
        return IdentityAccessRecord(user=user, staff=staff)

    async def revoke_session(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
        now: datetime,
    ) -> None:
        await self._session.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.user_id == user_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason="user_logout")
        )

    async def get_card_view(self, user_id: UUID) -> CardViewRecord | None:
        statement = (
            select(User, UserCard, UserLoyaltyState, LoyaltySettings)
            .join(UserCard, UserCard.user_id == User.id)
            .join(UserLoyaltyState, UserLoyaltyState.user_id == User.id)
            .outerjoin(LoyaltySettings, LoyaltySettings.singleton_key == "default")
            .where(
                User.id == user_id,
                UserCard.status == CardStatus.ACTIVE,
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        return CardViewRecord(
            user=row[0],
            card=row[1],
            loyalty_state=row[2],
            settings=row[3],
        )

    async def list_history(
        self,
        *,
        user_id: UUID,
        operation_type: LoyaltyOperationType | None,
        page: int,
        page_size: int,
    ) -> HistoryPageRecord:
        filters = [LoyaltyOperation.user_id == user_id]
        if operation_type is not None:
            filters.append(LoyaltyOperation.operation_type == operation_type)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(LoyaltyOperation).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(LoyaltyOperation)
                    .where(*filters)
                    .order_by(LoyaltyOperation.occurred_at.desc(), LoyaltyOperation.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return HistoryPageRecord(items=items, total=total)

    async def list_rewards(
        self,
        *,
        user_id: UUID,
        reward_status: RewardStatus | None,
        page: int,
        page_size: int,
    ) -> RewardPageRecord:
        filters = [Reward.user_id == user_id]
        if reward_status is not None:
            filters.append(Reward.status == reward_status)
        total = int(
            await self._session.scalar(select(func.count()).select_from(Reward).where(*filters))
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(Reward)
                    .where(*filters)
                    .order_by(Reward.created_at.desc(), Reward.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
        )
        return RewardPageRecord(items=items, total=total)


def _truncate(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    return value[:maximum]

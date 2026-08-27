"""Request actor loading and backend-enforced RBAC dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.errors import AppError, ErrorCode
from app.db.session import get_db_session
from app.models.access import Session, StaffMember, User
from app.models.enums import PermissionCode, Role, UserStatus
from app.security.sessions import hash_session_token

bearer_scheme = HTTPBearer(auto_error=False)

STAFF_DEFAULT_PERMISSIONS = frozenset(
    {
        PermissionCode.CARD_LOOKUP,
        PermissionCode.CUSTOMERS_CREATE,
        PermissionCode.POINTS_ACCRUE,
        PermissionCode.POINTS_REDEEM,
        PermissionCode.VISITS_MARK,
        PermissionCode.STAMPS_ADD,
        PermissionCode.REWARDS_REDEEM,
        PermissionCode.OWN_OPERATIONS_REVERSE,
        PermissionCode.OWN_TIP_PROFILE_MANAGE,
        PermissionCode.ORDERS_READ,
        PermissionCode.ORDERS_MANAGE,
    }
)
ADMIN_PERMISSIONS = STAFF_DEFAULT_PERMISSIONS | frozenset(
    {
        PermissionCode.ADMIN_USERS_READ,
        PermissionCode.ADMIN_USERS_MANAGE,
        PermissionCode.ADMIN_STAFF_MANAGE,
        PermissionCode.ADMIN_EVENTS_READ,
        PermissionCode.ADMIN_SETTINGS_MANAGE,
        PermissionCode.ADMIN_CONTENT_MANAGE,
        PermissionCode.ADMIN_BROADCASTS_MANAGE,
        PermissionCode.ADMIN_FEEDBACK_MANAGE,
        PermissionCode.ADMIN_DELIVERY_MANAGE,
    }
)
OWNER_PERMISSIONS = frozenset(PermissionCode)


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: UUID
    telegram_id: int
    session_id: UUID
    role: Role
    staff_member_id: UUID | None
    permissions: frozenset[PermissionCode]

    def can(self, permission: PermissionCode) -> bool:
        return permission in self.permissions


def resolve_permissions(
    role: Role,
    overrides: Mapping[PermissionCode, bool] | None = None,
) -> frozenset[PermissionCode]:
    if role is Role.CUSTOMER:
        return frozenset()
    if role is Role.OWNER:
        return OWNER_PERMISSIONS
    if role is Role.ADMIN:
        return ADMIN_PERMISSIONS

    permissions = set(STAFF_DEFAULT_PERMISSIONS)
    for permission, allowed in (overrides or {}).items():
        if permission not in STAFF_DEFAULT_PERMISSIONS:
            continue
        if allowed:
            permissions.add(permission)
        else:
            permissions.discard(permission)
    return frozenset(permissions)


async def load_actor(
    session: AsyncSession,
    *,
    raw_token: str,
    pepper: str | None,
    now: datetime | None = None,
) -> Actor:
    current_time = now or datetime.now(UTC)
    token_hash = hash_session_token(raw_token, pepper=pepper)
    statement = (
        select(Session)
        .options(
            joinedload(Session.user)
            .selectinload(User.staff_member)
            .selectinload(StaffMember.permissions)
        )
        .where(
            Session.token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > current_time,
        )
    )
    db_session = await session.scalar(statement)
    if (
        db_session is None
        or db_session.user.telegram_id is None
        or db_session.user.status
        in {
            UserStatus.INACTIVE,
            UserStatus.ANONYMIZED,
            UserStatus.MERGED,
        }
    ):
        raise AppError(
            code=ErrorCode.INVALID_SESSION,
            message="Session is invalid or expired",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    staff = db_session.user.staff_member
    if staff is None or not staff.is_active:
        role = Role.CUSTOMER
        staff_id = None
        permissions: frozenset[PermissionCode] = frozenset()
    else:
        role = staff.role
        staff_id = staff.id
        overrides = {item.permission: item.allowed for item in staff.permissions}
        permissions = resolve_permissions(role, overrides)

    return Actor(
        user_id=db_session.user.id,
        telegram_id=db_session.user.telegram_id,
        session_id=db_session.id,
        role=role,
        staff_member_id=staff_id,
        permissions=permissions,
    )


async def get_current_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Actor:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(
            code=ErrorCode.AUTHENTICATION_REQUIRED,
            message="Authentication is required",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    settings = request.app.state.settings
    pepper = (
        settings.session_token_pepper.get_secret_value()
        if settings.session_token_pepper is not None
        else None
    )
    return await load_actor(
        session,
        raw_token=credentials.credentials,
        pepper=pepper,
    )


def require_roles(*allowed_roles: Role) -> Callable[..., Awaitable[Actor]]:
    allowed = frozenset(allowed_roles)

    async def dependency(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
        if actor.role not in allowed:
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="Insufficient role",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return actor

    return dependency


def require_permissions(*required_permissions: PermissionCode) -> Callable[..., Awaitable[Actor]]:
    required = frozenset(required_permissions)

    async def dependency(actor: Annotated[Actor, Depends(get_current_actor)]) -> Actor:
        if not required.issubset(actor.permissions):
            raise AppError(
                code=ErrorCode.FORBIDDEN,
                message="Insufficient permissions",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return actor

    return dependency

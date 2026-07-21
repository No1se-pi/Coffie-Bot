from uuid import uuid4

import pytest

from app.core.errors import AppError
from app.models.enums import PermissionCode, Role
from app.security.rbac import (
    Actor,
    require_permissions,
    require_roles,
    resolve_permissions,
)


def actor(role: Role) -> Actor:
    return Actor(
        user_id=uuid4(),
        telegram_id=123,
        session_id=uuid4(),
        role=role,
        staff_member_id=None if role is Role.CUSTOMER else uuid4(),
        permissions=resolve_permissions(role),
    )


def test_staff_override_can_deny_but_cannot_grant_admin_permission() -> None:
    permissions = resolve_permissions(
        Role.STAFF,
        {
            PermissionCode.POINTS_REDEEM: False,
            PermissionCode.ADMIN_SETTINGS_MANAGE: True,
        },
    )

    assert PermissionCode.POINTS_ACCRUE in permissions
    assert PermissionCode.POINTS_REDEEM not in permissions
    assert PermissionCode.ADMIN_SETTINGS_MANAGE not in permissions


def test_admin_does_not_receive_owner_only_permissions() -> None:
    permissions = resolve_permissions(Role.ADMIN)

    assert PermissionCode.ADMIN_STAFF_MANAGE in permissions
    assert PermissionCode.OWNER_ADMINS_MANAGE not in permissions


def test_owner_receives_all_permissions() -> None:
    assert resolve_permissions(Role.OWNER) == frozenset(PermissionCode)


@pytest.mark.asyncio
async def test_role_dependency_rejects_wrong_role() -> None:
    dependency = require_roles(Role.OWNER)

    with pytest.raises(AppError) as error:
        await dependency(actor(Role.ADMIN))

    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_permission_dependency_accepts_authorized_actor() -> None:
    dependency = require_permissions(PermissionCode.POINTS_ACCRUE)
    staff = actor(Role.STAFF)

    assert await dependency(staff) is staff

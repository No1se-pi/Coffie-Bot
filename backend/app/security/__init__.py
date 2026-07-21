"""Authentication and authorization security boundary."""

from app.security.rbac import Actor, get_current_actor, require_permissions, require_roles
from app.security.sessions import IssuedSessionToken, hash_session_token, issue_session_token
from app.security.telegram import TelegramInitDataVerifier, VerifiedTelegramInitData

__all__ = [
    "Actor",
    "IssuedSessionToken",
    "TelegramInitDataVerifier",
    "VerifiedTelegramInitData",
    "get_current_actor",
    "hash_session_token",
    "issue_session_token",
    "require_permissions",
    "require_roles",
]

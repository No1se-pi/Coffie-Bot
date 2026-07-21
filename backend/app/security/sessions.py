"""Opaque high-entropy session token issuance and one-way hashing."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

TOKEN_PREFIX = "cbs_"
TOKEN_ENTROPY_BYTES = 32


@dataclass(frozen=True, slots=True)
class IssuedSessionToken:
    raw_token: str
    token_hash: str
    created_at: datetime
    expires_at: datetime


def hash_session_token(raw_token: str, *, pepper: str | None = None) -> str:
    if not raw_token:
        raise ValueError("raw_token must not be empty")
    encoded = raw_token.encode("utf-8")
    if pepper:
        return hmac.new(pepper.encode("utf-8"), encoded, hashlib.sha256).hexdigest()
    return hashlib.sha256(encoded).hexdigest()


def issue_session_token(
    *,
    ttl: timedelta,
    pepper: str | None = None,
    now: datetime | None = None,
) -> IssuedSessionToken:
    if ttl <= timedelta(0):
        raise ValueError("ttl must be positive")
    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    raw_token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)}"
    return IssuedSessionToken(
        raw_token=raw_token,
        token_hash=hash_session_token(raw_token, pepper=pepper),
        created_at=created_at,
        expires_at=created_at + ttl,
    )

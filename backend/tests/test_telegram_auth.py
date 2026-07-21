from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from app.core.errors import AppError
from app.security.telegram import TelegramInitDataVerifier

BOT_TOKEN = "123456789:development-test-token"


def signed_init_data(*, auth_date: datetime, user_id: int = 42) -> str:
    fields = {
        "signature": "public-signature-is-part-of-bot-token-hmac-input",
        "query_id": "query-123",
        "auth_date": str(int(auth_date.timestamp())),
        "user": json.dumps(
            {
                "id": user_id,
                "first_name": "Ярослав",
                "username": "coffee_guest",
                "language_code": "ru",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def verifier() -> TelegramInitDataVerifier:
    return TelegramInitDataVerifier(bot_token=BOT_TOKEN, ttl=timedelta(minutes=15))


def test_verifies_signature_freshness_and_user() -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)

    verified = verifier().verify(signed_init_data(auth_date=now), now=now)

    assert verified.user.id == 42
    assert verified.user.first_name == "Ярослав"
    assert verified.auth_date == now
    assert verified.query_id == "query-123"


def test_rejects_tampered_init_data() -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)
    init_data = signed_init_data(auth_date=now).replace("coffee_guest", "other_guest")

    with pytest.raises(AppError, match="Invalid Telegram"):
        verifier().verify(init_data, now=now)


def test_rejects_expired_init_data() -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)

    with pytest.raises(AppError):
        verifier().verify(signed_init_data(auth_date=now - timedelta(minutes=16)), now=now)


def test_rejects_duplicate_fields() -> None:
    now = datetime(2026, 7, 21, 12, tzinfo=UTC)
    init_data = f"{signed_init_data(auth_date=now)}&auth_date={int(now.timestamp())}"

    with pytest.raises(AppError):
        verifier().verify(init_data, now=now)


def test_rejects_naive_reference_time() -> None:
    naive_now = datetime(2026, 7, 21, 12, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        verifier().verify(signed_init_data(auth_date=naive_now.replace(tzinfo=UTC)), now=naive_now)

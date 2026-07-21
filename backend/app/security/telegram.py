"""Server-side validation of raw Telegram Mini App initData."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from urllib.parse import parse_qsl

from fastapi import status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import AppError, ErrorCode


class TelegramUserData(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=256)
    last_name: str | None = Field(default=None, max_length=256)
    username: str | None = Field(default=None, max_length=64)
    language_code: str | None = Field(default=None, max_length=35)
    photo_url: str | None = Field(default=None, max_length=2048)
    is_bot: bool = False
    is_premium: bool = False
    allows_write_to_pm: bool = False


class VerifiedTelegramInitData(BaseModel):
    """Only values produced after signature and freshness checks."""

    model_config = ConfigDict(frozen=True)

    user: TelegramUserData
    auth_date: datetime
    query_id: str | None = None
    start_param: str | None = None


class TelegramInitDataVerifier:
    def __init__(
        self,
        *,
        bot_token: str,
        ttl: timedelta,
        future_skew: timedelta = timedelta(seconds=30),
        max_bytes: int = 16_384,
    ) -> None:
        if not bot_token:
            raise ValueError("bot_token must not be empty")
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        if future_skew < timedelta(0):
            raise ValueError("future_skew must not be negative")
        self._bot_token = bot_token
        self._ttl = ttl
        self._future_skew = future_skew
        self._max_bytes = max_bytes

    def verify(
        self,
        init_data: str,
        *,
        now: datetime | None = None,
    ) -> VerifiedTelegramInitData:
        current_time = now or datetime.now(UTC)
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        if not init_data or len(init_data.encode("utf-8")) > self._max_bytes:
            self._raise_invalid()

        try:
            pairs = parse_qsl(
                init_data,
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=64,
            )
        except ValueError:
            self._raise_invalid()

        fields: dict[str, str] = {}
        for key, value in pairs:
            if not key or key in fields:
                self._raise_invalid()
            fields[key] = value

        received_hash = fields.pop("hash", None)
        if received_hash is None or len(received_hash) != 64:
            self._raise_invalid()

        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret_key = hmac.new(
            b"WebAppData",
            self._bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(received_hash.lower(), expected_hash):
            self._raise_invalid()

        try:
            auth_timestamp = int(fields["auth_date"])
            auth_date = datetime.fromtimestamp(auth_timestamp, tz=UTC)
            raw_user: Any = json.loads(fields["user"])
            if not isinstance(raw_user, dict):
                self._raise_invalid()
            user = TelegramUserData.model_validate(raw_user)
        except (
            KeyError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
            OverflowError,
        ):
            self._raise_invalid()

        if auth_date > current_time + self._future_skew:
            self._raise_invalid()
        if current_time - auth_date > self._ttl:
            self._raise_invalid()

        return VerifiedTelegramInitData(
            user=user,
            auth_date=auth_date,
            query_id=fields.get("query_id"),
            start_param=fields.get("start_param"),
        )

    @staticmethod
    def _raise_invalid() -> NoReturn:
        raise AppError(
            code=ErrorCode.INVALID_TELEGRAM_DATA,
            message="Invalid Telegram authorization data",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

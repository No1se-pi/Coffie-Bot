"""Typed environment configuration."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Settings loaded from process environment and an optional local ``.env`` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_name: str = "Coffie Bot API"
    app_version: str = "0.1.0"
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://coffie:coffie@localhost:5432/coffie"
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)

    bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None
    telegram_webapp_url: str | None = None
    telegram_init_data_ttl_seconds: int = Field(default=600, ge=60, le=86_400)
    telegram_auth_future_skew_seconds: int = Field(default=30, ge=0, le=300)
    telegram_init_data_max_bytes: int = Field(default=16_384, ge=1024, le=65_536)

    session_ttl_seconds: int = Field(default=900, ge=300, le=86_400)
    session_token_pepper: SecretStr | None = None
    admin_web_username: str | None = Field(default=None, min_length=3, max_length=64)
    admin_web_password_hash: SecretStr | None = None
    admin_web_telegram_id: int | None = Field(default=None, gt=0)
    dev_auth_enabled: bool = False
    dev_auth_telegram_id: int | None = Field(default=None, gt=0)
    cors_origins: list[str] = Field(default_factory=list)
    media_root: Path = Path("/app/media")
    seed_file: Path = Path("/app/configs/demo-seed.json")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            return json.loads(stripped)
        return [item.strip() for item in stripped.split(",") if item.strip()]

    @field_validator(
        "admin_web_username",
        "admin_web_password_hash",
        "admin_web_telegram_id",
        mode="before",
    )
    @classmethod
    def blank_optional_web_auth(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_security_boundaries(self) -> Settings:
        if self.app_env is AppEnvironment.PRODUCTION:
            if self.dev_auth_enabled:
                msg = "DEV_AUTH_ENABLED must be false in production"
                raise ValueError(msg)
            if self.bot_token is None:
                msg = "BOT_TOKEN is required in production"
                raise ValueError(msg)
            bot_token = self.bot_token.get_secret_value()
            if bot_token.casefold().startswith("replace-with-"):
                msg = "BOT_TOKEN must not be a placeholder in production"
                raise ValueError(msg)
            if re.fullmatch(r"[0-9]+:[^\s]+", bot_token) is None:
                msg = "BOT_TOKEN must have Telegram's <digits>:<nonspace> format"
                raise ValueError(msg)
            if self.session_token_pepper is None:
                msg = "SESSION_TOKEN_PEPPER is required in production"
                raise ValueError(msg)
            session_token_pepper = self.session_token_pepper.get_secret_value()
            if session_token_pepper.casefold().startswith("replace-with-"):
                msg = "SESSION_TOKEN_PEPPER must not be a placeholder in production"
                raise ValueError(msg)
            if len(session_token_pepper) < 48:
                msg = "SESSION_TOKEN_PEPPER must be at least 48 characters in production"
                raise ValueError(msg)
            if self.app_debug:
                msg = "APP_DEBUG must be false in production"
                raise ValueError(msg)
            if self.telegram_webapp_url is not None:
                webapp_url = urlsplit(self.telegram_webapp_url)
                if webapp_url.scheme != "https" or not webapp_url.hostname:
                    msg = "TELEGRAM_WEBAPP_URL must be an absolute HTTPS URL in production"
                    raise ValueError(msg)
            for origin in self.cors_origins:
                parsed_origin = urlsplit(origin)
                if origin == "*" or parsed_origin.scheme != "https" or not parsed_origin.hostname:
                    msg = "CORS_ORIGINS must contain only absolute HTTPS origins in production"
                    raise ValueError(msg)
        if self.dev_auth_enabled and self.dev_auth_telegram_id is None:
            msg = "DEV_AUTH_TELEGRAM_ID is required when DEV_AUTH_ENABLED=true"
            raise ValueError(msg)
        web_auth_values = (
            self.admin_web_username,
            self.admin_web_password_hash,
            self.admin_web_telegram_id,
        )
        if any(value is not None for value in web_auth_values) and not all(
            value is not None for value in web_auth_values
        ):
            msg = (
                "ADMIN_WEB_USERNAME, ADMIN_WEB_PASSWORD_HASH and "
                "ADMIN_WEB_TELEGRAM_ID must be set together"
            )
            raise ValueError(msg)
        if self.admin_web_password_hash is not None:
            encoded = self.admin_web_password_hash.get_secret_value()
            if not encoded.startswith("pbkdf2_sha256:"):
                msg = "ADMIN_WEB_PASSWORD_HASH must be a PBKDF2-SHA256 hash"
                raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a process-wide immutable-by-convention settings instance."""

    return Settings()

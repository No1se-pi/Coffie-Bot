import pytest
from pydantic import ValidationError

from app.core.config import AppEnvironment, Settings

VALID_BOT_TOKEN = "123456789:valid-production-token"
VALID_SESSION_TOKEN_PEPPER = "p" * 48


def test_production_rejects_development_auth() -> None:
    with pytest.raises(ValidationError, match="DEV_AUTH_ENABLED"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            bot_token=VALID_BOT_TOKEN,
            session_token_pepper=VALID_SESSION_TOKEN_PEPPER,
            dev_auth_enabled=True,
            dev_auth_telegram_id=1,
        )


@pytest.mark.parametrize(
    "bot_token",
    ["", "replace-with-bot-token", "123:", "abc:token", "123:with space"],
)
def test_production_rejects_invalid_bot_token(bot_token: str) -> None:
    with pytest.raises(ValidationError, match="BOT_TOKEN"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            bot_token=bot_token,
            session_token_pepper=VALID_SESSION_TOKEN_PEPPER,
        )


@pytest.mark.parametrize(
    "session_token_pepper",
    ["too-short", "x" * 47, "replace-with-" + ("x" * 48)],
)
def test_production_rejects_unsafe_session_token_pepper(session_token_pepper: str) -> None:
    with pytest.raises(ValidationError, match="SESSION_TOKEN_PEPPER"):
        Settings(
            app_env=AppEnvironment.PRODUCTION,
            bot_token=VALID_BOT_TOKEN,
            session_token_pepper=session_token_pepper,
        )


def test_production_accepts_non_placeholder_secrets() -> None:
    settings = Settings(
        app_env=AppEnvironment.PRODUCTION,
        bot_token=VALID_BOT_TOKEN,
        session_token_pepper=VALID_SESSION_TOKEN_PEPPER,
    )

    assert settings.telegram_init_data_ttl_seconds == 600


def test_blank_optional_browser_login_values_disable_it() -> None:
    settings = Settings(
        admin_web_username="",
        admin_web_password_hash="",
        admin_web_telegram_id="",  # type: ignore[arg-type]
    )

    assert settings.admin_web_username is None
    assert settings.admin_web_password_hash is None
    assert settings.admin_web_telegram_id is None


def test_browser_login_configuration_must_be_complete() -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(admin_web_username="owner")


def test_cors_origins_accept_comma_separated_environment_shape() -> None:
    settings = Settings(cors_origins="https://one.example, https://two.example")

    assert settings.cors_origins == ["https://one.example", "https://two.example"]


def test_default_database_url_does_not_embed_a_password() -> None:
    default_url = Settings.model_fields["database_url"].default

    assert default_url == "postgresql+asyncpg://coffie@localhost:5432/coffie"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("telegram_webapp_url", "http://coffee.example", "TELEGRAM_WEBAPP_URL"),
        ("telegram_webapp_url", "/mini-app", "TELEGRAM_WEBAPP_URL"),
        ("cors_origins", ["*"], "CORS_ORIGINS"),
        ("cors_origins", ["http://coffee.example"], "CORS_ORIGINS"),
    ],
)
def test_production_rejects_insecure_public_origins(
    field: str,
    value: str | list[str],
    error: str,
) -> None:
    values: dict[str, object] = {
        "app_env": AppEnvironment.PRODUCTION,
        "bot_token": VALID_BOT_TOKEN,
        "session_token_pepper": VALID_SESSION_TOKEN_PEPPER,
        field: value,
    }

    with pytest.raises(ValidationError, match=error):
        Settings(**values)  # type: ignore[arg-type]

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from app.api.routes.health import check_database_ready
from app.core.config import AppEnvironment, Settings
from app.core.errors import AppError, ErrorCode
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        log_json=False,
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    )
    application = create_app(settings=settings)

    async def database_is_ready() -> None:
        return None

    application.dependency_overrides[check_database_ready] = database_is_ready
    with TestClient(application) as test_client:
        yield test_client


def test_liveness_has_versioned_path_and_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-request-1"})

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-request-1"


def test_readiness_returns_ok_when_dependency_is_ready(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_readiness_uses_stable_error_contract(client: TestClient) -> None:
    async def database_is_unavailable() -> None:
        raise AppError(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Service dependency is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    application = cast(FastAPI, client.app)
    application.dependency_overrides[check_database_ready] = database_is_unavailable
    response = client.get("/api/v1/health/ready")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    payload = response.json()["error"]
    assert payload["code"] == "service_unavailable"
    assert payload["details"] == {}
    assert payload["request_id"] == response.headers["X-Request-ID"]


def test_unknown_route_uses_stable_error_contract(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["error"]["code"] == "not_found"

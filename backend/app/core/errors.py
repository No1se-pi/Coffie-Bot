"""Stable public API error contract and exception handlers."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class ErrorCode(StrEnum):
    AUTHENTICATION_REQUIRED = "authentication_required"
    FORBIDDEN = "forbidden"
    HTTP_ERROR = "http_error"
    INTERNAL_ERROR = "internal_error"
    INVALID_SESSION = "invalid_session"
    INVALID_TELEGRAM_DATA = "invalid_telegram_data"
    NOT_FOUND = "not_found"
    SERVICE_UNAVAILABLE = "service_unavailable"
    VALIDATION_ERROR = "validation_error"


class AppError(Exception):
    """An expected failure safe to expose through the public API."""

    def __init__(
        self,
        *,
        code: ErrorCode | str,
        message: str,
        status_code: int,
        details: Mapping[str, Any] | list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    details: Mapping[str, Any] | list[Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details or {},
                    "request_id": _request_id(request),
                }
            }
        ),
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            request,
            code=ErrorCode.VALIDATION_ERROR,
            message="Request validation failed",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            code = ErrorCode.NOT_FOUND
        elif exc.status_code == status.HTTP_401_UNAUTHORIZED:
            code = ErrorCode.AUTHENTICATION_REQUIRED
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            code = ErrorCode.FORBIDDEN
        else:
            code = ErrorCode.HTTP_ERROR
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return error_response(
            request,
            code=code,
            message=message,
            status_code=exc.status_code,
            details={} if isinstance(exc.detail, str) else exc.detail,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_request_error",
            request_id=_request_id(request),
            method=request.method,
            path=request.url.path,
            exc_info=exc,
        )
        return error_response(
            request,
            code=ErrorCode.INTERNAL_ERROR,
            message="Internal server error",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

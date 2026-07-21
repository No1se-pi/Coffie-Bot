"""Liveness and dependency readiness probes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.db.session import get_db_session

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/live", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def liveness() -> HealthResponse:
    return HealthResponse()


async def check_database_ready(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        raise AppError(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Service dependency is unavailable",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc


@router.get("/ready", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def readiness(_: Annotated[None, Depends(check_database_ready)]) -> HealthResponse:
    return HealthResponse()

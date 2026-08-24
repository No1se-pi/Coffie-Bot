"""Privileged preview/confirm API for irreversible customer account merges."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.customer_merges import CustomerMergeRepository
from app.schemas.customer_merges import (
    CustomerMergeConfirmRequest,
    CustomerMergeConfirmResponse,
    CustomerMergePreviewRequest,
    CustomerMergePreviewResponse,
    customer_merge_confirm_response,
    customer_merge_preview_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.customer_merges import CustomerMergeService, MergeRequestMetadata

router = APIRouter(prefix="/admin/customer-merge", tags=["admin-customer-merge"])

MergeActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_USERS_MANAGE)),
]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]


def _service(session: AsyncSession) -> CustomerMergeService:
    return CustomerMergeService(CustomerMergeRepository(session))


def _metadata(request: Request) -> MergeRequestMetadata:
    return MergeRequestMetadata(
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


@router.post("/preview", response_model=CustomerMergePreviewResponse)
async def preview_customer_merge(
    payload: CustomerMergePreviewRequest,
    actor: MergeActor,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomerMergePreviewResponse:
    preview = await _service(session).preview(
        actor,
        source_user_id=payload.source_user_id,
        canonical_user_id=payload.canonical_user_id,
    )
    return customer_merge_preview_response(preview)


@router.post("/confirm", response_model=CustomerMergeConfirmResponse)
async def confirm_customer_merge(
    payload: CustomerMergeConfirmRequest,
    request: Request,
    actor: MergeActor,
    idempotency_key: IdempotencyKey,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CustomerMergeConfirmResponse:
    result = await _service(session).confirm(
        actor,
        source_user_id=payload.source_user_id,
        canonical_user_id=payload.canonical_user_id,
        preview_hash=payload.preview_hash,
        reason=payload.reason,
        idempotency_key=str(idempotency_key),
        birthday_resolution=payload.birthday_resolution,
        metadata=_metadata(request),
    )
    return customer_merge_confirm_response(result)

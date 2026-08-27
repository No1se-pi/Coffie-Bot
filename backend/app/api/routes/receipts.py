"""Staff receipt create/edit/history endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.receipts import ReceiptRepository
from app.schemas.receipts import (
    ReceiptCreateRequest,
    ReceiptEditRequest,
    ReceiptListResponse,
    ReceiptResponse,
    receipt_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.receipts import ReceiptCreateCommand, ReceiptEditCommand, ReceiptService

router = APIRouter(prefix="/staff/receipts", tags=["staff-receipts"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
ReceiptReader = Annotated[Actor, Depends(require_permissions(PermissionCode.RECEIPTS_READ))]
ReceiptManager = Annotated[Actor, Depends(require_permissions(PermissionCode.RECEIPTS_MANAGE))]


def _service(session: AsyncSession) -> ReceiptService:
    return ReceiptService(ReceiptRepository(session))


@router.post("", response_model=ReceiptResponse, status_code=status.HTTP_201_CREATED)
async def create_receipt(
    payload: ReceiptCreateRequest,
    actor: ReceiptManager,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> ReceiptResponse:
    value = await _service(session).create(
        actor,
        ReceiptCreateCommand(
            user_id=payload.user_id,
            venue_id=payload.venue_id,
            amount_minor=payload.amount_minor,
            image_media_id=payload.image_media_id,
            receipt_number=payload.receipt_number,
            external_id=payload.external_id,
            fiscal_data=payload.fiscal_data,
            note=payload.note,
            source=payload.source,
        ),
        idempotency_key=str(idempotency_key),
    )
    return receipt_response(value)


@router.get("", response_model=ReceiptListResponse)
async def list_receipts(
    actor: ReceiptReader,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ReceiptListResponse:
    values = await _service(session).list(actor, limit=limit)
    return ReceiptListResponse(items=[receipt_response(value) for value in values])


@router.get("/{receipt_id}", response_model=ReceiptResponse)
async def get_receipt(
    receipt_id: UUID, actor: ReceiptReader, session: DatabaseSession
) -> ReceiptResponse:
    return receipt_response(await _service(session).get(actor, receipt_id))


@router.put("/{receipt_id}", response_model=ReceiptResponse)
async def edit_receipt(
    receipt_id: UUID,
    payload: ReceiptEditRequest,
    actor: ReceiptManager,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> ReceiptResponse:
    value = await _service(session).edit(
        actor,
        receipt_id,
        ReceiptEditCommand(
            image_media_id=payload.image_media_id,
            receipt_number=payload.receipt_number,
            external_id=payload.external_id,
            fiscal_data=payload.fiscal_data,
            note=payload.note,
        ),
        idempotency_key=str(idempotency_key),
    )
    return receipt_response(value)


@router.post("/{receipt_id}/cancel", response_model=ReceiptResponse)
async def cancel_receipt(
    receipt_id: UUID,
    actor: ReceiptManager,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> ReceiptResponse:
    return receipt_response(
        await _service(session).cancel(actor, receipt_id, idempotency_key=str(idempotency_key))
    )

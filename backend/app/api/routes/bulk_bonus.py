"""Admin-only bulk bonus preview and explicit idempotent confirmation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import PermissionCode
from app.repositories.bulk_bonus import BulkBonusRepository
from app.schemas.bulk_bonus import (
    BulkBonusConfirmRequest,
    BulkBonusPreviewResponse,
    BulkBonusRequest,
    BulkBonusResponse,
    bulk_bonus_response,
    preview_response,
)
from app.security.rbac import Actor, require_permissions
from app.services.bulk_bonus import BulkBonusCommand, BulkBonusService

router = APIRouter(prefix="/admin/bulk-bonus", tags=["admin-bulk-bonus"])
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]
BulkAdmin = Annotated[Actor, Depends(require_permissions(PermissionCode.ADMIN_BULK_BONUS_MANAGE))]


def _service(session: AsyncSession) -> BulkBonusService:
    return BulkBonusService(BulkBonusRepository(session))


def _command(payload: BulkBonusRequest) -> BulkBonusCommand:
    return BulkBonusCommand(
        customer_ids=frozenset(payload.customer_ids),
        points_per_user=payload.points_per_user,
        reason=payload.reason,
        venue_id=payload.venue_id,
    )


@router.post("/preview", response_model=BulkBonusPreviewResponse)
async def preview_bulk_bonus(
    payload: BulkBonusRequest, actor: BulkAdmin, session: DatabaseSession
) -> BulkBonusPreviewResponse:
    return preview_response(await _service(session).preview(actor, _command(payload)))


@router.post("/confirm", response_model=BulkBonusResponse)
async def confirm_bulk_bonus(
    payload: BulkBonusConfirmRequest,
    actor: BulkAdmin,
    session: DatabaseSession,
    idempotency_key: IdempotencyKey,
) -> BulkBonusResponse:
    return bulk_bonus_response(
        await _service(session).confirm(
            actor,
            _command(payload),
            preview_hash=payload.preview_hash,
            idempotency_key=str(idempotency_key),
        )
    )

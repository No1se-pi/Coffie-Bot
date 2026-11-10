"""Transport for employee benefit configuration and purchases."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.enums import Role
from app.repositories.staff_benefits import StaffBenefitRepository
from app.schemas.identity import PointsMenuPurchaseResponse
from app.schemas.pricing import ModifierSelectionRequest
from app.security.rbac import Actor, get_current_actor, require_roles
from app.services.pricing import RequestedModifier
from app.services.staff_benefits import StaffBenefitService

IdempotencyKey = Annotated[UUID, Header(alias="Idempotency-Key")]

router = APIRouter(tags=["staff-benefits"])
Owner = Annotated[Actor, Depends(require_roles(Role.OWNER))]
Member = Annotated[Actor, Depends(get_current_actor)]
Session = Annotated[AsyncSession, Depends(get_db_session)]


class BenefitView(BaseModel):
    staff_id: UUID | None = None
    enabled: bool = False
    monthly_points: int = 3000
    all_items: bool = True
    item_ids: list[UUID] = Field(default_factory=list)
    balance_points: int = 0
    expires_at: datetime | None = None


class BenefitConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    monthly_points: int = Field(gt=0, le=1_000_000)
    all_items: bool
    item_ids: list[UUID] = Field(default_factory=list, max_length=1000)


class BenefitPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: UUID
    modifiers: list[ModifierSelectionRequest] = Field(default_factory=list, max_length=50)


@router.get("/me/staff-benefits", response_model=BenefitView)
async def my_benefits(actor: Member, session: Session) -> BenefitView:
    if actor.staff_member_id is None or actor.role == Role.COURIER:
        return BenefitView()
    return BenefitView(
        **await StaffBenefitService(StaffBenefitRepository(session)).view(actor.staff_member_id)
    )


@router.get("/admin/staff/{staff_id}/benefits", response_model=BenefitView)
async def employee_benefits(staff_id: UUID, actor: Owner, session: Session) -> BenefitView:
    return BenefitView(**await StaffBenefitService(StaffBenefitRepository(session)).view(staff_id))


@router.put("/admin/staff/{staff_id}/benefits", response_model=BenefitView)
async def configure_benefits(
    staff_id: UUID, payload: BenefitConfiguration, actor: Owner, session: Session
) -> BenefitView:
    result = await StaffBenefitService(StaffBenefitRepository(session)).configure(
        actor, staff_id, **payload.model_dump()
    )
    return BenefitView(**result)


@router.post("/me/staff-benefits/purchases", response_model=PointsMenuPurchaseResponse)
async def purchase(
    payload: BenefitPurchase, actor: Member, session: Session, idempotency_key: IdempotencyKey
) -> PointsMenuPurchaseResponse:
    result = await StaffBenefitService(StaffBenefitRepository(session)).purchase(
        actor,
        item_id=payload.item_id,
        modifiers=tuple(
            RequestedModifier(option_id=m.option_id, quantity=m.quantity) for m in payload.modifiers
        ),
        key=str(idempotency_key),
    )
    return PointsMenuPurchaseResponse(**result)

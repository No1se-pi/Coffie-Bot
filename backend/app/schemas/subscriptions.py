"""API schemas for pass templates, customer passes, and usages."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.engagement import CustomerPass, PassPurchase, PassUsage
from app.models.enums import PassStatus, PaymentMethod
from app.repositories.subscriptions import PassRecord, TemplateAccess
from app.services.subscriptions import PassOutcome, UsageOutcome


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PassTemplateCreateRequest(ApiSchema):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    image_media_id: UUID | None = None
    total_uses: int = Field(ge=1, le=10000)
    validity_days: int = Field(ge=1, le=3650)
    price_minor: int = Field(default=0, ge=0)
    purchase_enabled: bool = False
    venue_ids: set[UUID] = Field(default_factory=set)
    category_ids: set[UUID] = Field(default_factory=set)
    item_ids: set[UUID] = Field(default_factory=set)


class PassTemplateUpdateRequest(PassTemplateCreateRequest):
    """All editable fields are replaced together to keep scope changes explicit."""


class PassIssueRequest(ApiSchema):
    user_id: UUID
    template_id: UUID


class PassUseRequest(ApiSchema):
    venue_id: UUID
    item_id: UUID


class PassCancelRequest(ApiSchema):
    reason: str = Field(min_length=3, max_length=2000)


class PassTemplateResponse(ApiSchema):
    id: UUID
    name: str
    description: str
    image_media_id: UUID | None
    image_url: str | None
    total_uses: int
    validity_days: int
    price_minor: int
    purchase_enabled: bool
    venue_ids: list[UUID]
    category_ids: list[UUID]
    item_ids: list[UUID]
    is_active: bool
    created_at: datetime


class PassTemplateListResponse(ApiSchema):
    items: list[PassTemplateResponse]


class PassUsageResponse(ApiSchema):
    id: UUID
    pass_id: UUID
    venue_id: UUID
    item_id: UUID
    uses_before: int
    uses_after: int
    created_at: datetime
    replay: bool = False


class CustomerPassResponse(ApiSchema):
    id: UUID
    template_id: UUID
    user_id: UUID
    name: str
    description: str
    image_media_id: UUID | None
    image_url: str | None
    total_uses: int
    remaining_uses: int
    status: PassStatus
    issued_at: datetime
    expires_at: datetime
    usage_count: int = 0
    replay: bool = False


class CustomerPassListResponse(ApiSchema):
    items: list[CustomerPassResponse]


class PassPurchaseCreateRequest(ApiSchema):
    template_id: UUID
    payment_method: PaymentMethod = PaymentMethod.CARD_ON_RECEIPT


class PassPurchaseResponse(ApiSchema):
    id: UUID
    number: int
    template_id: UUID
    user_id: UUID
    name: str
    price_minor: int
    payment_method: PaymentMethod
    status: str
    customer_pass_id: UUID | None
    created_at: datetime
    paid_at: datetime | None


class PassPurchaseListResponse(ApiSchema):
    items: list[PassPurchaseResponse]


def template_response(value: TemplateAccess) -> PassTemplateResponse:
    template = value.template
    return PassTemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        image_media_id=template.image_media_id,
        image_url=(f"/api/v1/media/{template.image_media_id}" if template.image_media_id else None),
        total_uses=template.total_uses,
        validity_days=template.validity_days,
        price_minor=template.price_minor,
        purchase_enabled=template.purchase_enabled,
        venue_ids=sorted(value.venue_ids),
        category_ids=sorted(value.category_ids),
        item_ids=sorted(value.item_ids),
        is_active=template.is_active,
        created_at=template.created_at,
    )


def purchase_response(value: PassPurchase) -> PassPurchaseResponse:
    return PassPurchaseResponse(
        id=value.id,
        number=value.number,
        template_id=value.template_id,
        user_id=value.user_id,
        name=value.name_snapshot,
        price_minor=value.price_minor,
        payment_method=value.payment_method,
        status=value.status,
        customer_pass_id=value.customer_pass_id,
        created_at=value.created_at,
        paid_at=value.paid_at,
    )


def pass_response(
    value: CustomerPass | PassRecord | PassOutcome, *, replay: bool = False
) -> CustomerPassResponse:
    usage_count = 0
    if isinstance(value, PassRecord):
        customer_pass = value.customer_pass
        usage_count = value.usage_count
    elif isinstance(value, PassOutcome):
        customer_pass = value.value
        replay = value.replay
    else:
        customer_pass = value
    effective_status = customer_pass.status
    if effective_status is PassStatus.ACTIVE and customer_pass.expires_at <= datetime.now(UTC):
        effective_status = PassStatus.EXPIRED
    return CustomerPassResponse(
        id=customer_pass.id,
        template_id=customer_pass.template_id,
        user_id=customer_pass.user_id,
        name=customer_pass.name_snapshot,
        description=customer_pass.description_snapshot,
        image_media_id=customer_pass.image_media_id_snapshot,
        image_url=(
            f"/api/v1/media/{customer_pass.image_media_id_snapshot}"
            if customer_pass.image_media_id_snapshot
            else None
        ),
        total_uses=customer_pass.total_uses,
        remaining_uses=customer_pass.remaining_uses,
        status=effective_status,
        issued_at=customer_pass.issued_at,
        expires_at=customer_pass.expires_at,
        usage_count=usage_count,
        replay=replay,
    )


def usage_response(value: PassUsage | UsageOutcome) -> PassUsageResponse:
    replay = isinstance(value, UsageOutcome) and value.replay
    usage = value.value if isinstance(value, UsageOutcome) else value
    return PassUsageResponse(
        id=usage.id,
        pass_id=usage.pass_id,
        venue_id=usage.venue_id,
        item_id=usage.item_id,
        uses_before=usage.uses_before,
        uses_after=usage.uses_after,
        created_at=usage.created_at,
        replay=replay,
    )

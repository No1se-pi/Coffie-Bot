"""Owner/admin delivery settings, zones, and pickup location controls."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.content import Location
from app.models.enums import PermissionCode
from app.models.orders import DeliverySettings, DeliveryZone
from app.repositories.orders import OrderRepository
from app.schemas.delivery_admin import (
    DeliverySettingsResponse,
    DeliverySettingsUpdate,
    DeliveryZoneAdminResponse,
    DeliveryZoneCreate,
    DeliveryZoneListResponse,
    DeliveryZoneUpdate,
    LocationCreate,
    LocationFulfillmentListResponse,
    LocationFulfillmentResponse,
    LocationFulfillmentUpdate,
)
from app.security.rbac import Actor, require_permissions
from app.services.delivery_admin import DeliveryAdminService

router = APIRouter(prefix="/admin/delivery", tags=["admin-delivery"])
DeliveryActor = Annotated[
    Actor,
    Depends(require_permissions(PermissionCode.ADMIN_DELIVERY_MANAGE)),
]
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


def _service(session: AsyncSession) -> DeliveryAdminService:
    return DeliveryAdminService(OrderRepository(session))


def _settings(value: DeliverySettings) -> DeliverySettingsResponse:
    return DeliverySettingsResponse(
        id=value.id,
        delivery_enabled=value.delivery_enabled,
        minimum_order_minor=value.minimum_order_minor,
        fixed_fee_minor=value.fixed_fee_minor,
        free_delivery_threshold_minor=value.free_delivery_threshold_minor,
        scheduling_allowed=value.scheduling_allowed,
        earliest_preparation_minutes=value.earliest_preparation_minutes,
        operating_hours=value.operating_hours,
        default_pickup_location_id=value.default_pickup_location_id,
        consolidation_location_id=value.consolidation_location_id,
    )


def _zone(value: DeliveryZone) -> DeliveryZoneAdminResponse:
    return DeliveryZoneAdminResponse(
        id=value.id,
        name=value.name,
        description=value.description,
        fee_minor=value.fee_minor,
        minimum_order_minor=value.minimum_order_minor,
        location_id=value.location_id,
        radius_meters=value.radius_meters,
        is_active=value.is_active,
        sort_order=value.sort_order,
        archived=value.archived_at is not None,
    )


def _location(value: Location) -> LocationFulfillmentResponse:
    return LocationFulfillmentResponse(
        id=value.id,
        venue_id=value.venue_id,
        slug=value.slug,
        name=value.name,
        address=value.address,
        phone=value.phone,
        map_url=value.map_url,
        image_media_id=value.image_media_id,
        latitude=float(value.latitude) if value.latitude is not None else None,
        longitude=float(value.longitude) if value.longitude is not None else None,
        timezone=value.timezone,
        is_active=value.is_active,
        pickup_enabled=value.pickup_enabled,
        consolidation_enabled=value.consolidation_enabled,
        pickup_comment=value.pickup_comment,
        preparation_minutes=value.preparation_minutes,
    )


@router.get("/settings", response_model=DeliverySettingsResponse)
async def get_settings(actor: DeliveryActor, session: DatabaseSession) -> DeliverySettingsResponse:
    return _settings(await _service(session).get_settings(actor))


@router.put("/settings", response_model=DeliverySettingsResponse)
async def update_settings(
    payload: DeliverySettingsUpdate,
    actor: DeliveryActor,
    session: DatabaseSession,
) -> DeliverySettingsResponse:
    return _settings(await _service(session).update_settings(actor, payload.model_dump()))


@router.get("/zones", response_model=DeliveryZoneListResponse)
async def list_zones(actor: DeliveryActor, session: DatabaseSession) -> DeliveryZoneListResponse:
    values = await _service(session).list_zones(actor)
    return DeliveryZoneListResponse(items=[_zone(value) for value in values])


@router.post(
    "/zones",
    response_model=DeliveryZoneAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_zone(
    payload: DeliveryZoneCreate,
    actor: DeliveryActor,
    session: DatabaseSession,
) -> DeliveryZoneAdminResponse:
    return _zone(await _service(session).create_zone(actor, payload.model_dump()))


@router.put("/zones/{zone_id}", response_model=DeliveryZoneAdminResponse)
async def update_zone(
    zone_id: UUID,
    payload: DeliveryZoneUpdate,
    actor: DeliveryActor,
    session: DatabaseSession,
) -> DeliveryZoneAdminResponse:
    return _zone(await _service(session).update_zone(actor, zone_id, payload.model_dump()))


@router.post("/zones/{zone_id}/archive", response_model=DeliveryZoneAdminResponse)
async def archive_zone(
    zone_id: UUID,
    actor: DeliveryActor,
    session: DatabaseSession,
) -> DeliveryZoneAdminResponse:
    return _zone(await _service(session).archive_zone(actor, zone_id))


@router.get("/locations", response_model=LocationFulfillmentListResponse)
async def list_locations(
    actor: DeliveryActor, session: DatabaseSession
) -> LocationFulfillmentListResponse:
    values = await _service(session).list_locations(actor)
    return LocationFulfillmentListResponse(items=[_location(value) for value in values])


@router.post(
    "/locations",
    response_model=LocationFulfillmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_location(
    payload: LocationCreate,
    actor: DeliveryActor,
    session: DatabaseSession,
) -> LocationFulfillmentResponse:
    return _location(await _service(session).create_location(actor, payload.model_dump()))


@router.put("/locations/{location_id}", response_model=LocationFulfillmentResponse)
async def update_location(
    location_id: UUID,
    payload: LocationFulfillmentUpdate,
    actor: DeliveryActor,
    session: DatabaseSession,
) -> LocationFulfillmentResponse:
    return _location(
        await _service(session).update_location(
            actor, location_id, payload.model_dump(exclude_unset=True)
        )
    )

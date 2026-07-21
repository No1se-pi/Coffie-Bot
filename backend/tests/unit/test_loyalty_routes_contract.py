from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.routes.admin_events import router as admin_events_router
from app.api.routes.admin_users import router as admin_users_router
from app.api.routes.staff import router as staff_router
from app.schemas.loyalty import CardLookupResponse


def test_loyalty_route_paths_match_api_contract() -> None:
    paths = {
        route.path
        for router in (staff_router, admin_users_router, admin_events_router)
        for route in router.routes
        if isinstance(route, APIRoute)
    }

    assert {
        "/staff/cards/lookup",
        "/staff/operations/accrual/preview",
        "/staff/operations/accrual",
        "/staff/operations/redemption/preview",
        "/staff/operations/redemption",
        "/staff/operations/visits",
        "/staff/operations/stamps",
        "/staff/rewards/{reward_id}/redeem",
        "/staff/operations/{operation_id}/reverse",
        "/staff/operations/recent",
        "/admin/users",
        "/admin/users/{user_id}/adjustments",
        "/admin/users/{user_id}/block",
        "/admin/users/{user_id}/unblock",
        "/admin/users/{user_id}/cards/reissue",
        "/admin/events",
    }.issubset(paths)


def test_confirm_routes_require_uuid_idempotency_header() -> None:
    app = FastAPI()
    app.include_router(staff_router)
    app.include_router(admin_users_router)
    schema = app.openapi()

    for path in (
        "/staff/operations/accrual",
        "/staff/operations/redemption",
        "/staff/operations/visits",
        "/staff/operations/stamps",
        "/admin/users/{user_id}/adjustments",
        "/admin/users/{user_id}/cards/reissue",
    ):
        parameters = schema["paths"][path]["post"]["parameters"]
        header = next(item for item in parameters if item["name"] == "Idempotency-Key")
        assert header["required"] is True
        assert header["schema"]["format"] == "uuid"


def test_card_lookup_does_not_return_qr_secret() -> None:
    assert "qr_token" not in CardLookupResponse.model_fields
    assert "qr_payload" not in CardLookupResponse.model_fields

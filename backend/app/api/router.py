"""API v1 router registry."""

from fastapi import APIRouter

from app.api.routes.admin_broadcasts import router as admin_broadcasts_router
from app.api.routes.admin_content import router as admin_content_router
from app.api.routes.admin_events import router as admin_events_router
from app.api.routes.admin_staff import router as admin_staff_router
from app.api.routes.admin_users import router as admin_users_router
from app.api.routes.admin_venues import router as admin_venues_router
from app.api.routes.auth import router as auth_router
from app.api.routes.couriers import router as couriers_router
from app.api.routes.customer_merges import router as customer_merges_router
from app.api.routes.customers import router as customers_router
from app.api.routes.delivery_admin import router as delivery_admin_router
from app.api.routes.health import router as health_router
from app.api.routes.loyalty_v2 import admin_router as loyalty_v2_admin_router
from app.api.routes.loyalty_v2 import me_router as loyalty_v2_me_router
from app.api.routes.me import router as me_router
from app.api.routes.media import router as media_router
from app.api.routes.menu_pricing_admin import router as menu_pricing_admin_router
from app.api.routes.orders import router as orders_router
from app.api.routes.pricing import router as pricing_router
from app.api.routes.public import router as public_router
from app.api.routes.receipts import router as receipts_router
from app.api.routes.staff import router as staff_router
from app.api.routes.staff_profile import router as staff_profile_router
from app.api.routes.venues import router as venues_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(customers_router)
api_v1_router.include_router(me_router)
api_v1_router.include_router(loyalty_v2_me_router)
api_v1_router.include_router(public_router)
api_v1_router.include_router(pricing_router)
api_v1_router.include_router(venues_router)
api_v1_router.include_router(staff_router)
api_v1_router.include_router(staff_profile_router)
api_v1_router.include_router(admin_users_router)
api_v1_router.include_router(admin_events_router)
api_v1_router.include_router(admin_broadcasts_router)
api_v1_router.include_router(admin_content_router)
api_v1_router.include_router(admin_staff_router)
api_v1_router.include_router(admin_venues_router)
api_v1_router.include_router(menu_pricing_admin_router)
api_v1_router.include_router(orders_router)
api_v1_router.include_router(couriers_router)
api_v1_router.include_router(receipts_router)
api_v1_router.include_router(loyalty_v2_admin_router)
api_v1_router.include_router(customer_merges_router)
api_v1_router.include_router(delivery_admin_router)
api_v1_router.include_router(media_router)

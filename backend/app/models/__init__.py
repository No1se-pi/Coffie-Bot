"""Complete SQLAlchemy model registry used by runtime and Alembic."""

from app.models.access import Session, StaffInvite, StaffMember, StaffPermission, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import AppSetting, Location, MenuCategory, MenuItem, Promotion
from app.models.delivery import Broadcast, BroadcastDelivery, NotificationOutbox
from app.models.loyalty import (
    LoyaltyOperation,
    LoyaltySettings,
    PointTransaction,
    Reward,
    RewardTemplate,
    StampTransaction,
    UserLoyaltyState,
    Visit,
)
from app.models.media import MediaFile
from app.models.staff import FeedbackItem, StaffTipProfile

__all__ = [
    "AppSetting",
    "AuditEvent",
    "Broadcast",
    "BroadcastDelivery",
    "FeedbackItem",
    "Location",
    "LoyaltyOperation",
    "LoyaltySettings",
    "MediaFile",
    "MenuCategory",
    "MenuItem",
    "NotificationOutbox",
    "PointTransaction",
    "Promotion",
    "Reward",
    "RewardTemplate",
    "Session",
    "StaffInvite",
    "StaffMember",
    "StaffPermission",
    "StaffTipProfile",
    "StampTransaction",
    "User",
    "UserCard",
    "UserLoyaltyState",
    "Visit",
]

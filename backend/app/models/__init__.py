"""Complete SQLAlchemy model registry used by runtime and Alembic."""

from app.models.access import Session, StaffInvite, StaffMember, StaffPermission, User
from app.models.audit import AuditEvent
from app.models.cards import UserCard
from app.models.content import AppSetting, Location, MenuCategory, MenuItem, Promotion, Venue
from app.models.customers import CustomerIdentity, CustomerMerge
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
from app.models.loyalty_v2 import (
    AccountMergeLotRoute,
    BirthdayPromotionVenue,
    LoyaltyWallet,
    PointAllocation,
    PointLot,
    PointLotRoute,
    WalletModeSwitch,
    WalletTransfer,
)
from app.models.media import MediaFile
from app.models.staff import FeedbackItem, StaffTipProfile

__all__ = [
    "AccountMergeLotRoute",
    "AppSetting",
    "AuditEvent",
    "BirthdayPromotionVenue",
    "Broadcast",
    "BroadcastDelivery",
    "CustomerIdentity",
    "CustomerMerge",
    "FeedbackItem",
    "Location",
    "LoyaltyOperation",
    "LoyaltySettings",
    "LoyaltyWallet",
    "MediaFile",
    "MenuCategory",
    "MenuItem",
    "NotificationOutbox",
    "PointAllocation",
    "PointLot",
    "PointLotRoute",
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
    "Venue",
    "Visit",
    "WalletModeSwitch",
    "WalletTransfer",
]

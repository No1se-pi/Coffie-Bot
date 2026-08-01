"""Stable string values persisted by the relational model and exposed by API v1."""

from enum import StrEnum


class Role(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"
    ADMIN = "admin"
    OWNER = "owner"


class PermissionCode(StrEnum):
    CARD_LOOKUP = "card.lookup"
    POINTS_ACCRUE = "points.accrue"
    POINTS_REDEEM = "points.redeem"
    VISITS_MARK = "visits.mark"
    STAMPS_ADD = "stamps.add"
    REWARDS_REDEEM = "rewards.redeem"
    OWN_OPERATIONS_REVERSE = "operations.reverse_own"
    OWN_TIP_PROFILE_MANAGE = "tip_profile.manage_own"
    ADMIN_USERS_READ = "admin.users.read"
    ADMIN_USERS_MANAGE = "admin.users.manage"
    ADMIN_STAFF_MANAGE = "admin.staff.manage"
    ADMIN_EVENTS_READ = "admin.events.read"
    ADMIN_SETTINGS_MANAGE = "admin.settings.manage"
    ADMIN_CONTENT_MANAGE = "admin.content.manage"
    ADMIN_BROADCASTS_MANAGE = "admin.broadcasts.manage"
    ADMIN_FEEDBACK_MANAGE = "admin.feedback.manage"
    OWNER_ADMINS_MANAGE = "owner.admins.manage"
    OWNER_EXPORT_DATA = "owner.export_data"
    OWNER_CRITICAL_SETTINGS = "owner.critical_settings"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    INACTIVE = "inactive"
    ANONYMIZED = "anonymized"


class CardStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class OperationStatus(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    REJECTED = "rejected"
    REVERSED = "reversed"
    FAILED = "failed"


class LoyaltyOperationType(StrEnum):
    PURCHASE_ACCRUAL = "purchase_accrual"
    POINTS_REDEMPTION = "points_redemption"
    POINTS_PRODUCT_PURCHASE = "points_product_purchase"
    WELCOME_BONUS = "welcome_bonus"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    OPERATION_REVERSAL = "operation_reversal"
    POINTS_EXPIRATION = "points_expiration"
    VISIT_MARK = "visit_mark"
    STAMP_ADDED = "stamp_added"
    REWARD_CREATED = "reward_created"
    REWARD_REDEEMED = "reward_redeemed"
    REWARD_CANCELLED = "reward_cancelled"


class RoundingMode(StrEnum):
    FLOOR = "floor"
    HALF_UP = "half_up"
    CEILING = "ceiling"


class RewardType(StrEnum):
    FREE_PRODUCT = "free_product"
    PERCENT_DISCOUNT = "percent_discount"
    FIXED_DISCOUNT = "fixed_discount"
    FREE_OPTION = "free_option"
    TEXT = "text"
    POINTS = "points"


class RewardStatus(StrEnum):
    ACTIVE = "active"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class LoyaltyProgram(StrEnum):
    POINTS = "points"
    VISITS = "visits"
    STAMPS = "stamps"
    MANUAL = "manual"


class PromotionStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TipProfileStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    HIDDEN = "hidden"


class FeedbackCategory(StrEnum):
    SERVICE = "service"
    FOOD_AND_DRINKS = "food_and_drinks"
    APPLICATION = "application"
    LOYALTY = "loyalty"
    OTHER = "other"


class FeedbackStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ARCHIVED = "archived"


class BroadcastStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class MediaStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class AuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

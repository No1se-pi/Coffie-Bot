"""Stable string values persisted by the relational model and exposed by API v1."""

from enum import StrEnum


class Role(StrEnum):
    CUSTOMER = "customer"
    STAFF = "staff"
    ADMIN = "admin"
    OWNER = "owner"


class IdentityProvider(StrEnum):
    """Authentication/contact namespaces attached to a customer profile."""

    TELEGRAM = "telegram"
    PHONE = "phone"
    MAX = "max"


class PermissionCode(StrEnum):
    CARD_LOOKUP = "card.lookup"
    CUSTOMERS_CREATE = "customers.create"
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
    MERGED = "merged"


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
    ACCOUNT_MERGE_DEBIT = "account_merge_debit"
    ACCOUNT_MERGE_CREDIT = "account_merge_credit"
    WALLET_TRANSFER_DEBIT = "wallet_transfer_debit"
    WALLET_TRANSFER_CREDIT = "wallet_transfer_credit"


class WalletMode(StrEnum):
    SHARED = "shared"
    SEPARATE = "separate"


class PointLotSourceType(StrEnum):
    """Stable reasons why a point lot was minted."""

    OPENING_BALANCE = "opening_balance"
    ACCRUAL = "accrual"
    WELCOME_BONUS = "welcome_bonus"
    REWARD_BONUS = "reward_bonus"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    REVERSAL = "reversal"
    WALLET_TRANSFER = "wallet_transfer"
    ACCOUNT_MERGE = "account_merge"


class PointAllocationType(StrEnum):
    """Append-only reasons why a lot's remaining amount changed."""

    SPEND = "spend"
    EXPIRY = "expiry"
    REVERSAL_DEBIT = "reversal_debit"
    REVERSAL_RESTORE = "reversal_restore"
    WALLET_TRANSFER_DEBIT = "wallet_transfer_debit"
    ACCOUNT_MERGE_DEBIT = "account_merge_debit"


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


class PromotionActionType(StrEnum):
    """Supported pricing actions; intentionally small and auditable."""

    PERCENT_DISCOUNT = "percent_discount"
    FIXED_DISCOUNT = "fixed_discount"


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

export type Role = "customer" | "staff" | "admin" | "owner";

export interface Actor {
  id: string;
  telegram_id: string;
  display_name: string;
  username?: string | null;
  photo_url?: string | null;
  role: Role;
  available_roles: Role[];
  permissions: string[];
}

export interface AuthSession {
  access_token: string;
  expires_at: string;
  actor: Actor;
}

export interface ListResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface CardData {
  user_id: string;
  display_name: string;
  qr_payload: string;
  short_code: string;
  balance_points: number;
  currency_name: string;
  visit_streak: number;
  visit_goal: number;
  stamps: number;
  stamp_goal: number;
  blocked: boolean;
  updated_at: string;
}

export type HistoryType =
  | "purchase_accrual"
  | "points_redemption"
  | "welcome_bonus"
  | "points_expiration"
  | "visit_mark"
  | "stamp_added"
  | "reward_created"
  | "reward_redeemed"
  | "reward_cancelled"
  | "admin_adjustment"
  | "operation_reversal";

export interface HistoryItem {
  id: string;
  type: HistoryType;
  description: string;
  delta_points?: number | null;
  balance_after?: number | null;
  created_at: string;
  status: "completed" | "pending" | "reversed" | "failed";
}

export interface Reward {
  id: string;
  title: string;
  description: string;
  image_url?: string | null;
  type:
    | "free_product"
    | "percent_discount"
    | "fixed_discount"
    | "free_option"
    | "text";
  status: "active" | "redeemed" | "expired" | "cancelled";
  expires_at?: string | null;
  created_at: string;
  redeemed_at?: string | null;
}

export interface Promotion {
  id: string;
  title: string;
  text: string;
  image_url?: string | null;
  button_label?: string | null;
  button_url?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  status: "draft" | "scheduled" | "published" | "archived";
  published_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface PromotionDraft {
  title: string;
  text: string;
  button_label?: string | null;
  button_url?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
}

export interface MenuCategory {
  id: string;
  name: string;
  description?: string | null;
  sort_order: number;
  visible: boolean;
  archived_at?: string | null;
}

export interface MenuCategoryDraft {
  name: string;
  description?: string | null;
  sort_order: number;
  visible: boolean;
}

export interface MenuItem {
  id: string;
  category_id: string;
  name: string;
  description?: string | null;
  image_url?: string | null;
  price_minor: number;
  old_price_minor?: number | null;
  composition?: string | null;
  volume?: string | null;
  labels?: string[];
  available: boolean;
  visible: boolean;
  sort_order?: number;
  archived_at?: string | null;
}

export interface MenuItemDraft {
  category_id: string;
  name: string;
  description?: string | null;
  price_minor: number;
  old_price_minor?: number | null;
  composition?: string | null;
  volume?: string | null;
  labels: string[];
  available: boolean;
  visible: boolean;
  sort_order: number;
}

export interface ContactLocation {
  id: string;
  name: string;
  address: string;
  hours: string;
  phone?: string | null;
  map_url?: string | null;
}

export interface ContactsData {
  coffee_shop_name: string;
  description: string;
  support_contact?: string | null;
  privacy_policy: string;
  locations: ContactLocation[];
}

export interface StaffProfile {
  id: string;
  display_name: string;
  position: string;
  bio?: string | null;
  photo_url?: string | null;
  tip_url?: string | null;
  tip_qr_url?: string | null;
}

export interface HomeData {
  card: CardData;
  active_rewards: Reward[];
  promotions: Promotion[];
}

export interface PublicMoreData {
  contacts: ContactsData;
  staff: StaffProfile[];
  promotions: Promotion[];
}

export interface StaffClient {
  user_id: string;
  display_name: string;
  photo_url?: string | null;
  short_code: string;
  masked_short_code: string;
  balance_points: number;
  currency_name: string;
  visit_streak: number;
  visit_goal: number;
  stamps: number;
  stamp_goal: number;
  available_rewards: Reward[];
  blocked: boolean;
  suspicious: boolean;
  recent_operations: HistoryItem[];
}

export interface AccrualPreview {
  user_id: string;
  customer_name: string;
  purchase_amount_minor: number;
  points_to_accrue: number;
  balance_before: number;
  balance_after: number;
  requires_approval: boolean;
}

export interface RedemptionPreview {
  user_id: string;
  customer_name: string;
  purchase_amount_minor: number;
  requested_points: number;
  discount_minor: number;
  maximum_points_for_purchase: number;
  balance_before: number;
  balance_after: number;
}

export interface OperationResult {
  operation_id: string;
  status: "completed" | "pending" | "reversed" | "failed";
  delta_points: number;
  balance_after: number | null;
  created_at: string;
  operation_type?: HistoryType;
  streak_after?: number | null;
  stamps_after?: number | null;
  reward_ids?: string[];
  audit_message?: string;
}

export interface TipProfile {
  display_name: string;
  position: string;
  bio: string;
  tip_url: string;
  tip_qr_url?: string | null;
  moderation_status: "draft" | "pending_review" | "approved" | "hidden";
}

export interface AdminUserListItem {
  id: string;
  telegram_id: string | number;
  display_name: string;
  username?: string | null;
  status: "active" | "blocked";
  created_at: string;
  last_seen_at?: string | null;
}

export interface AdminUser extends AdminUserListItem {
  short_code: string;
  balance_points: number;
  visit_streak: number;
  stamps: number;
  active_rewards: number;
  active_card?: boolean;
}

export interface AuditEvent {
  id: string;
  type: string;
  message: string;
  actor_name?: string | null;
  subject_name?: string | null;
  severity: "info" | "warning" | "critical";
  suspicious: boolean;
  created_at: string;
}

export type FeedbackCategory =
  "service" | "food_and_drinks" | "application" | "loyalty" | "other";

export type FeedbackStatus = "new" | "in_progress" | "resolved" | "archived";

export interface AdminFeedback {
  id: string;
  user_id: string;
  user_display_name: string;
  rating: number;
  category: FeedbackCategory;
  message: string;
  may_contact: boolean;
  status: FeedbackStatus;
  assigned_to_staff_id?: string | null;
  internal_note?: string | null;
  resolved_at?: string | null;
  created_at: string;
}

export type OperationalPermission =
  | "card.lookup"
  | "points.accrue"
  | "points.redeem"
  | "visits.mark"
  | "stamps.add"
  | "rewards.redeem"
  | "operations.reverse_own"
  | "tip_profile.manage_own";

export interface PermissionOverride {
  permission: OperationalPermission;
  allowed: boolean;
}

export interface AdminStaffMember {
  id: string;
  user_id: string;
  telegram_id: string | number;
  username?: string | null;
  display_name: string;
  position?: string | null;
  bio?: string | null;
  role: Exclude<Role, "customer">;
  is_active: boolean;
  can_edit_tip_profile: boolean;
  permissions: PermissionOverride[];
  created_at: string;
  updated_at: string;
}

export interface StaffMemberDraft {
  display_name?: string | null;
  position?: string | null;
  bio?: string | null;
  can_edit_tip_profile: boolean;
  permissions: Partial<Record<OperationalPermission, boolean>>;
}

export interface LoyaltySettings {
  points_enabled: boolean;
  currency_name: string;
  rubles_per_point: number;
  redemption_rubles_per_point: number;
  minimum_purchase_minor: number;
  maximum_purchase_minor: number;
  rounding: "floor" | "half_up" | "ceiling";
  max_redemption_percent: number;
  minimum_redemption_points: number;
  welcome_bonus_points: number;
  points_validity_days: number | null;
  daily_accrual_limit_points: number | null;
  operation_accrual_limit_points: number | null;
  large_operation_threshold_minor: number | null;
  large_operation_requires_approval: boolean;
  visit_enabled: boolean;
  visit_goal: number;
  visits_must_be_consecutive: boolean;
  visit_daily_limit: number;
  timezone: string;
  business_day_boundary: string;
  visit_allowed_misses: number;
  visit_reset_on_miss: boolean;
  visit_reward_validity_days: number | null;
  visit_restart_cycle: boolean;
  stamps_enabled: boolean;
  stamp_goal: number;
  stamps_per_purchase: number;
  stamp_operation_limit: number;
  stamp_reward_validity_days: number | null;
  reset_stamps_after_reward: boolean;
}

export interface AdminOverview {
  users_total: number;
  blocked_users: number;
  suspicious_events: number;
  active_promotions: number;
  recent_events: AuditEvent[];
}

export interface AdjustmentPreview {
  user_id: string;
  customer_name: string;
  delta_points: number;
  balance_before: number;
  balance_after: number;
  reason: string;
}

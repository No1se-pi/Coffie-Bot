export type Role = "customer" | "staff" | "courier" | "admin" | "owner";

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

export interface Venue {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  telegram: string | null;
  logo_url: string | null;
  sort_order: number;
}

export type LoyaltyWalletMode = "shared" | "separate";

export interface LoyaltyVenueRef {
  id: string;
  name: string;
  available: boolean;
}

export interface CustomerWalletEntry {
  id: string;
  venue: LoyaltyVenueRef | null;
  balance_points: number;
  expiring_points: number;
  expires_at: string | null;
}

export interface CustomerWalletSummary {
  mode: LoyaltyWalletMode;
  total_balance_points: number;
  point_value_minor: number;
  max_redemption_percent: number;
  entries: CustomerWalletEntry[];
}

export interface BirthdayValue {
  month: number;
  day: number;
}

export interface BirthdayOfferSummary {
  enabled: boolean;
  discount_percent: number;
  window_days: number;
  eligible_venues: LoyaltyVenueRef[];
  stackable: boolean;
}

export interface CustomerBirthday {
  birthday: BirthdayValue | null;
  locked: boolean;
  offer: BirthdayOfferSummary | null;
}

export interface VenueLoyaltyRate {
  venue_id: string;
  venue_name: string;
  available: boolean;
  loyalty_points_enabled: boolean;
  accrual_basis_points: number;
  rounding_mode: "floor" | "half_up" | "ceiling";
}

export type VenueLoyaltyRateUpdate = Omit<
  VenueLoyaltyRate,
  "venue_name" | "available"
>;

export interface AdminBirthdaySettings {
  enabled: boolean;
  discount_percent: number;
  window_days: number;
  eligible_venue_ids: string[];
  stackable: boolean;
}

export interface AdminLoyaltyV2Settings {
  wallet_mode: LoyaltyWalletMode;
  point_value_minor: number;
  max_redemption_percent: number;
  expiry_months: number;
  expiry_days_override: number | null;
  expiry_reminder_days: number;
  default_bonus_venue_id: string | null;
  rounding: "floor" | "half_up" | "ceiling";
  venue_rates: VenueLoyaltyRate[];
  birthday: AdminBirthdaySettings;
}

export type AdminLoyaltyV2Update = Omit<
  AdminLoyaltyV2Settings,
  "wallet_mode" | "venue_rates"
> & { venue_rates: VenueLoyaltyRateUpdate[] };

export interface WalletModePreview {
  current_mode: LoyaltyWalletMode;
  target_mode: LoyaltyWalletMode;
  preview_hash: string;
  customers_affected: number;
  wallets_affected: number;
  total_balance_points: number;
  transfer_operations: number;
  fallback_required: boolean;
  fallback_venue_id: string | null;
  unresolved_points: number;
  eligible_fallback_venues: LoyaltyVenueRef[];
  warnings: string[];
}

export interface WalletModePreviewRequest {
  target_mode: LoyaltyWalletMode;
  fallback_venue_id?: string | null;
}

export interface WalletModeConfirmRequest {
  target_mode: LoyaltyWalletMode;
  preview_hash: string;
  fallback_venue_id?: string | null;
  reason: string;
  confirm: true;
}

export interface WalletModeChangeResult {
  wallet_mode: LoyaltyWalletMode;
  wallets_created: number;
  transfer_operations: number;
  total_balance_points: number;
  completed_at: string;
  idempotent_replay: boolean;
}

export interface AdminCustomerBirthday {
  user_id: string;
  birthday: BirthdayValue;
  locked: boolean;
  updated_at: string;
}

export interface CardData {
  user_id: string;
  display_name: string;
  qr_payload: string;
  short_code: string;
  balance_points: number;
  currency_name: string;
  visits_enabled: boolean;
  visit_streak: number;
  visit_goal: number;
  stamps_enabled: boolean;
  stamps: number;
  stamp_goal: number;
  blocked: boolean;
  updated_at: string;
}

export type HistoryType =
  | "purchase_accrual"
  | "points_redemption"
  | "points_product_purchase"
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
    | "text"
    | "points";
  status: "active" | "redeemed" | "expired" | "cancelled";
  expires_at?: string | null;
  created_at: string;
  redeemed_at?: string | null;
  terms?: string | null;
  qr_payload?: string | null;
}

export interface Promotion {
  id: string;
  venue_id?: string;
  title: string;
  text: string;
  image_url?: string | null;
  image_media_id?: string | null;
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
  venue_id?: string;
  title: string;
  text: string;
  image_media_id?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
}

export interface MenuCategory {
  id: string;
  venue_id?: string;
  name: string;
  description?: string | null;
  icon_media_id?: string | null;
  icon_url?: string | null;
  sort_order: number;
  visible: boolean;
  archived_at?: string | null;
}

export interface MenuCategoryDraft {
  venue_id?: string;
  name: string;
  description?: string | null;
  icon_media_id?: string | null;
  sort_order: number;
  visible: boolean;
}

export interface MenuItem {
  id: string;
  venue_id?: string;
  category_id: string;
  name: string;
  description?: string | null;
  image_url?: string | null;
  image_media_id?: string | null;
  price_minor: number;
  old_price_minor?: number | null;
  points_price?: number | null;
  composition?: string | null;
  volume?: string | null;
  labels?: string[];
  available: boolean;
  visible: boolean;
  sort_order?: number;
  archived_at?: string | null;
  modifier_groups?: MenuModifierGroup[];
}

export interface MenuModifierOption {
  id: string;
  name: string;
  price_delta_minor: number;
  allows_quantity: boolean;
  max_quantity: number;
}

export interface MenuModifierGroup {
  id: string;
  name: string;
  description?: string | null;
  min_selections: number;
  max_selections: number;
  required: boolean;
  options: MenuModifierOption[];
}

export interface MenuItemDraft {
  category_id: string;
  name: string;
  description?: string | null;
  image_media_id?: string | null;
  price_minor: number;
  old_price_minor?: number | null;
  points_price?: number | null;
  composition?: string | null;
  volume?: string | null;
  labels: string[];
  available: boolean;
  visible: boolean;
  sort_order: number;
}

export interface AdminModifierOption extends MenuModifierOption {
  enabled: boolean;
  sort_order: number;
}

export interface AdminModifierGroup {
  id: string;
  venue_id: string;
  name: string;
  description?: string | null;
  min_selections: number;
  max_selections: number;
  required: boolean;
  enabled: boolean;
  sort_order: number;
  archived_at?: string | null;
  item_ids: string[];
  options: AdminModifierOption[];
}

export interface AdminModifierGroupDraft {
  venue_id: string;
  name: string;
  description?: string | null;
  min_selections: number;
  max_selections: number;
  required: boolean;
  enabled: boolean;
  sort_order: number;
  item_ids: string[];
  options: Array<{
    id?: string | null;
    name: string;
    price_delta_minor: number;
    allows_quantity: boolean;
    max_quantity: number;
    enabled: boolean;
    sort_order: number;
  }>;
}

export interface PromotionPricingRules {
  promotion_id: string;
  venue_id: string;
  pricing_enabled: boolean;
  action_type: "percent_discount" | "fixed_discount" | null;
  discount_value: number | null;
  priority: number;
  stackable: boolean;
  active_from_date: string | null;
  active_to_date: string | null;
  active_weekdays: number[];
  active_time_from: string | null;
  active_time_to: string | null;
  fulfillment_modes: string[];
  customer_birthday_only: boolean;
  minimum_order_minor: number;
  category_ids: string[];
  menu_item_ids: string[];
}

export type PromotionPricingRulesDraft = Omit<
  PromotionPricingRules,
  "promotion_id" | "venue_id"
>;

export interface CartPriceRequest {
  fulfillment_mode: "pickup" | "delivery";
  lines: Array<{
    line_id?: string;
    menu_item_id: string;
    quantity: number;
    modifiers: Array<{ option_id: string; quantity: number }>;
  }>;
}

export interface CartPriceResponse {
  subtotal_minor: number;
  discount_minor: number;
  total_minor: number;
  venues: Array<{
    venue_id: string;
    subtotal_minor: number;
    discount_minor: number;
    total_minor: number;
    lines: Array<{
      line_id: string;
      menu_item_id: string;
      item_name: string;
      quantity: number;
      subtotal_minor: number;
      discount_minor: number;
      total_minor: number;
    }>;
    promotions: Array<{
      promotion_id: string | null;
      title: string;
      priority: number;
      discount_minor: number;
    }>;
  }>;
}

export type FulfillmentMode = "pickup" | "delivery";
export type OrderStatus =
  | "new"
  | "confirmed"
  | "preparing"
  | "ready"
  | "waiting_for_courier"
  | "courier_assigned"
  | "picked_up"
  | "in_transit"
  | "delivered"
  | "cancelled";

export interface CartLineDraft {
  line_id: string;
  menu_item_id: string;
  quantity: number;
  modifiers: Array<{ option_id: string; quantity: number }>;
}

export interface OrderCreateRequest {
  fulfillment_mode: FulfillmentMode;
  lines: CartLineDraft[];
  point_redemptions: Array<{ venue_id: string; points: number }>;
  pickup_location_id: string | null;
  delivery_zone_id: string | null;
  contact_phone: string;
  delivery_address: string | null;
  entrance: string | null;
  apartment: string | null;
  floor: string | null;
  customer_comment: string | null;
  desired_delivery_at: string | null;
  payment_method: "cash" | "card_on_receipt";
}

export interface OrderOptions {
  delivery_enabled: boolean;
  minimum_order_minor: number;
  fixed_fee_minor: number;
  free_delivery_threshold_minor: number | null;
  scheduling_allowed: boolean;
  earliest_preparation_minutes: number;
  pickup_locations: Array<{
    id: string;
    name: string;
    address: string;
    opening_hours: Record<string, unknown>;
    comment: string | null;
    preparation_minutes: number;
  }>;
  delivery_zones: Array<{
    id: string;
    name: string;
    description: string | null;
    fee_minor: number;
    minimum_order_minor: number | null;
  }>;
}

export interface CustomerOrder {
  id: string;
  number: number;
  fulfillment_mode: FulfillmentMode;
  status: OrderStatus;
  status_version: number;
  contact_phone: string;
  delivery_address: string | null;
  entrance: string | null;
  apartment: string | null;
  floor: string | null;
  customer_comment: string | null;
  desired_delivery_at: string | null;
  pickup_name: string | null;
  pickup_address: string | null;
  delivery_zone_name: string | null;
  subtotal_minor: number;
  promotion_discount_minor: number;
  points_discount_minor: number;
  delivery_fee_minor: number;
  total_minor: number;
  payment_method: "cash" | "card_on_receipt";
  payment_status: "unpaid" | "paid_externally" | "cancelled";
  created_at: string;
  updated_at: string;
  idempotent_replay: boolean;
  suborders: Array<{
    id: string;
    venue_id: string;
    venue_name: string;
    status: OrderStatus;
    subtotal_minor: number;
    promotion_discount_minor: number;
    points_discount_minor: number;
    total_minor: number;
    lines: Array<{
      id: string;
      menu_item_id: string | null;
      name: string;
      quantity: number;
      unit_base_price_minor: number;
      unit_modifiers_price_minor: number;
      subtotal_minor: number;
      promotion_discount_minor: number;
      points_discount_minor: number;
      total_minor: number;
      modifiers: Array<{
        id: string;
        option_id: string | null;
        group_name: string;
        name: string;
        quantity: number;
        unit_price_delta_minor: number;
        total_price_delta_minor: number;
      }>;
    }>;
    promotions: Array<{
      id: string;
      promotion_id: string | null;
      title: string;
      priority: number;
      discount_minor: number;
    }>;
  }>;
  events: Array<{
    id: string;
    suborder_id: string | null;
    from_status: OrderStatus | null;
    to_status: OrderStatus;
    reason: string | null;
    comment: string | null;
    created_at: string;
  }>;
}

/** Courier DTO deliberately omits loyalty, Telegram identifiers and audit history. */
export interface CourierOrder {
  id: string;
  number: number;
  status: OrderStatus;
  status_version: number;
  venue_names: string[];
  delivery_zone_name: string | null;
  desired_delivery_at: string | null;
  created_at: string;
  customer_name: string | null;
  contact_phone: string | null;
  delivery_address: string | null;
  entrance: string | null;
  apartment: string | null;
  floor: string | null;
  customer_comment: string | null;
}

export interface CourierOption {
  id: string;
  display_name: string;
}

export interface AdminDeliverySettings {
  id: string;
  delivery_enabled: boolean;
  minimum_order_minor: number;
  fixed_fee_minor: number;
  free_delivery_threshold_minor: number | null;
  scheduling_allowed: boolean;
  earliest_preparation_minutes: number;
  operating_hours: Record<string, unknown>;
  default_pickup_location_id: string | null;
  consolidation_location_id: string | null;
}

export type AdminDeliverySettingsDraft = Omit<AdminDeliverySettings, "id">;

export interface AdminDeliveryZone {
  id: string;
  name: string;
  description: string | null;
  fee_minor: number;
  minimum_order_minor: number | null;
  is_active: boolean;
  sort_order: number;
  archived: boolean;
}

export type AdminDeliveryZoneDraft = Omit<AdminDeliveryZone, "id" | "archived">;

export interface AdminFulfillmentLocation {
  id: string;
  name: string;
  address: string;
  is_active: boolean;
  pickup_enabled: boolean;
  consolidation_enabled: boolean;
  pickup_comment: string | null;
  preparation_minutes: number;
}

export interface ContactLocation {
  id: string;
  venue_id: string | null;
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

export type StaffClientLookup =
  | { qr_token: string; short_code?: never; phone?: never }
  | { qr_token?: never; short_code: string; phone?: never }
  | { qr_token?: never; short_code?: never; phone: string };

export interface PhoneCustomerCreate {
  phone: string;
  display_name?: string | null;
  venue_id: string;
}

export interface PhoneCustomer {
  user_id: string;
  card_id: string;
  display_name: string;
  masked_phone: string;
  short_code: string;
  points_balance: number;
  idempotent_replay: boolean;
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

export interface PurchasePreview extends AccrualPreview {
  location_id: string;
  stamps_to_add: number;
  stamps_before: number;
  stamps_after: number;
  stamp_rewards_earned: number;
  reward_bonus_points: number;
  visit_will_be_recorded: boolean;
  visit_already_counted: boolean;
  visit_streak_after: number;
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
  location_id: string;
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
  id?: string | null;
  display_name: string;
  position: string;
  bio: string;
  tip_url: string;
  tip_qr_url?: string | null;
  photo_url?: string | null;
  photo_media_id?: string | null;
  tip_qr_media_id?: string | null;
  moderation_status: "draft" | "pending_review" | "approved" | "hidden";
  published_visible?: boolean;
}

export interface MediaUpload {
  id: string;
  url: string;
}

export interface PointsMenuPurchase {
  operation_id: string;
  reward_id: string;
  item_id: string;
  item_name: string;
  points_spent: number;
  balance_after: number;
  qr_payload: string;
  expires_at?: string | null;
  idempotent_replay: boolean;
}

export interface StaffRewardLookup {
  reward_id: string;
  customer_name: string;
  reward_name: string;
  description: string;
  terms?: string | null;
  expires_at?: string | null;
}

export interface PendingTipProfile {
  id: string;
  staff_id: string;
  staff_display_name: string;
  position?: string | null;
  pending_name?: string | null;
  pending_bio?: string | null;
  pending_tip_url?: string | null;
  status: TipProfile["moderation_status"];
  submitted_at?: string | null;
}

export interface PostPurchase {
  operation_id: string;
  barista_name: string;
  position: string;
  photo_url?: string | null;
  tip_url?: string | null;
  tip_qr_url?: string | null;
}

export interface AdminUserListItem {
  id: string;
  telegram_id: string | number | null;
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
  birthday?: BirthdayValue | null;
  birthday_locked?: boolean;
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
  | "customers.create"
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
  telegram_id: string | number | null;
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

export type CustomerIdentityProvider = "telegram" | "phone" | "max";

export interface CustomerMergeProfile {
  user_id: string;
  display_name: string;
  status: "active" | "blocked" | "inactive" | "anonymized" | "merged";
  identity_providers: CustomerIdentityProvider[];
  points_balance: number;
  stamp_count: number;
  visit_streak: number;
  last_visit_business_date: string | null;
  staff_role: Role | null;
  birthday_set: boolean;
}

export interface CustomerMergePreviewRequest {
  source_user_id: string;
  canonical_user_id: string;
}

export interface CustomerMergePreview {
  source: CustomerMergeProfile;
  canonical: CustomerMergeProfile;
  preview_hash: string;
  points_to_transfer: number;
  stamps_to_transfer: number;
  visit_snapshot_from_user_id: string | null;
  identities_to_move: number;
  rewards_to_move: number;
  sessions_to_revoke: number;
  cards_to_revoke: number;
  feedback_to_move: number;
  source_staff_rebound: boolean;
  birthday_conflict: boolean;
  birthday_resolution_required: boolean;
}

export interface CustomerMergeConfirmRequest extends CustomerMergePreviewRequest {
  preview_hash: string;
  reason: string;
  confirm: true;
  birthday_resolution?: "keep_canonical" | "use_source" | null;
}

export interface CustomerMergeResult {
  merge_id: string;
  source_user_id: string;
  canonical_user_id: string;
  preview_hash: string;
  completed_at: string;
  points_transferred: number;
  canonical_points_after: number;
  stamps_transferred: number;
  canonical_stamps_after: number;
  visit_snapshot_from_user_id: string | null;
  identities_moved: number;
  rewards_moved: number;
  sessions_revoked: number;
  cards_revoked: number;
  feedback_moved: number;
  birthday_resolution: "keep_canonical" | "use_source" | null;
  source_staff_rebound: boolean;
  idempotent_replay: boolean;
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
  visit_reward: LoyaltyRewardConfig | null;
  stamps_enabled: boolean;
  stamp_goal: number;
  stamps_per_purchase: number;
  stamp_operation_limit: number;
  stamp_reward_validity_days: number | null;
  reset_stamps_after_reward: boolean;
  stamp_reward: LoyaltyRewardConfig | null;
}

export type LoyaltyRewardConfig =
  | { kind: "menu_item"; menu_item_id: string }
  | { kind: "custom"; name: string; description?: string | null }
  | { kind: "points"; points: number };

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
  venue_id: string | null;
  scope_label: string;
}

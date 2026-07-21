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
  | "visit_mark"
  | "stamp_added"
  | "reward_created"
  | "reward_redeemed"
  | "admin_adjustment"
  | "operation_reversal";

export interface HistoryItem {
  id: string;
  type: HistoryType;
  description: string;
  delta_points?: number | null;
  balance_after?: number | null;
  created_at: string;
  status: "completed" | "pending" | "reversed";
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
}

export interface MenuCategory {
  id: string;
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
  volume?: string | null;
  labels?: string[];
  available: boolean;
  visible: boolean;
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
  masked_short_code: string;
  balance_points: number;
  currency_name: string;
  visit_streak: number;
  stamps: number;
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

export interface OperationResult {
  operation_id: string;
  status: "completed" | "pending";
  delta_points: number;
  balance_after: number;
  created_at: string;
}

export interface TipProfile {
  display_name: string;
  position: string;
  bio: string;
  tip_url: string;
  tip_qr_url?: string | null;
  moderation_status: "draft" | "pending_review" | "approved" | "hidden";
}

export interface AdminUser {
  id: string;
  telegram_id: string | number;
  display_name: string;
  username?: string | null;
  short_code: string;
  balance_points: number;
  status: "active" | "blocked";
  visit_streak: number;
  stamps: number;
  active_rewards: number;
  created_at: string;
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

export interface LoyaltySettings {
  points_enabled: boolean;
  currency_name: string;
  rubles_per_point: number;
  minimum_purchase_minor: number;
  rounding: "floor" | "half_up" | "ceiling";
  max_redemption_percent: number;
  visit_enabled: boolean;
  visit_goal: number;
  timezone: string;
  business_day_boundary: string;
  stamps_enabled: boolean;
  stamp_goal: number;
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

import type {
  AccrualPreview,
  Actor,
  AdminModifierGroup,
  AdminModifierGroupDraft,
  AdminAnalytics,
  AdminCustomerBirthday,
  AdminStaffMember,
  AdminOverview,
  AdminFeedback,
  AdminDeliverySettings,
  AdminDeliverySettingsDraft,
  AdminDeliveryZone,
  AdminDeliveryZoneDraft,
  AdminFulfillmentLocation,
  AdminFulfillmentLocationDraft,
  AdminLoyaltyV2Settings,
  AdminLoyaltyV2Update,
  AdminUser,
  AdminUserListItem,
  AdminVenue,
  AdminVenueDraft,
  AdjustmentPreview,
  AuditEvent,
  AuthSession,
  BirthdayValue,
  BulkBonusDraft,
  BulkBonusPreview,
  BulkBonusResult,
  CardData,
  CartPriceRequest,
  CartPriceResponse,
  CustomerOrder,
  CourierOrder,
  CourierOption,
  ContactsData,
  CustomerMergeConfirmRequest,
  CustomerMergePreview,
  CustomerMergePreviewRequest,
  CustomerMergeResult,
  CustomerIdentity,
  CustomerBirthday,
  CustomerPass,
  CustomerWalletSummary,
  HistoryItem,
  HomeData,
  ListResponse,
  LoyaltySettings,
  MenuCategory,
  MenuCategoryDraft,
  MenuItem,
  MenuItemDraft,
  MediaUpload,
  OperationResult,
  OrderCreateRequest,
  OrderOptions,
  OrderStatus,
  PhoneCustomer,
  PhoneCustomerCreate,
  Promotion,
  PromotionDraft,
  PromotionPricingRules,
  PromotionPricingRulesDraft,
  PointsMenuPurchase,
  PostPurchase,
  PublicMoreData,
  PurchasePreview,
  RedemptionPreview,
  Receipt,
  Reward,
  Role,
  StaffClient,
  StaffClientLookup,
  StaffRewardLookup,
  StaffPassLookup,
  StaffMemberDraft,
  StaffProfile,
  TipProfile,
  TelegramWebLoginData,
  PendingTipProfile,
  PassTemplate,
  PassPurchase,
  PassUsage,
  PublicReview,
  ReviewStatus,
  Venue,
  WalletModeChangeResult,
  WalletModeConfirmRequest,
  WalletModePreview,
  WalletModePreviewRequest,
} from "./types";
import { demoApi } from "./demo";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api/v1").replace(
  /\/$/,
  "",
);
const TOKEN_KEY = "coffie.session";
const MAX_MEDIA_BYTES = 5 * 1024 * 1024;
export const MEDIA_FILE_ACCEPT =
  ".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details?: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      requestId?: string;
      details?: Record<string, unknown>;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code ?? "request_failed";
    this.requestId = options.requestId;
    this.details = options.details;
  }
}

let inMemoryToken: string | null = null;

function readToken(): string | null {
  if (inMemoryToken) return inMemoryToken;
  try {
    inMemoryToken = window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
  return inMemoryToken;
}

export function setSessionToken(token: string | null): void {
  inMemoryToken = token;
  try {
    if (token) window.sessionStorage.setItem(TOKEN_KEY, token);
    else window.sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // In-memory sessions still work when storage is unavailable.
  }
}

interface ErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

async function request<T>(
  path: string,
  options: RequestInit & { idempotencyKey?: string } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.idempotencyKey)
    headers.set("Idempotency-Key", options.idempotencyKey);

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(
      "Не удалось связаться с сервером. Проверьте подключение.",
      {
        status: 0,
        code: "network_error",
      },
    );
  }

  if (!response.ok) {
    let envelope: ErrorEnvelope = {};
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      // Use a safe generic message for non-JSON upstream errors.
    }
    throw new ApiError(
      envelope.error?.message ??
        (response.status === 413
          ? "Фото больше 5 МБ. Выберите файл меньшего размера."
          : "Не удалось выполнить запрос"),
      {
        status: response.status,
        code: envelope.error?.code,
        requestId: envelope.error?.request_id,
        details: envelope.error?.details,
      },
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function queryString(
  values: Record<
    string,
    | string
    | number
    | boolean
    | readonly (string | number | boolean)[]
    | undefined
  >,
): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach((item) => params.append(key, String(item)));
    } else if (value !== undefined && value !== "") {
      params.set(key, String(value));
    }
  });
  const value = params.toString();
  return value ? `?${value}` : "";
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

function uuid(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();

  // FastAPI validates Idempotency-Key as a UUID, including in older WebViews
  // where randomUUID is missing but getRandomValues is still available.
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export const createIdempotencyKey = uuid;

function validateMediaFile(file: File): void {
  if (file.size > MAX_MEDIA_BYTES) {
    throw new ApiError("Фото больше 5 МБ. Выберите файл меньшего размера.", {
      status: 413,
      code: "media_too_large",
    });
  }
}

const demoConfigured = import.meta.env.VITE_USE_DEMO_DATA;
export const isDemoMode =
  demoConfigured === "true" ||
  (import.meta.env.DEV && demoConfigured !== "false");

interface RawAuthResponse {
  access_token: string;
  expires_at: string;
  user: Partial<Actor> & {
    id: string;
    display_name: string;
    telegram_id: string | number;
  };
  staff?: { role?: Role; permissions?: string[] } | null;
}

interface BackendCustomerWallets {
  mode: CustomerWalletSummary["mode"];
  total_balance: number;
  point_value_minor: number;
  max_redemption_percent: number;
  entries: Array<{
    wallet_id: string;
    venue: { id: string; name: string; available: boolean } | null;
    balance: number;
    expiring_amount: number;
    expires_at: string | null;
  }>;
}

function normalizeCustomerWallets(
  response: BackendCustomerWallets,
): CustomerWalletSummary {
  // Phase 2 transport names stay behind this adapter so screen state remains
  // stable if persistence-oriented DTO fields change during backend rollout.
  return {
    mode: response.mode,
    total_balance_points: response.total_balance,
    point_value_minor: response.point_value_minor,
    max_redemption_percent: response.max_redemption_percent,
    entries: response.entries.map((entry) => ({
      id: entry.wallet_id,
      venue: entry.venue,
      balance_points: entry.balance,
      expiring_points: entry.expiring_amount,
      expires_at: entry.expires_at,
    })),
  };
}

async function bootstrapAuth(initData: string): Promise<AuthSession> {
  if (isDemoMode) return demoApi.bootstrapAuth();
  const raw = await request<RawAuthResponse>("/auth/telegram", {
    method: "POST",
    body: jsonBody({ init_data: initData }),
  });
  return normalizeAuth(raw);
}

function normalizeAuth(raw: RawAuthResponse): AuthSession {
  const staffRole = raw.staff?.role;
  const role = staffRole ?? raw.user.role ?? "customer";
  const availableRoles =
    raw.user.available_roles ??
    (staffRole ? ["customer", staffRole] : ["customer"]);
  const session: AuthSession = {
    access_token: raw.access_token,
    expires_at: raw.expires_at,
    actor: {
      id: raw.user.id,
      telegram_id: String(raw.user.telegram_id),
      display_name: raw.user.display_name,
      username: raw.user.username,
      photo_url: raw.user.photo_url,
      role,
      available_roles: availableRoles,
      permissions: raw.staff?.permissions ?? raw.user.permissions ?? [],
    },
  };
  setSessionToken(session.access_token);
  return session;
}

async function telegramWebLogin(
  payload: TelegramWebLoginData,
): Promise<AuthSession> {
  const raw = await request<RawAuthResponse>("/auth/telegram/web", {
    method: "POST",
    body: jsonBody(payload),
  });
  return normalizeAuth(raw);
}

async function passwordLogin(payload: {
  username: string;
  password: string;
}): Promise<AuthSession> {
  const raw = await request<RawAuthResponse>("/auth/password", {
    method: "POST",
    body: jsonBody(payload),
  });
  return normalizeAuth(raw);
}

async function getHome(): Promise<HomeData> {
  if (isDemoMode) return demoApi.getHome();
  const [card, rewards, promotions, subscriptionProducts] = await Promise.all([
    request<CardData>("/me/card"),
    request<ListResponse<Reward>>("/me/rewards?status=active"),
    request<ListResponse<Promotion>>("/promotions?active=true"),
    request<ListResponse<PassTemplate>>("/subscription-products"),
  ]);
  return {
    card,
    active_rewards: rewards.items,
    promotions: promotions.items,
    subscription_products: subscriptionProducts.items,
  };
}

async function getMenu(venueId?: string | null): Promise<{
  categories: MenuCategory[];
  items: MenuItem[];
}> {
  if (isDemoMode) return demoApi.getMenu(venueId);
  const venueQuery = venueId ? `?venue_id=${encodeURIComponent(venueId)}` : "";
  const itemQuery = venueId
    ? `?available=true&venue_id=${encodeURIComponent(venueId)}`
    : "?available=true";
  const [categories, items] = await Promise.all([
    request<ListResponse<MenuCategory>>(`/menu/categories${venueQuery}`),
    request<ListResponse<MenuItem>>(`/menu/items${itemQuery}`),
  ]);
  return { categories: categories.items, items: items.items };
}

async function getMore(): Promise<PublicMoreData> {
  if (isDemoMode) return demoApi.getMore();
  const [contacts, staff, promotions] = await Promise.all([
    request<ContactsData>("/contacts"),
    request<ListResponse<StaffProfile>>("/staff-profiles"),
    request<ListResponse<Promotion>>("/promotions?active=true"),
  ]);
  return { contacts, staff: staff.items, promotions: promotions.items };
}

async function getAdminOverview(): Promise<AdminOverview> {
  if (isDemoMode) return demoApi.getAdminOverview();
  const [dashboard, events] = await Promise.all([
    request<Omit<AdminOverview, "recent_events">>("/admin/dashboard"),
    request<ListResponse<BackendAuditEvent>>(
      "/admin/events?page=1&page_size=5",
    ),
  ]);
  return {
    ...dashboard,
    recent_events: events.items.map(normalizeAuditEvent),
  };
}

interface BackendAdminUser extends AdminUserListItem {
  short_code: string;
  points_balance: number;
  visit_streak: number;
  stamp_count: number;
  active_card: boolean;
}

interface BackendAuditEvent {
  id: string;
  event_type: string;
  actor_user_id?: string | null;
  actor_staff_id?: string | null;
  subject_user_id?: string | null;
  object_type?: string | null;
  object_id?: string | null;
  metadata: Record<string, unknown>;
  severity: "info" | "warning" | "critical";
  suspicious: boolean;
  human_message: string;
  created_at: string;
}

interface BackendCardReward {
  id: string;
  name: string;
  description: string;
  type: Reward["type"];
  status: Reward["status"];
  terms?: string | null;
  expires_at?: string | null;
  created_at: string;
}

interface BackendOperation {
  id?: string;
  operation_id?: string;
  type?: HistoryItem["type"];
  operation_type?: HistoryItem["type"];
  status: OperationResult["status"] | "committed" | "rejected";
  points_delta: number;
  balance_after: number | null;
  occurred_at: string;
  streak_after?: number | null;
  stamps_after?: number | null;
  reward_ids?: string[];
  audit_message?: string;
}

interface BackendStaffClient {
  user_id: string;
  display_name: string;
  short_code: string;
  blocked: boolean;
  points_balance: number;
  visit_streak: number;
  visit_goal: number;
  stamp_count: number;
  stamp_goal: number;
  currency_name: string;
  available_rewards: BackendCardReward[];
  recent_operations: BackendOperation[];
}

interface BackendAccrualPreview {
  user_id: string;
  purchase_amount_minor: number;
  awarded_points: number;
  balance_before: number;
  projected_balance_after: number;
  requires_approval: boolean;
}

interface BackendPurchasePreview extends BackendAccrualPreview {
  stamps_to_add: number;
  stamps_before: number;
  projected_stamps_after: number;
  stamp_rewards_earned: number;
  reward_bonus_points: number;
  visit_will_be_recorded: boolean;
  visit_already_counted: boolean;
  projected_visit_streak: number;
}

interface BackendRedemptionPreview {
  user_id: string;
  purchase_amount_minor: number;
  requested_points: number;
  discount_minor: number;
  maximum_points_for_purchase: number;
  balance_before: number;
  projected_balance_after: number;
}

const operationDescriptions: Record<HistoryItem["type"], string> = {
  purchase_accrual: "Начисление за покупку",
  points_redemption: "Списание баллов",
  points_product_purchase: "Покупка за баллы",
  welcome_bonus: "Приветственный бонус",
  points_expiration: "Сгорание баллов",
  visit_mark: "Отмечено посещение",
  stamp_added: "Добавлен штамп",
  reward_created: "Выдана награда",
  reward_redeemed: "Погашена награда",
  reward_cancelled: "Награда отменена",
  admin_adjustment: "Корректировка администратором",
  bulk_bonus: "Массовый бонус",
  operation_reversal: "Отмена операции",
};

function normalizeOperationStatus(
  status: BackendOperation["status"],
): OperationResult["status"] {
  if (status === "committed") return "completed";
  if (status === "rejected") return "failed";
  return status;
}

function normalizeHistoryOperation(operation: BackendOperation): HistoryItem {
  const type = operation.type ?? operation.operation_type ?? "admin_adjustment";
  return {
    id: operation.id ?? operation.operation_id ?? "",
    type,
    description: operationDescriptions[type],
    delta_points: operation.points_delta,
    balance_after: operation.balance_after,
    created_at: operation.occurred_at,
    status: normalizeOperationStatus(operation.status),
  };
}

function normalizeOperationResult(
  operation: BackendOperation,
): OperationResult {
  return {
    operation_id: operation.operation_id ?? operation.id ?? "",
    operation_type: operation.operation_type ?? operation.type,
    status: normalizeOperationStatus(operation.status),
    delta_points: operation.points_delta,
    balance_after: operation.balance_after,
    created_at: operation.occurred_at,
    streak_after: operation.streak_after,
    stamps_after: operation.stamps_after,
    reward_ids: operation.reward_ids,
    audit_message: operation.audit_message,
  };
}

function normalizeStaffClient(client: BackendStaffClient): StaffClient {
  return {
    user_id: client.user_id,
    display_name: client.display_name,
    short_code: client.short_code,
    masked_short_code: `••••${client.short_code.slice(-4)}`,
    balance_points: client.points_balance,
    currency_name: client.currency_name,
    visit_streak: client.visit_streak,
    visit_goal: client.visit_goal,
    stamps: client.stamp_count,
    stamp_goal: client.stamp_goal,
    available_rewards: client.available_rewards.map((reward) => ({
      id: reward.id,
      title: reward.name,
      description: reward.description,
      type: reward.type,
      status: reward.status,
      expires_at: reward.expires_at,
      created_at: reward.created_at,
    })),
    blocked: client.blocked,
    suspicious: false,
    recent_operations: client.recent_operations.map(normalizeHistoryOperation),
  };
}

function normalizeAdminUser(user: BackendAdminUser): AdminUser {
  return {
    ...user,
    balance_points: user.points_balance,
    stamps: user.stamp_count,
    active_rewards: 0,
  };
}

function normalizeAuditEvent(event: BackendAuditEvent): AuditEvent {
  return {
    id: event.id,
    type: event.event_type,
    message: event.human_message,
    actor_name: event.actor_staff_id ?? event.actor_user_id,
    subject_name: event.subject_user_id,
    object_type: event.object_type,
    object_id: event.object_id,
    metadata: event.metadata,
    severity: event.severity,
    suspicious: event.suspicious,
    created_at: event.created_at,
  };
}

export const coffeeApi = {
  isDemo: isDemoMode,
  bootstrapAuth,
  telegramWebLogin,
  passwordLogin,
  async logout(): Promise<void> {
    if (!isDemoMode) await request<void>("/auth/logout", { method: "POST" });
    setSessionToken(null);
  },
  getHome,
  getVenues: (): Promise<ListResponse<Venue>> =>
    isDemoMode ? demoApi.getVenues() : request("/venues"),
  getAdminVenues: (
    includeArchived = false,
  ): Promise<ListResponse<AdminVenue>> =>
    request(
      `/admin/venues${queryString({ page: 1, page_size: 100, include_archived: includeArchived || undefined })}`,
    ),
  saveAdminVenue: (
    venue: AdminVenue | null,
    payload: AdminVenueDraft,
  ): Promise<AdminVenue> =>
    request(
      venue ? `/admin/venues/${encodeURIComponent(venue.id)}` : "/admin/venues",
      { method: venue ? "PATCH" : "POST", body: jsonBody(payload) },
    ),
  archiveAdminVenue: (venue: AdminVenue): Promise<AdminVenue> =>
    request(`/admin/venues/${encodeURIComponent(venue.id)}/archive`, {
      method: "POST",
    }),
  restoreAdminVenue: (venue: AdminVenue): Promise<AdminVenue> =>
    request(`/admin/venues/${encodeURIComponent(venue.id)}/restore`, {
      method: "POST",
    }),
  getMyWallets: async (): Promise<CustomerWalletSummary> =>
    isDemoMode
      ? demoApi.getMyWallets()
      : normalizeCustomerWallets(
          await request<BackendCustomerWallets>("/me/wallets"),
        ),
  getMyBirthday: (): Promise<CustomerBirthday> =>
    isDemoMode ? demoApi.getMyBirthday() : request("/me/birthday"),
  setMyBirthday: (birthday: BirthdayValue): Promise<CustomerBirthday> =>
    isDemoMode
      ? demoApi.setMyBirthday(birthday)
      : request("/me/birthday", {
          method: "PUT",
          body: jsonBody({ birthday }),
        }),
  getCard: (): Promise<CardData> =>
    isDemoMode ? demoApi.getCard() : request("/me/card"),
  getHistory: (type?: string): Promise<ListResponse<HistoryItem>> =>
    isDemoMode
      ? demoApi.getHistory(type)
      : request(`/me/history${queryString({ page: 1, page_size: 50, type })}`),
  getRewards: (status?: string): Promise<ListResponse<Reward>> =>
    isDemoMode
      ? demoApi.getRewards(status)
      : request(`/me/rewards${queryString({ status })}`),
  getMenu,
  priceCart: (payload: CartPriceRequest): Promise<CartPriceResponse> =>
    request("/cart/price", { method: "POST", body: jsonBody(payload) }),
  getOrderOptions: (): Promise<OrderOptions> => request("/order-options"),
  createOrder: (
    payload: OrderCreateRequest,
    idempotencyKey = uuid(),
  ): Promise<CustomerOrder> =>
    request("/orders", {
      method: "POST",
      body: jsonBody(payload),
      idempotencyKey,
    }),
  getOrders: (active?: boolean): Promise<{ items: CustomerOrder[] }> =>
    request(`/orders${queryString({ active, limit: 100 })}`),
  getOrder: (id: string): Promise<CustomerOrder> =>
    request(`/orders/${encodeURIComponent(id)}`),
  cancelOrder: (id: string, reason: string): Promise<CustomerOrder> =>
    request(`/orders/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      body: jsonBody({ reason }),
    }),
  getStaffOrders: (
    venueId?: string,
    statuses?: OrderStatus[],
  ): Promise<{ items: CustomerOrder[] }> =>
    request(
      `/staff/orders${queryString({ venue_id: venueId, statuses, limit: 200 })}`,
    ),
  getStaffOrder: (id: string): Promise<CustomerOrder> =>
    request(`/staff/orders/${encodeURIComponent(id)}`),
  transitionOrder: (
    id: string,
    status: OrderStatus,
    reason: string | null = null,
    comment: string | null = null,
  ): Promise<CustomerOrder> =>
    request(`/staff/orders/${encodeURIComponent(id)}/transition`, {
      method: "POST",
      body: jsonBody({ status, reason, comment }),
    }),
  transitionSuborder: (
    id: string,
    status: OrderStatus,
    reason: string | null = null,
    comment: string | null = null,
  ): Promise<CustomerOrder> =>
    request(`/staff/suborders/${encodeURIComponent(id)}/transition`, {
      method: "POST",
      body: jsonBody({ status, reason, comment }),
    }),
  getAvailableCourierOrders: (): Promise<{ items: CourierOrder[] }> =>
    request("/courier/orders/available?limit=100"),
  getMyCourierOrders: (
    includeCompleted = false,
  ): Promise<{ items: CourierOrder[] }> =>
    request(
      `/courier/orders/mine${queryString({ include_completed: includeCompleted, limit: 100 })}`,
    ),
  getCourierOrder: (id: string): Promise<CourierOrder> =>
    request(`/courier/orders/${encodeURIComponent(id)}`),
  claimCourierOrder: (id: string): Promise<CourierOrder> =>
    request(`/courier/orders/${encodeURIComponent(id)}/claim`, {
      method: "POST",
      idempotencyKey: uuid(),
    }),
  declineCourierOrder: (id: string): Promise<CourierOrder> =>
    request(`/courier/orders/${encodeURIComponent(id)}/decline`, {
      method: "POST",
      idempotencyKey: uuid(),
    }),
  transitionCourierOrder: (
    id: string,
    action: "pickup" | "in-transit" | "delivered",
  ): Promise<CourierOrder> =>
    request(`/courier/orders/${encodeURIComponent(id)}/${action}`, {
      method: "POST",
      idempotencyKey: uuid(),
    }),
  assignCourier: (
    orderId: string,
    courierStaffId: string,
  ): Promise<CourierOrder> =>
    request(`/staff/orders/${encodeURIComponent(orderId)}/courier`, {
      method: "POST",
      body: jsonBody({ courier_staff_id: courierStaffId }),
      idempotencyKey: uuid(),
    }),
  getCourierOptions: (): Promise<{ items: CourierOption[] }> =>
    request("/staff/couriers"),
  uploadReceiptMedia: async (file: File): Promise<MediaUpload> => {
    const body = new FormData();
    body.append("upload", file);
    return request<MediaUpload>("/staff/receipts/media", {
      method: "POST",
      body,
    });
  },
  createReceipt: (
    payload: {
      user_id: string;
      venue_id: string;
      amount_minor: number;
      image_media_id: string;
      receipt_number: string | null;
      external_id: string | null;
      fiscal_data: Record<string, unknown>;
      note: string | null;
      source: "manual";
    },
    idempotencyKey = uuid(),
  ): Promise<Receipt> =>
    request("/staff/receipts", {
      method: "POST",
      body: jsonBody(payload),
      idempotencyKey,
    }),
  getReceipts: (): Promise<{ items: Receipt[] }> =>
    request("/staff/receipts?limit=100"),
  getReceipt: (id: string): Promise<Receipt> =>
    request(`/staff/receipts/${encodeURIComponent(id)}`),
  editReceipt: (
    id: string,
    payload: {
      image_media_id: string | null;
      receipt_number: string | null;
      external_id: string | null;
      fiscal_data: Record<string, unknown>;
      note: string | null;
    },
    idempotencyKey = uuid(),
  ): Promise<Receipt> =>
    request(`/staff/receipts/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: jsonBody(payload),
      idempotencyKey,
    }),
  cancelReceipt: (id: string, idempotencyKey = uuid()): Promise<Receipt> =>
    request(`/staff/receipts/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      idempotencyKey,
    }),
  getPostPurchase: (operationId: string): Promise<PostPurchase> =>
    isDemoMode
      ? Promise.resolve({
          operation_id: operationId,
          barista_name: "Анна",
          position: "Бариста",
          tip_url: "https://example.com",
        })
      : request(`/me/post-purchase/${encodeURIComponent(operationId)}`),
  purchaseMenuItemWithPoints: (
    itemId: string,
    idempotencyKey = uuid(),
  ): Promise<PointsMenuPurchase> =>
    isDemoMode
      ? Promise.resolve({
          operation_id: uuid(),
          reward_id: uuid(),
          item_id: itemId,
          item_name: "Награда из меню",
          points_spent: 80,
          balance_after: 204,
          qr_payload: `coffee-reward:v1:${uuid()}`,
          idempotent_replay: false,
        })
      : request(
          `/me/menu-items/${encodeURIComponent(itemId)}/purchase-with-points`,
          {
            method: "POST",
            idempotencyKey,
          },
        ),
  getMore,
  getContacts: (): Promise<ContactsData> =>
    isDemoMode ? demoApi.getContacts() : request("/contacts"),
  submitFeedback: (payload: {
    rating: number;
    category: string;
    message: string;
    may_contact: boolean;
  }): Promise<{ id: string; status: string }> =>
    isDemoMode
      ? demoApi.submitFeedback(payload)
      : request("/feedback", { method: "POST", body: jsonBody(payload) }),
  lookupStaffClient: async (
    payload: StaffClientLookup,
  ): Promise<StaffClient> =>
    isDemoMode
      ? demoApi.lookupStaffClient(payload)
      : normalizeStaffClient(
          await request<BackendStaffClient>("/staff/cards/lookup", {
            method: "POST",
            body: jsonBody(payload),
          }),
        ),
  createPhoneCustomer: (
    payload: PhoneCustomerCreate,
    idempotencyKey: string,
  ): Promise<PhoneCustomer> =>
    isDemoMode
      ? demoApi.createPhoneCustomer(payload, idempotencyKey)
      : request("/staff/customers", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey,
        }),
  previewAccrual: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
  }): Promise<AccrualPreview> =>
    isDemoMode
      ? demoApi.previewAccrual(payload)
      : request<BackendAccrualPreview>("/staff/operations/accrual/preview", {
          method: "POST",
          body: jsonBody(payload),
        }).then((preview) => ({
          user_id: preview.user_id,
          customer_name: "Клиент",
          purchase_amount_minor: preview.purchase_amount_minor,
          points_to_accrue: preview.awarded_points,
          balance_before: preview.balance_before,
          balance_after: preview.projected_balance_after,
          requires_approval: preview.requires_approval,
        })),
  confirmAccrual: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
  }): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.confirmAccrual(payload)
      : request<BackendOperation>("/staff/operations/accrual", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey: uuid(),
        }).then(normalizeOperationResult),
  previewPurchase: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
    stamps_to_add: number;
    location_id: string;
  }): Promise<PurchasePreview> =>
    isDemoMode
      ? demoApi.previewPurchase(payload)
      : request<BackendPurchasePreview>("/staff/operations/purchase/preview", {
          method: "POST",
          body: jsonBody(payload),
        }).then((preview) => ({
          user_id: preview.user_id,
          customer_name: "Клиент",
          purchase_amount_minor: preview.purchase_amount_minor,
          points_to_accrue: preview.awarded_points,
          balance_before: preview.balance_before,
          balance_after: preview.projected_balance_after,
          stamps_to_add: preview.stamps_to_add,
          stamps_before: preview.stamps_before,
          stamps_after: preview.projected_stamps_after,
          stamp_rewards_earned: preview.stamp_rewards_earned,
          reward_bonus_points: preview.reward_bonus_points,
          visit_will_be_recorded: preview.visit_will_be_recorded,
          visit_already_counted: preview.visit_already_counted,
          visit_streak_after: preview.projected_visit_streak,
          requires_approval: preview.requires_approval,
          location_id: payload.location_id,
        })),
  confirmPurchase: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
    stamps_to_add: number;
    location_id: string;
  }): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.confirmPurchase(payload)
      : request<BackendOperation>("/staff/operations/purchase", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey: uuid(),
        }).then(normalizeOperationResult),
  previewRedemption: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
    requested_points: number;
    location_id: string;
  }): Promise<RedemptionPreview> =>
    isDemoMode
      ? demoApi.previewRedemption(payload)
      : request<BackendRedemptionPreview>(
          "/staff/operations/redemption/preview",
          { method: "POST", body: jsonBody(payload) },
        ).then((preview) => ({
          user_id: preview.user_id,
          customer_name: "Клиент",
          purchase_amount_minor: preview.purchase_amount_minor,
          requested_points: preview.requested_points,
          discount_minor: preview.discount_minor,
          maximum_points_for_purchase: preview.maximum_points_for_purchase,
          balance_before: preview.balance_before,
          balance_after: preview.projected_balance_after,
          location_id: payload.location_id,
        })),
  confirmRedemption: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
    requested_points: number;
    location_id: string;
  }): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.confirmRedemption(payload)
      : request<BackendOperation>("/staff/operations/redemption", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey: uuid(),
        }).then(normalizeOperationResult),
  markVisit: async (userId: string): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.markVisit(userId)
      : request<BackendOperation>("/staff/operations/visits", {
          method: "POST",
          body: jsonBody({ user_id: userId }),
          idempotencyKey: uuid(),
        }).then(normalizeOperationResult),
  addStamp: async (userId: string): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.addStamp(userId)
      : request<BackendOperation>("/staff/operations/stamps", {
          method: "POST",
          body: jsonBody({ user_id: userId, stamps_to_add: 1 }),
          idempotencyKey: uuid(),
        }).then(normalizeOperationResult),
  redeemReward: async (rewardId: string): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.redeemReward(rewardId)
      : request<BackendOperation>(
          `/staff/rewards/${encodeURIComponent(rewardId)}/redeem`,
          { method: "POST", idempotencyKey: uuid() },
        ).then(normalizeOperationResult),
  lookupStaffReward: (qrPayload: string): Promise<StaffRewardLookup> =>
    isDemoMode
      ? Promise.resolve({
          reward_id: uuid(),
          customer_name: "Анна",
          reward_name: "Капучино",
          description: "Награда за баллы",
        })
      : request("/staff/rewards/lookup", {
          method: "POST",
          body: jsonBody({ qr_payload: qrPayload }),
        }),
  reverseOperation: async (
    operationId: string,
    reason: string,
  ): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.reverseOperation(operationId, reason)
      : request<BackendOperation>(
          `/staff/operations/${encodeURIComponent(operationId)}/reverse`,
          {
            method: "POST",
            body: jsonBody({ reason }),
            idempotencyKey: uuid(),
          },
        ).then(normalizeOperationResult),
  getRecentOperations: async (): Promise<ListResponse<HistoryItem>> =>
    isDemoMode
      ? demoApi.getRecentOperations()
      : request<ListResponse<BackendOperation>>(
          "/staff/operations/recent",
        ).then((response) => ({
          ...response,
          items: response.items.map(normalizeHistoryOperation),
        })),
  getTipProfile: (): Promise<TipProfile> =>
    isDemoMode ? demoApi.getTipProfile() : request("/staff/me/tip-profile"),
  saveTipProfile: (profile: TipProfile): Promise<TipProfile> =>
    isDemoMode
      ? demoApi.saveTipProfile(profile)
      : request("/staff/me/tip-profile", {
          method: "PUT",
          body: jsonBody({
            display_name: profile.display_name,
            position: profile.position,
            bio: profile.bio,
            tip_url: profile.tip_url,
            photo_media_id: profile.photo_media_id ?? null,
            tip_qr_media_id: profile.tip_qr_media_id ?? null,
          }),
        }),
  cancelTipProfileReview: (): Promise<TipProfile> =>
    isDemoMode
      ? demoApi.getTipProfile()
      : request("/staff/me/tip-profile/cancel-review", { method: "POST" }),
  uploadStaffMedia: async (file: File, kind: "staff_profile" | "tip_qr") => {
    validateMediaFile(file);
    if (isDemoMode) return Promise.resolve({ id: uuid(), url: "" });
    const body = new FormData();
    body.append("upload", file);
    body.append("kind", kind);
    return request<MediaUpload>("/staff/me/media", { method: "POST", body });
  },
  getAdminOverview,
  getAdminAnalytics: (days = 30): Promise<AdminAnalytics> =>
    isDemoMode
      ? demoApi.getAdminAnalytics(days)
      : request(`/admin/analytics${queryString({ days })}`),
  getAdminUsers: (
    query?: string,
    status?: string,
  ): Promise<ListResponse<AdminUserListItem>> =>
    isDemoMode
      ? demoApi.getAdminUsers(query, status)
      : request(
          `/admin/users${queryString({ query, status, page: 1, page_size: 50 })}`,
        ),
  getAdminUser: async (id: string): Promise<AdminUser> =>
    isDemoMode
      ? demoApi.getAdminUser(id)
      : normalizeAdminUser(
          await request<BackendAdminUser>(
            `/admin/users/${encodeURIComponent(id)}`,
          ),
        ),
  getAdminUserHistory: async (
    id: string,
  ): Promise<ListResponse<HistoryItem>> => {
    if (isDemoMode) return demoApi.getHistory();
    const response = await request<ListResponse<BackendOperation>>(
      `/admin/users/${encodeURIComponent(id)}/history?page=1&page_size=50`,
    );
    return {
      ...response,
      items: response.items.map(normalizeHistoryOperation),
    };
  },
  getAdminCustomerIdentities: (
    id: string,
  ): Promise<{ items: CustomerIdentity[] }> =>
    isDemoMode
      ? Promise.resolve({ items: [] })
      : request(`/admin/users/${encodeURIComponent(id)}/identities`),
  updateAdminUserNote: async (
    id: string,
    internalNote: string | null,
  ): Promise<AdminUser> =>
    isDemoMode
      ? demoApi.getAdminUser(id)
      : normalizeAdminUser(
          await request<BackendAdminUser>(
            `/admin/users/${encodeURIComponent(id)}/note`,
            {
              method: "PATCH",
              body: jsonBody({ internal_note: internalNote }),
            },
          ),
        ),
  setAdminUserBlocked: async (
    id: string,
    blocked: boolean,
    reason: string,
  ): Promise<{ status: string; blocked: boolean }> => {
    if (isDemoMode) return { status: blocked ? "blocked" : "active", blocked };
    return request(
      `/admin/users/${encodeURIComponent(id)}/${blocked ? "block" : "unblock"}`,
      {
        method: "POST",
        body: blocked ? jsonBody({ reason }) : undefined,
        idempotencyKey: uuid(),
      },
    );
  },
  reissueAdminUserCard: (
    id: string,
  ): Promise<{ card_id: string; short_code: string }> =>
    isDemoMode
      ? Promise.resolve({ card_id: uuid(), short_code: "DEMO-CARD" })
      : request(`/admin/users/${encodeURIComponent(id)}/cards/reissue`, {
          method: "POST",
          idempotencyKey: uuid(),
        }),
  previewCustomerMerge: (
    payload: CustomerMergePreviewRequest,
  ): Promise<CustomerMergePreview> =>
    isDemoMode
      ? demoApi.previewCustomerMerge(payload)
      : request("/admin/customer-merge/preview", {
          method: "POST",
          body: jsonBody(payload),
        }),
  confirmCustomerMerge: (
    payload: CustomerMergeConfirmRequest,
    idempotencyKey: string,
  ): Promise<CustomerMergeResult> =>
    isDemoMode
      ? demoApi.confirmCustomerMerge(payload, idempotencyKey)
      : request("/admin/customer-merge/confirm", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey,
        }),
  changeAdminCustomerBirthday: (
    userId: string,
    payload: { birthday: BirthdayValue; reason: string },
  ): Promise<AdminCustomerBirthday> =>
    isDemoMode
      ? demoApi.changeAdminCustomerBirthday(userId, payload)
      : request(`/admin/users/${encodeURIComponent(userId)}/birthday`, {
          method: "PUT",
          body: jsonBody(payload),
        }),
  getAdminEvents: (
    filters: { severity?: string; suspicious?: boolean } = {},
  ): Promise<ListResponse<AuditEvent>> =>
    isDemoMode
      ? demoApi.getAdminEvents(filters)
      : request<ListResponse<BackendAuditEvent>>(
          `/admin/events${queryString({ ...filters, page: 1, page_size: 50 })}`,
        ).then((response) => ({
          ...response,
          items: response.items.map(normalizeAuditEvent),
        })),
  getAdminFeedback: (status?: string): Promise<ListResponse<AdminFeedback>> =>
    isDemoMode
      ? demoApi.getAdminFeedback(status)
      : request(
          `/admin/feedback${queryString({ status, page: 1, page_size: 50 })}`,
        ),
  updateAdminFeedback: (
    id: string,
    payload: {
      status: AdminFeedback["status"];
      internal_note?: string | null;
      assigned_to_staff_id?: string | null;
    },
  ): Promise<AdminFeedback> =>
    isDemoMode
      ? demoApi.updateAdminFeedback(id, payload)
      : request(`/admin/feedback/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: jsonBody(payload),
        }),
  deleteAdminFeedback: (id: string): Promise<void> =>
    isDemoMode
      ? demoApi.deleteAdminFeedback(id)
      : request(`/admin/feedback/${encodeURIComponent(id)}`, {
          method: "DELETE",
        }),
  getAdminStaff: (
    query?: string,
    active?: boolean,
  ): Promise<ListResponse<AdminStaffMember>> =>
    isDemoMode
      ? demoApi.getAdminStaff(query, active)
      : request(
          `/admin/staff${queryString({ query, active, page: 1, page_size: 100 })}`,
        ),
  getPendingTipProfiles: (): Promise<ListResponse<PendingTipProfile>> =>
    isDemoMode
      ? Promise.resolve({ items: [], page: 1, page_size: 100, total: 0 })
      : request("/admin/tip-profiles/pending?page=1&page_size=100"),
  approveTipProfile: (id: string): Promise<PendingTipProfile> =>
    request(`/admin/tip-profiles/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: jsonBody({ moderation_note: null }),
    }),
  hideTipProfile: (id: string, note?: string): Promise<PendingTipProfile> =>
    request(`/admin/tip-profiles/${encodeURIComponent(id)}/hide`, {
      method: "POST",
      body: jsonBody({ moderation_note: note || null }),
    }),
  createAdminStaff: (
    payload: StaffMemberDraft & {
      user_id: string;
      role: Exclude<Role, "customer">;
    },
  ): Promise<AdminStaffMember> =>
    isDemoMode
      ? demoApi.createAdminStaff(payload)
      : request("/admin/staff", {
          method: "POST",
          body: jsonBody(payload),
        }),
  updateAdminStaff: (
    id: string,
    payload: Partial<StaffMemberDraft> & { is_active?: boolean },
  ): Promise<AdminStaffMember> =>
    isDemoMode
      ? demoApi.updateAdminStaff(id, payload)
      : request(`/admin/staff/${encodeURIComponent(id)}`, {
          method: "PATCH",
          body: jsonBody(payload),
        }),
  deleteAdminStaff: (id: string): Promise<void> =>
    isDemoMode
      ? demoApi.deleteAdminStaff(id)
      : request(`/admin/staff/${encodeURIComponent(id)}`, {
          method: "DELETE",
        }),
  changeAdminStaffRole: (
    id: string,
    role: Exclude<Role, "customer">,
  ): Promise<AdminStaffMember> =>
    isDemoMode
      ? demoApi.changeAdminStaffRole(id, role)
      : request(`/admin/staff/${encodeURIComponent(id)}/role`, {
          method: "POST",
          body: jsonBody({ role }),
        }),
  revokeAdminStaffSessions: (
    id: string,
  ): Promise<{ revoked_sessions: number }> =>
    isDemoMode
      ? demoApi.revokeAdminStaffSessions(id)
      : request(`/admin/staff/${encodeURIComponent(id)}/revoke-sessions`, {
          method: "POST",
        }),
  getSettings: (): Promise<LoyaltySettings> =>
    isDemoMode ? demoApi.getSettings() : request("/admin/loyalty-settings"),
  saveSettings: (settings: LoyaltySettings): Promise<LoyaltySettings> =>
    isDemoMode
      ? demoApi.saveSettings(settings)
      : request("/admin/loyalty-settings", {
          method: "PUT",
          body: jsonBody(settings),
        }),
  getAdminLoyaltyV2: (): Promise<AdminLoyaltyV2Settings> =>
    isDemoMode ? demoApi.getAdminLoyaltyV2() : request("/admin/loyalty"),
  saveAdminLoyaltyV2: (
    settings: AdminLoyaltyV2Update,
  ): Promise<AdminLoyaltyV2Settings> =>
    isDemoMode
      ? demoApi.saveAdminLoyaltyV2(settings)
      : request("/admin/loyalty", {
          method: "PUT",
          body: jsonBody(settings),
        }),
  previewWalletMode: (
    payload: WalletModePreviewRequest,
  ): Promise<WalletModePreview> =>
    isDemoMode
      ? demoApi.previewWalletMode(payload)
      : request("/admin/loyalty/wallet-mode/preview", {
          method: "POST",
          body: jsonBody(payload),
        }),
  confirmWalletMode: (
    payload: WalletModeConfirmRequest,
    idempotencyKey: string,
  ): Promise<WalletModeChangeResult> =>
    isDemoMode
      ? demoApi.confirmWalletMode(payload, idempotencyKey)
      : request("/admin/loyalty/wallet-mode/confirm", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey,
        }),
  getAdminMenu: async (
    includeArchived = false,
  ): Promise<{
    categories: MenuCategory[];
    items: MenuItem[];
  }> => {
    if (isDemoMode) return demoApi.getAdminMenu(includeArchived);
    const [categories, items] = await Promise.all([
      request<ListResponse<MenuCategory>>(
        `/admin/menu/categories${queryString({ page: 1, page_size: 100, include_archived: includeArchived || undefined })}`,
      ),
      request<ListResponse<MenuItem>>(
        `/admin/menu/items${queryString({ page: 1, page_size: 100, include_archived: includeArchived || undefined })}`,
      ),
    ]);
    return { categories: categories.items, items: items.items };
  },
  uploadAdminMedia: async (
    file: File,
    kind:
      | "menu_category"
      | "menu_item"
      | "promotion"
      | "location"
      | "pass_template",
  ) => {
    validateMediaFile(file);
    if (isDemoMode) return Promise.resolve({ id: uuid(), url: "" });
    const body = new FormData();
    body.append("upload", file);
    body.append("kind", kind);
    return request<MediaUpload>("/admin/media", { method: "POST", body });
  },
  toggleMenuItem: (item: MenuItem): Promise<MenuItem> =>
    isDemoMode
      ? demoApi.toggleMenuItem(item)
      : request(`/admin/menu/items/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: jsonBody({ visible: !item.visible }),
        }),
  archiveMenuItem: (item: MenuItem): Promise<MenuItem> =>
    isDemoMode
      ? demoApi.archiveMenuItem(item)
      : request(`/admin/menu/items/${encodeURIComponent(item.id)}/archive`, {
          method: "POST",
        }),
  restoreMenuItem: (item: MenuItem): Promise<MenuItem> =>
    isDemoMode
      ? demoApi.restoreMenuItem(item)
      : request(`/admin/menu/items/${encodeURIComponent(item.id)}/restore`, {
          method: "POST",
        }),
  deleteMenuItem: (item: MenuItem): Promise<void> =>
    isDemoMode
      ? demoApi.deleteMenuItem(item)
      : request(`/admin/menu/items/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
          headers: { "Idempotency-Key": uuid() },
        }),
  saveMenuCategory: (
    category: MenuCategory | null,
    payload: MenuCategoryDraft,
  ): Promise<MenuCategory> =>
    isDemoMode
      ? demoApi.saveMenuCategory(category, payload)
      : request(
          category
            ? `/admin/menu/categories/${encodeURIComponent(category.id)}`
            : "/admin/menu/categories",
          {
            method: category ? "PATCH" : "POST",
            body: jsonBody(
              category
                ? Object.fromEntries(
                    Object.entries(payload).filter(
                      ([key]) => key !== "venue_id",
                    ),
                  )
                : payload,
            ),
          },
        ),
  saveMenuItem: (
    item: MenuItem | null,
    payload: MenuItemDraft,
  ): Promise<MenuItem> =>
    isDemoMode
      ? demoApi.saveMenuItem(item, payload)
      : request(
          item
            ? `/admin/menu/items/${encodeURIComponent(item.id)}`
            : "/admin/menu/items",
          {
            method: item ? "PATCH" : "POST",
            body: jsonBody(payload),
          },
        ),
  getAdminPromotions: (
    status?: Promotion["status"],
  ): Promise<ListResponse<Promotion>> =>
    isDemoMode
      ? demoApi.getAdminPromotions(status)
      : request(
          `/admin/promotions${queryString({ status, page: 1, page_size: 50 })}`,
        ),
  publishPromotion: (promotion: Promotion): Promise<Promotion> =>
    isDemoMode
      ? demoApi.publishPromotion(promotion)
      : request(
          `/admin/promotions/${encodeURIComponent(promotion.id)}/publish`,
          { method: "POST" },
        ),
  savePromotion: (
    promotion: Promotion | null,
    payload: PromotionDraft,
  ): Promise<Promotion> =>
    isDemoMode
      ? demoApi.savePromotion(promotion, payload)
      : request(
          promotion
            ? `/admin/promotions/${encodeURIComponent(promotion.id)}`
            : "/admin/promotions",
          {
            method: promotion ? "PATCH" : "POST",
            body: jsonBody({
              ...(promotion
                ? Object.fromEntries(
                    Object.entries(payload).filter(
                      ([key]) => key !== "venue_id",
                    ),
                  )
                : payload),
              // Promotions are static cards. Saving also clears legacy links.
              button_label: null,
              button_url: null,
            }),
          },
        ),
  getAdminModifierGroups: async (
    includeArchived = false,
  ): Promise<AdminModifierGroup[]> => {
    if (isDemoMode) return [];
    const value = await request<{ items: AdminModifierGroup[] }>(
      `/admin/pricing/modifier-groups${queryString({ include_archived: includeArchived || undefined })}`,
    );
    return value.items;
  },
  getAdminDelivery: async (): Promise<{
    settings: AdminDeliverySettings;
    zones: AdminDeliveryZone[];
    locations: AdminFulfillmentLocation[];
  }> => {
    const [settings, zones, locations] = await Promise.all([
      request<AdminDeliverySettings>("/admin/delivery/settings"),
      request<{ items: AdminDeliveryZone[] }>("/admin/delivery/zones"),
      request<{ items: AdminFulfillmentLocation[] }>(
        "/admin/delivery/locations",
      ),
    ]);
    return { settings, zones: zones.items, locations: locations.items };
  },
  saveAdminDeliverySettings: (
    payload: AdminDeliverySettingsDraft,
  ): Promise<AdminDeliverySettings> =>
    request("/admin/delivery/settings", {
      method: "PUT",
      body: jsonBody(payload),
    }),
  saveAdminDeliveryZone: (
    zone: AdminDeliveryZone | null,
    payload: AdminDeliveryZoneDraft,
  ): Promise<AdminDeliveryZone> =>
    request(
      zone
        ? `/admin/delivery/zones/${encodeURIComponent(zone.id)}`
        : "/admin/delivery/zones",
      { method: zone ? "PUT" : "POST", body: jsonBody(payload) },
    ),
  archiveAdminDeliveryZone: (id: string): Promise<AdminDeliveryZone> =>
    request(`/admin/delivery/zones/${encodeURIComponent(id)}/archive`, {
      method: "POST",
    }),
  saveAdminFulfillmentLocation: (
    location: AdminFulfillmentLocation,
  ): Promise<AdminFulfillmentLocation> =>
    request(`/admin/delivery/locations/${encodeURIComponent(location.id)}`, {
      method: "PUT",
      body: jsonBody({
        venue_id: location.venue_id,
        name: location.name,
        address: location.address,
        phone: location.phone,
        map_url: location.map_url,
        image_media_id: location.image_media_id,
        latitude: location.latitude,
        longitude: location.longitude,
        is_active: location.is_active,
        pickup_enabled: location.pickup_enabled,
        consolidation_enabled: location.consolidation_enabled,
        pickup_comment: location.pickup_comment,
        preparation_minutes: location.preparation_minutes,
      }),
    }),
  createAdminFulfillmentLocation: (
    location: AdminFulfillmentLocationDraft,
  ): Promise<AdminFulfillmentLocation> =>
    request("/admin/delivery/locations", {
      method: "POST",
      body: jsonBody({ ...location, sort_order: 0 }),
    }),
  saveAdminModifierGroup: (
    group: AdminModifierGroup | null,
    payload: AdminModifierGroupDraft,
  ): Promise<AdminModifierGroup> =>
    request(
      group
        ? `/admin/pricing/modifier-groups/${encodeURIComponent(group.id)}`
        : "/admin/pricing/modifier-groups",
      { method: group ? "PUT" : "POST", body: jsonBody(payload) },
    ),
  archiveAdminModifierGroup: (
    group: AdminModifierGroup,
  ): Promise<AdminModifierGroup> =>
    request(
      `/admin/pricing/modifier-groups/${encodeURIComponent(group.id)}/archive`,
      { method: "POST" },
    ),
  restoreAdminModifierGroup: (
    group: AdminModifierGroup,
  ): Promise<AdminModifierGroup> =>
    request(
      `/admin/pricing/modifier-groups/${encodeURIComponent(group.id)}/restore`,
      { method: "POST" },
    ),
  getPromotionPricingRules: (
    promotionId: string,
  ): Promise<PromotionPricingRules> =>
    request(`/admin/pricing/promotions/${encodeURIComponent(promotionId)}`),
  savePromotionPricingRules: (
    promotionId: string,
    payload: PromotionPricingRulesDraft,
  ): Promise<PromotionPricingRules> =>
    request(`/admin/pricing/promotions/${encodeURIComponent(promotionId)}`, {
      method: "PUT",
      body: jsonBody(payload),
    }),
  archivePromotion: (promotion: Promotion): Promise<Promotion> =>
    isDemoMode
      ? demoApi.archivePromotion(promotion)
      : request(
          `/admin/promotions/${encodeURIComponent(promotion.id)}/archive`,
          { method: "POST" },
        ),
  restorePromotion: (promotion: Promotion): Promise<Promotion> =>
    isDemoMode
      ? demoApi.restorePromotion(promotion)
      : request(
          `/admin/promotions/${encodeURIComponent(promotion.id)}/restore`,
          { method: "POST" },
        ),
  deletePromotion: (promotion: Promotion): Promise<void> =>
    isDemoMode
      ? demoApi.deletePromotion(promotion)
      : request(`/admin/promotions/${encodeURIComponent(promotion.id)}`, {
          method: "DELETE",
        }),
  previewAdjustment(
    user: AdminUser,
    deltaPoints: number,
    reason: string,
    venueId: string | null,
    scopeLabel: string,
  ): AdjustmentPreview {
    return {
      user_id: user.id,
      customer_name: user.display_name,
      delta_points: deltaPoints,
      balance_before: user.balance_points,
      balance_after: user.balance_points + deltaPoints,
      reason,
      venue_id: venueId,
      scope_label: scopeLabel,
    };
  },
  confirmAdjustment: async (payload: {
    user_id: string;
    delta_points: number;
    reason: string;
    venue_id: string | null;
  }): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.confirmAdjustment(payload)
      : request<BackendOperation>(
          `/admin/users/${encodeURIComponent(payload.user_id)}/adjustments`,
          {
            method: "POST",
            body: jsonBody({
              delta_points: payload.delta_points,
              reason: payload.reason,
              venue_id: payload.venue_id,
            }),
            idempotencyKey: uuid(),
          },
        ).then(normalizeOperationResult),
  getReviews: (venueId?: string): Promise<{ items: PublicReview[] }> =>
    isDemoMode
      ? Promise.resolve({ items: [] })
      : request(`/reviews${queryString({ venue_id: venueId, limit: 100 })}`),
  getMyReviews: (): Promise<{ items: PublicReview[] }> =>
    isDemoMode ? Promise.resolve({ items: [] }) : request("/me/reviews"),
  createReview: (payload: {
    venue_id: string;
    order_id: string | null;
    employee_staff_id: string | null;
    rating: number;
    text: string;
    author_display_name: string | null;
  }): Promise<PublicReview> =>
    request("/reviews", { method: "POST", body: jsonBody(payload) }),
  getAdminReviews: (
    status?: ReviewStatus,
  ): Promise<{ items: PublicReview[] }> =>
    request(`/admin/reviews${queryString({ status, limit: 200 })}`),
  moderateReview: (
    id: string,
    status: Exclude<ReviewStatus, "pending">,
    moderationNote: string | null,
  ): Promise<PublicReview> =>
    request(`/admin/reviews/${encodeURIComponent(id)}/moderate`, {
      method: "POST",
      body: jsonBody({ status, moderation_note: moderationNote }),
    }),
  getMyPasses: (): Promise<{ items: CustomerPass[] }> =>
    isDemoMode ? Promise.resolve({ items: [] }) : request("/me/subscriptions"),
  getSubscriptionProducts: (): Promise<{ items: PassTemplate[] }> =>
    isDemoMode
      ? Promise.resolve({ items: [] })
      : request("/subscription-products"),
  purchaseSubscription: (
    templateId: string,
    paymentMethod: "cash" | "card_on_receipt",
    idempotencyKey = uuid(),
  ): Promise<PassPurchase> =>
    request("/subscription-purchases", {
      method: "POST",
      body: jsonBody({
        template_id: templateId,
        payment_method: paymentMethod,
      }),
      idempotencyKey,
    }),
  getMyPassPurchases: (): Promise<{ items: PassPurchase[] }> =>
    isDemoMode
      ? Promise.resolve({ items: [] })
      : request("/me/subscription-purchases"),
  getPendingPassPurchases: (): Promise<{ items: PassPurchase[] }> =>
    request("/staff/subscription-purchases"),
  confirmPassPurchase: (id: string): Promise<PassPurchase> =>
    request(`/staff/subscription-purchases/${encodeURIComponent(id)}/confirm`, {
      method: "POST",
    }),
  getCustomerPasses: (userId: string): Promise<{ items: CustomerPass[] }> =>
    request(`/staff/customers/${encodeURIComponent(userId)}/subscriptions`),
  lookupStaffPass: (qrPayload: string): Promise<StaffPassLookup> =>
    request("/staff/subscriptions/lookup", {
      method: "POST",
      body: jsonBody({ qr_payload: qrPayload }),
    }),
  usePass: (
    passId: string,
    venueId: string,
    itemId: string,
    idempotencyKey = uuid(),
  ): Promise<PassUsage> =>
    request(`/staff/subscriptions/${encodeURIComponent(passId)}/use`, {
      method: "POST",
      body: jsonBody({ venue_id: venueId, item_id: itemId }),
      idempotencyKey,
    }),
  getPassTemplates: (activeOnly = false): Promise<{ items: PassTemplate[] }> =>
    request(
      `/admin/subscriptions/templates${queryString({ active_only: activeOnly })}`,
    ),
  createPassTemplate: (payload: {
    name: string;
    description: string;
    image_media_id: string | null;
    total_uses: number;
    validity_days: number;
    price_minor: number;
    purchase_enabled: boolean;
    venue_ids: string[];
    category_ids: string[];
    item_ids: string[];
  }): Promise<PassTemplate> =>
    request("/admin/subscriptions/templates", {
      method: "POST",
      body: jsonBody(payload),
    }),
  archivePassTemplate: (id: string): Promise<PassTemplate> =>
    request(
      `/admin/subscriptions/templates/${encodeURIComponent(id)}/archive`,
      { method: "POST" },
    ),
  restorePassTemplate: (id: string): Promise<PassTemplate> =>
    request(
      `/admin/subscriptions/templates/${encodeURIComponent(id)}/restore`,
      { method: "POST" },
    ),
  updatePassTemplate: (
    id: string,
    payload: {
      name: string;
      description: string;
      image_media_id: string | null;
      total_uses: number;
      validity_days: number;
      price_minor: number;
      purchase_enabled: boolean;
      venue_ids: string[];
      category_ids: string[];
      item_ids: string[];
    },
  ): Promise<PassTemplate> =>
    request(`/admin/subscriptions/templates/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: jsonBody(payload),
    }),
  issuePass: (
    userId: string,
    templateId: string,
    idempotencyKey = uuid(),
  ): Promise<CustomerPass> =>
    request("/admin/subscriptions/issue", {
      method: "POST",
      body: jsonBody({ user_id: userId, template_id: templateId }),
      idempotencyKey,
    }),
  cancelPass: (
    id: string,
    reason: string,
    idempotencyKey = uuid(),
  ): Promise<CustomerPass> =>
    request(`/admin/subscriptions/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
      body: jsonBody({ reason }),
      idempotencyKey,
    }),
  previewBulkBonus: (payload: BulkBonusDraft): Promise<BulkBonusPreview> =>
    request("/admin/bulk-bonus/preview", {
      method: "POST",
      body: jsonBody(payload),
    }),
  confirmBulkBonus: (
    payload: BulkBonusDraft & { preview_hash: string },
    idempotencyKey: string,
  ): Promise<BulkBonusResult> =>
    request("/admin/bulk-bonus/confirm", {
      method: "POST",
      body: jsonBody(payload),
      idempotencyKey,
    }),
};

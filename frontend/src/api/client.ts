import type {
  AccrualPreview,
  Actor,
  AdminStaffMember,
  AdminOverview,
  AdminFeedback,
  AdminUser,
  AdminUserListItem,
  AdjustmentPreview,
  AuditEvent,
  AuthSession,
  CardData,
  ContactsData,
  HistoryItem,
  HomeData,
  ListResponse,
  LoyaltySettings,
  MenuCategory,
  MenuCategoryDraft,
  MenuItem,
  MenuItemDraft,
  OperationResult,
  Promotion,
  PromotionDraft,
  PublicMoreData,
  RedemptionPreview,
  Reward,
  Role,
  StaffClient,
  StaffMemberDraft,
  StaffProfile,
  TipProfile,
} from "./types";
import { demoApi } from "./demo";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "/api/v1").replace(
  /\/$/,
  "",
);
const TOKEN_KEY = "coffie.session";

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
      envelope.error?.message ?? "Не удалось выполнить запрос",
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
  values: Record<string, string | number | boolean | undefined>,
): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  const value = params.toString();
  return value ? `?${value}` : "";
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

function uuid(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `fallback-${Date.now()}-${Math.random()}`
  );
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

async function bootstrapAuth(initData: string): Promise<AuthSession> {
  if (isDemoMode) return demoApi.bootstrapAuth();
  const raw = await request<RawAuthResponse>("/auth/telegram", {
    method: "POST",
    body: jsonBody({ init_data: initData }),
  });
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

async function getHome(): Promise<HomeData> {
  if (isDemoMode) return demoApi.getHome();
  const [card, rewards, promotions] = await Promise.all([
    request<CardData>("/me/card"),
    request<ListResponse<Reward>>("/me/rewards?status=active"),
    request<ListResponse<Promotion>>("/promotions?active=true"),
  ]);
  return { card, active_rewards: rewards.items, promotions: promotions.items };
}

async function getMenu(): Promise<{
  categories: MenuCategory[];
  items: MenuItem[];
}> {
  if (isDemoMode) return demoApi.getMenu();
  const [categories, items] = await Promise.all([
    request<ListResponse<MenuCategory>>("/menu/categories"),
    request<ListResponse<MenuItem>>("/menu/items?available=true"),
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
  const [users, blocked, events, suspicious, promotions] = await Promise.all([
    request<ListResponse<AdminUserListItem>>("/admin/users?page=1&page_size=1"),
    request<ListResponse<AdminUserListItem>>(
      "/admin/users?status=blocked&page=1&page_size=1",
    ),
    request<ListResponse<BackendAuditEvent>>(
      "/admin/events?page=1&page_size=5",
    ),
    request<ListResponse<BackendAuditEvent>>(
      "/admin/events?suspicious=true&page=1&page_size=1",
    ),
    request<ListResponse<Promotion>>(
      "/admin/promotions?status=published&page=1&page_size=1",
    ),
  ]);
  return {
    users_total: users.total,
    blocked_users: blocked.total,
    suspicious_events: suspicious.total,
    active_promotions: promotions.total,
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
  status: OperationResult["status"];
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
  welcome_bonus: "Приветственный бонус",
  points_expiration: "Сгорание баллов",
  visit_mark: "Отмечено посещение",
  stamp_added: "Добавлен штамп",
  reward_created: "Выдана награда",
  reward_redeemed: "Погашена награда",
  reward_cancelled: "Награда отменена",
  admin_adjustment: "Корректировка администратором",
  operation_reversal: "Отмена операции",
};

function normalizeHistoryOperation(operation: BackendOperation): HistoryItem {
  const type = operation.type ?? operation.operation_type ?? "admin_adjustment";
  return {
    id: operation.id ?? operation.operation_id ?? "",
    type,
    description: operationDescriptions[type],
    delta_points: operation.points_delta,
    balance_after: operation.balance_after,
    created_at: operation.occurred_at,
    status: operation.status,
  };
}

function normalizeOperationResult(
  operation: BackendOperation,
): OperationResult {
  return {
    operation_id: operation.operation_id ?? operation.id ?? "",
    operation_type: operation.operation_type ?? operation.type,
    status: operation.status,
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
    severity: event.severity,
    suspicious: event.suspicious,
    created_at: event.created_at,
  };
}

export const coffeeApi = {
  isDemo: isDemoMode,
  bootstrapAuth,
  async logout(): Promise<void> {
    if (!isDemoMode) await request<void>("/auth/logout", { method: "POST" });
    setSessionToken(null);
  },
  getHome,
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
  getMore,
  submitFeedback: (payload: {
    rating: number;
    category: string;
    message: string;
    may_contact: boolean;
  }): Promise<{ id: string; status: string }> =>
    isDemoMode
      ? demoApi.submitFeedback(payload)
      : request("/feedback", { method: "POST", body: jsonBody(payload) }),
  lookupStaffClient: async (payload: {
    qr_token?: string;
    short_code?: string;
  }): Promise<StaffClient> =>
    isDemoMode
      ? demoApi.lookupStaffClient(payload)
      : normalizeStaffClient(
          await request<BackendStaffClient>("/staff/cards/lookup", {
            method: "POST",
            body: jsonBody(payload),
          }),
        ),
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
  previewRedemption: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
    requested_points: number;
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
        })),
  confirmRedemption: async (payload: {
    user_id: string;
    purchase_amount_minor: number;
    requested_points: number;
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
          body: jsonBody(profile),
        }),
  getAdminOverview,
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
  getAdminMenu: async (): Promise<{
    categories: MenuCategory[];
    items: MenuItem[];
  }> => {
    if (isDemoMode) return demoApi.getMenu();
    const [categories, items] = await Promise.all([
      request<ListResponse<MenuCategory>>(
        "/admin/menu/categories?page=1&page_size=100",
      ),
      request<ListResponse<MenuItem>>("/admin/menu/items?page=1&page_size=100"),
    ]);
    return { categories: categories.items, items: items.items };
  },
  toggleMenuItem: (item: MenuItem): Promise<MenuItem> =>
    isDemoMode
      ? demoApi.toggleMenuItem(item)
      : request(`/admin/menu/items/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: jsonBody({ visible: !item.visible }),
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
            body: jsonBody(payload),
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
  getAdminPromotions: (): Promise<ListResponse<Promotion>> =>
    isDemoMode
      ? demoApi.getAdminPromotions()
      : request("/admin/promotions?page=1&page_size=50"),
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
            body: jsonBody(payload),
          },
        ),
  archivePromotion: (promotion: Promotion): Promise<Promotion> =>
    isDemoMode
      ? demoApi.archivePromotion(promotion)
      : request(
          `/admin/promotions/${encodeURIComponent(promotion.id)}/archive`,
          { method: "POST" },
        ),
  previewAdjustment(
    user: AdminUser,
    deltaPoints: number,
    reason: string,
  ): AdjustmentPreview {
    return {
      user_id: user.id,
      customer_name: user.display_name,
      delta_points: deltaPoints,
      balance_before: user.balance_points,
      balance_after: user.balance_points + deltaPoints,
      reason,
    };
  },
  confirmAdjustment: async (payload: {
    user_id: string;
    delta_points: number;
    reason: string;
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
            }),
            idempotencyKey: uuid(),
          },
        ).then(normalizeOperationResult),
};

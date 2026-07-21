import type {
  AccrualPreview,
  Actor,
  AdminOverview,
  AdminUser,
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
  MenuItem,
  OperationResult,
  Promotion,
  PublicMoreData,
  Reward,
  Role,
  StaffClient,
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
    request<ListResponse<AdminUser>>("/admin/users?page=1&page_size=1"),
    request<ListResponse<AdminUser>>(
      "/admin/users?status=blocked&page=1&page_size=1",
    ),
    request<ListResponse<AuditEvent>>("/admin/events?page=1&page_size=5"),
    request<ListResponse<AuditEvent>>(
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
    recent_events: events.items,
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
  lookupStaffClient: (payload: {
    qr_token?: string;
    short_code?: string;
  }): Promise<StaffClient> =>
    isDemoMode
      ? demoApi.lookupStaffClient(payload)
      : request("/staff/cards/lookup", {
          method: "POST",
          body: jsonBody(payload),
        }),
  previewAccrual: (payload: {
    user_id: string;
    purchase_amount_minor: number;
  }): Promise<AccrualPreview> =>
    isDemoMode
      ? demoApi.previewAccrual(payload)
      : request("/staff/operations/accrual/preview", {
          method: "POST",
          body: jsonBody(payload),
        }),
  confirmAccrual: (payload: {
    user_id: string;
    purchase_amount_minor: number;
  }): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.confirmAccrual(payload)
      : request("/staff/operations/accrual", {
          method: "POST",
          body: jsonBody(payload),
          idempotencyKey: uuid(),
        }),
  getRecentOperations: (): Promise<ListResponse<HistoryItem>> =>
    isDemoMode
      ? demoApi.getRecentOperations()
      : request("/staff/operations/recent"),
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
  ): Promise<ListResponse<AdminUser>> =>
    isDemoMode
      ? demoApi.getAdminUsers(query, status)
      : request(
          `/admin/users${queryString({ query, status, page: 1, page_size: 50 })}`,
        ),
  getAdminUser: (id: string): Promise<AdminUser> =>
    isDemoMode
      ? demoApi.getAdminUser(id)
      : request(`/admin/users/${encodeURIComponent(id)}`),
  getAdminEvents: (
    filters: { severity?: string; suspicious?: boolean } = {},
  ): Promise<ListResponse<AuditEvent>> =>
    isDemoMode
      ? demoApi.getAdminEvents(filters)
      : request(
          `/admin/events${queryString({ ...filters, page: 1, page_size: 50 })}`,
        ),
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
  confirmAdjustment: (payload: {
    user_id: string;
    delta_points: number;
    reason: string;
  }): Promise<OperationResult> =>
    isDemoMode
      ? demoApi.confirmAdjustment(payload)
      : request(
          `/admin/users/${encodeURIComponent(payload.user_id)}/adjustments`,
          {
            method: "POST",
            body: jsonBody({
              delta_points: payload.delta_points,
              reason: payload.reason,
            }),
            idempotencyKey: uuid(),
          },
        ),
};

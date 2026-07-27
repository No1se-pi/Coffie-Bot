import { ApiError } from "./client";
import type {
  AccrualPreview,
  AdminFeedback,
  AdminOverview,
  AdminStaffMember,
  AdminUser,
  AuditEvent,
  AuthSession,
  CardData,
  HistoryItem,
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
  PurchasePreview,
  RedemptionPreview,
  Reward,
  Role,
  StaffClient,
  StaffMemberDraft,
  TipProfile,
} from "./types";

const now = () => new Date().toISOString();
const wait = async () =>
  new Promise<void>((resolve) => window.setTimeout(resolve, 90));

let card: CardData = {
  user_id: "user-demo",
  display_name: "Ярослав",
  qr_payload: "coffee-card:v1:4f636248-e6ef-4b89-a9c4-fab15f56d761",
  short_code: "C0FFEE42",
  balance_points: 284,
  currency_name: "бобов",
  visit_streak: 3,
  visit_goal: 5,
  stamps: 6,
  stamp_goal: 9,
  blocked: false,
  updated_at: now(),
};

let lastAutomaticVisitDate: string | null = null;

let history: HistoryItem[] = [
  {
    id: "op-1",
    type: "purchase_accrual",
    description: "Начислено за покупку на 460 ₽",
    delta_points: 46,
    balance_after: 284,
    created_at: new Date(Date.now() - 25 * 60_000).toISOString(),
    status: "completed",
  },
  {
    id: "op-2",
    type: "visit_mark",
    description: "Третий визит подряд",
    created_at: new Date(Date.now() - 86_400_000).toISOString(),
    status: "completed",
  },
  {
    id: "op-3",
    type: "points_redemption",
    description: "Списано при оплате заказа",
    delta_points: -120,
    balance_after: 238,
    created_at: new Date(Date.now() - 172_800_000).toISOString(),
    status: "completed",
  },
];

let rewards: Reward[] = [
  {
    id: "reward-1",
    title: "Сироп в подарок",
    description:
      "Добавьте любой сироп к напитку. Покажите награду бариста до оплаты.",
    type: "free_option",
    status: "active",
    expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
    created_at: new Date(Date.now() - 86_400_000).toISOString(),
  },
  {
    id: "reward-2",
    title: "Бесплатный капучино",
    description: "Награда за серию посещений",
    type: "free_product",
    status: "redeemed",
    created_at: new Date(Date.now() - 20 * 86_400_000).toISOString(),
    redeemed_at: new Date(Date.now() - 16 * 86_400_000).toISOString(),
  },
];

let promotions: Promotion[] = [
  {
    id: "promo-1",
    title: "Утро начинается здесь",
    text: "До 11:00 второй напиток для друга со скидкой 30%.",
    status: "published",
    starts_at: new Date(Date.now() - 86_400_000).toISOString(),
    ends_at: new Date(Date.now() + 10 * 86_400_000).toISOString(),
  },
  {
    id: "promo-2",
    title: "Новый летний вкус",
    text: "Черничный эспрессо-тоник скоро появится в меню.",
    status: "draft",
  },
];

let categories: MenuCategory[] = [
  {
    id: "cat-coffee",
    name: "Кофе",
    description: "Классика и авторские напитки",
    sort_order: 1,
    visible: true,
  },
  {
    id: "cat-cold",
    name: "Холодные",
    description: "Для тёплого дня",
    sort_order: 2,
    visible: true,
  },
  {
    id: "cat-food",
    name: "Десерты",
    description: "К напитку",
    sort_order: 3,
    visible: true,
  },
];

let menuItems: MenuItem[] = [
  {
    id: "menu-1",
    category_id: "cat-coffee",
    name: "Флэт уайт",
    description: "Двойной эспрессо и шелковистое молоко",
    price_minor: 29000,
    volume: "250 мл",
    labels: ["хит"],
    available: true,
    visible: true,
  },
  {
    id: "menu-2",
    category_id: "cat-cold",
    name: "Эспрессо-тоник",
    description: "Тоник, цитрус и двойной эспрессо",
    price_minor: 33000,
    volume: "350 мл",
    labels: ["сезонное"],
    available: true,
    visible: true,
  },
  {
    id: "menu-3",
    category_id: "cat-food",
    name: "Баскский чизкейк",
    description: "Кремовая середина и карамельная корочка",
    price_minor: 36000,
    available: true,
    visible: true,
  },
];

let tipProfile: TipProfile = {
  display_name: "Екатерина",
  position: "Бариста",
  bio: "Люблю фильтр и умею рисовать идеальное сердце на капучино.",
  tip_url: "https://example.com/tips/demo",
  moderation_status: "approved",
};

let settings: LoyaltySettings = {
  points_enabled: true,
  currency_name: "бобы",
  rubles_per_point: 10,
  redemption_rubles_per_point: 1,
  minimum_purchase_minor: 10000,
  maximum_purchase_minor: 1_000_000,
  rounding: "floor",
  max_redemption_percent: 30,
  minimum_redemption_points: 1,
  welcome_bonus_points: 20,
  points_validity_days: null,
  daily_accrual_limit_points: null,
  operation_accrual_limit_points: null,
  large_operation_threshold_minor: 100_000,
  large_operation_requires_approval: true,
  visit_enabled: true,
  visit_goal: 5,
  visits_must_be_consecutive: true,
  visit_daily_limit: 1,
  timezone: "Europe/Moscow",
  business_day_boundary: "04:00",
  visit_allowed_misses: 1,
  visit_reset_on_miss: true,
  visit_reward_validity_days: 30,
  visit_restart_cycle: true,
  stamps_enabled: true,
  stamp_goal: 9,
  stamps_per_purchase: 1,
  stamp_operation_limit: 1,
  stamp_reward_validity_days: 30,
  reset_stamps_after_reward: true,
};

let adminUsers: AdminUser[] = [
  {
    id: "user-demo",
    telegram_id: "100000001",
    display_name: "Ярослав",
    username: "yaroslav",
    short_code: "C0FFEE42",
    balance_points: card.balance_points,
    status: "active",
    visit_streak: 3,
    stamps: 6,
    active_rewards: 1,
    created_at: new Date(Date.now() - 45 * 86_400_000).toISOString(),
  },
  {
    id: "user-anna",
    telegram_id: "100000002",
    display_name: "Анна",
    username: "anna_coffee",
    short_code: "BEAN2026",
    balance_points: 90,
    status: "active",
    visit_streak: 1,
    stamps: 2,
    active_rewards: 0,
    created_at: new Date(Date.now() - 12 * 86_400_000).toISOString(),
  },
  {
    id: "user-blocked",
    telegram_id: "100000003",
    display_name: "Дмитрий",
    short_code: "LOCK0001",
    balance_points: 20,
    status: "blocked",
    visit_streak: 0,
    stamps: 1,
    active_rewards: 0,
    created_at: new Date(Date.now() - 5 * 86_400_000).toISOString(),
  },
];

let adminStaff: AdminStaffMember[] = [
  {
    id: "staff-owner",
    user_id: "user-demo",
    telegram_id: "100000001",
    username: "yaroslav",
    display_name: "Ярослав",
    position: "Владелец",
    role: "owner",
    is_active: true,
    can_edit_tip_profile: true,
    permissions: [],
    created_at: new Date(Date.now() - 45 * 86_400_000).toISOString(),
    updated_at: now(),
  },
];

let events: AuditEvent[] = [
  {
    id: "event-1",
    type: "points.accrued",
    message:
      "Бариста Екатерина начислила Ярославу 46 баллов за покупку на 460 ₽",
    actor_name: "Екатерина",
    subject_name: "Ярослав",
    severity: "info",
    suspicious: false,
    created_at: new Date(Date.now() - 25 * 60_000).toISOString(),
  },
  {
    id: "event-2",
    type: "card.blocked_attempt",
    message: "Попытка использовать заблокированную карту",
    actor_name: "Илья",
    subject_name: "Дмитрий",
    severity: "warning",
    suspicious: true,
    created_at: new Date(Date.now() - 2 * 60 * 60_000).toISOString(),
  },
];

let feedback: AdminFeedback[] = [
  {
    id: "feedback-demo-1",
    user_id: "user-anna",
    user_display_name: "Анна",
    rating: 5,
    category: "service",
    message: "Очень тёплая команда и отличный фильтр.",
    may_contact: true,
    status: "new",
    created_at: new Date(Date.now() - 75 * 60_000).toISOString(),
  },
  {
    id: "feedback-demo-2",
    user_id: "user-demo",
    user_display_name: "Ярослав",
    rating: 3,
    category: "application",
    message: "Хочется быстрее находить историю начислений.",
    may_contact: false,
    status: "in_progress",
    internal_note: "Проверить навигацию после следующего релиза.",
    created_at: new Date(Date.now() - 2 * 86_400_000).toISOString(),
  },
];

function list<T>(items: T[]): ListResponse<T> {
  return { items, page: 1, page_size: 50, total: items.length };
}

export const demoApi = {
  async bootstrapAuth(): Promise<AuthSession> {
    await wait();
    return {
      access_token: "demo-session-token",
      expires_at: new Date(Date.now() + 15 * 60_000).toISOString(),
      actor: {
        id: "user-demo",
        telegram_id: "100000001",
        display_name: "Ярослав",
        username: "yaroslav",
        role: "owner",
        available_roles: ["customer", "staff", "admin", "owner"],
        permissions: ["points.accrue", "points.redeem", "rewards.redeem"],
      },
    };
  },
  async getHome() {
    await wait();
    return {
      card: { ...card },
      active_rewards: rewards.filter((item) => item.status === "active"),
      promotions: promotions.filter((item) => item.status === "published"),
    };
  },
  async getCard() {
    await wait();
    return { ...card };
  },
  async getHistory(type?: string) {
    await wait();
    return list(
      type ? history.filter((item) => item.type === type) : [...history],
    );
  },
  async getRewards(status?: string) {
    await wait();
    return list(
      status ? rewards.filter((item) => item.status === status) : [...rewards],
    );
  },
  async getMenu() {
    await wait();
    return { categories: [...categories], items: [...menuItems] };
  },
  async getMore(): Promise<PublicMoreData> {
    await wait();
    return {
      contacts: {
        coffee_shop_name: "Тёплое зерно",
        description: "Небольшая кофейня по соседству",
        support_contact: "@coffee_support",
        privacy_policy:
          "Мы используем Telegram ID только для работы карты лояльности и не передаём данные третьим лицам.",
        locations: [
          {
            id: "location-1",
            name: "Тёплое зерно",
            address: "Москва, Кофейный переулок, 8",
            hours: "Ежедневно 08:00–22:00",
            phone: "+7 000 000-00-00",
            map_url: "https://example.com/map",
          },
        ],
      },
      staff: [
        {
          id: "staff-kate",
          display_name: "Екатерина",
          position: "Бариста",
          bio: "Посоветует зерно под настроение",
          tip_url: "https://example.com/tips/demo",
        },
      ],
      promotions: promotions.filter((item) => item.status === "published"),
    };
  },
  async submitFeedback(payload: unknown) {
    void payload;
    await wait();
    return { id: `feedback-${Date.now()}`, status: "new" };
  },
  async lookupStaffClient(payload: {
    qr_token?: string;
    short_code?: string;
  }): Promise<StaffClient> {
    await wait();
    if (!payload.qr_token && !payload.short_code)
      throw new ApiError("Введите код карты", {
        status: 422,
        code: "invalid_card_code",
      });
    if (payload.short_code?.toUpperCase() === "UNKNOWN")
      throw new ApiError("Карта не найдена или QR устарел", {
        status: 404,
        code: "card_not_found",
      });
    return {
      user_id: card.user_id,
      display_name: card.display_name,
      short_code: card.short_code,
      masked_short_code: `••••${card.short_code.slice(-4)}`,
      balance_points: card.balance_points,
      currency_name: card.currency_name,
      visit_streak: card.visit_streak,
      visit_goal: card.visit_goal,
      stamps: card.stamps,
      stamp_goal: card.stamp_goal,
      available_rewards: rewards.filter((item) => item.status === "active"),
      blocked: card.blocked,
      suspicious: false,
      recent_operations: history.slice(0, 3),
    };
  },
  async previewAccrual(payload: {
    user_id: string;
    purchase_amount_minor: number;
  }): Promise<AccrualPreview> {
    await wait();
    if (payload.purchase_amount_minor <= 0)
      throw new ApiError("Сумма покупки должна быть больше нуля", {
        status: 422,
        code: "invalid_purchase_amount",
      });
    const points = Math.floor(
      payload.purchase_amount_minor / 100 / settings.rubles_per_point,
    );
    return {
      user_id: payload.user_id,
      customer_name: card.display_name,
      purchase_amount_minor: payload.purchase_amount_minor,
      points_to_accrue: points,
      balance_before: card.balance_points,
      balance_after: card.balance_points + points,
      requires_approval: payload.purchase_amount_minor >= 100_000,
    };
  },
  async confirmAccrual(payload: {
    user_id: string;
    purchase_amount_minor: number;
  }): Promise<OperationResult> {
    const preview = await this.previewAccrual(payload);
    card = {
      ...card,
      balance_points: preview.balance_after,
      updated_at: now(),
    };
    const operation: HistoryItem = {
      id: `op-${Date.now()}`,
      type: "purchase_accrual",
      description: `Начислено за покупку на ${Math.round(payload.purchase_amount_minor / 100)} ₽`,
      delta_points: preview.points_to_accrue,
      balance_after: preview.balance_after,
      created_at: now(),
      status: preview.requires_approval ? "pending" : "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      status: preview.requires_approval ? "pending" : "completed",
      delta_points: preview.points_to_accrue,
      balance_after: preview.balance_after,
      created_at: operation.created_at,
    };
  },
  async previewPurchase(payload: {
    user_id: string;
    purchase_amount_minor: number;
    stamps_to_add: number;
  }): Promise<PurchasePreview> {
    const accrual = await this.previewAccrual(payload);
    if (!Number.isInteger(payload.stamps_to_add) || payload.stamps_to_add < 0)
      throw new ApiError("Количество штампов должно быть целым", {
        status: 422,
        code: "invalid_stamp_state",
      });
    const stampTotal = card.stamps + payload.stamps_to_add;
    const stampRewards = Math.floor(stampTotal / card.stamp_goal);
    const today = new Date().toISOString().slice(0, 10);
    const visitWillBeRecorded = lastAutomaticVisitDate !== today;
    return {
      ...accrual,
      stamps_to_add: payload.stamps_to_add,
      stamps_before: card.stamps,
      stamps_after: stampTotal % card.stamp_goal,
      stamp_rewards_earned: stampRewards,
      visit_will_be_recorded: visitWillBeRecorded,
      visit_already_counted: !visitWillBeRecorded,
      visit_streak_after: visitWillBeRecorded
        ? (card.visit_streak + 1) % card.visit_goal
        : card.visit_streak,
    };
  },
  async confirmPurchase(payload: {
    user_id: string;
    purchase_amount_minor: number;
    stamps_to_add: number;
  }): Promise<OperationResult> {
    const preview = await this.previewPurchase(payload);
    if (!preview.requires_approval) {
      card = {
        ...card,
        balance_points: preview.balance_after,
        stamps: preview.stamps_after,
        visit_streak: preview.visit_streak_after,
        updated_at: now(),
      };
      if (preview.visit_will_be_recorded) {
        lastAutomaticVisitDate = new Date().toISOString().slice(0, 10);
      }
    }
    const operation: HistoryItem = {
      id: `purchase-${Date.now()}`,
      type: "purchase_accrual",
      description: `Покупка на ${Math.round(payload.purchase_amount_minor / 100)} ₽`,
      delta_points: preview.points_to_accrue,
      balance_after: preview.requires_approval ? null : preview.balance_after,
      created_at: now(),
      status: preview.requires_approval ? "pending" : "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      operation_type: operation.type,
      status: operation.status,
      delta_points: preview.points_to_accrue,
      balance_after: preview.balance_after,
      created_at: operation.created_at,
      streak_after: preview.requires_approval
        ? null
        : preview.visit_streak_after,
      stamps_after: preview.requires_approval ? null : preview.stamps_after,
      reward_ids: [],
    };
  },
  async previewRedemption(payload: {
    user_id: string;
    purchase_amount_minor: number;
    requested_points: number;
  }): Promise<RedemptionPreview> {
    await wait();
    const maximum = Math.min(
      card.balance_points,
      Math.floor(
        (payload.purchase_amount_minor / 100) *
          (settings.max_redemption_percent / 100),
      ),
    );
    if (payload.requested_points > maximum)
      throw new ApiError(`Можно списать не больше ${maximum} баллов`, {
        status: 409,
        code: "redemption_limit",
      });
    return {
      user_id: payload.user_id,
      customer_name: card.display_name,
      purchase_amount_minor: payload.purchase_amount_minor,
      requested_points: payload.requested_points,
      discount_minor: payload.requested_points * 100,
      maximum_points_for_purchase: maximum,
      balance_before: card.balance_points,
      balance_after: card.balance_points - payload.requested_points,
    };
  },
  async confirmRedemption(payload: {
    user_id: string;
    purchase_amount_minor: number;
    requested_points: number;
  }): Promise<OperationResult> {
    const preview = await this.previewRedemption(payload);
    card = {
      ...card,
      balance_points: preview.balance_after,
      updated_at: now(),
    };
    const operation: HistoryItem = {
      id: `op-${Date.now()}`,
      type: "points_redemption",
      description: `Списано ${payload.requested_points} баллов`,
      delta_points: -payload.requested_points,
      balance_after: preview.balance_after,
      created_at: now(),
      status: "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      operation_type: operation.type,
      status: "completed",
      delta_points: operation.delta_points ?? 0,
      balance_after: preview.balance_after,
      created_at: operation.created_at,
    };
  },
  async markVisit(userId: string): Promise<OperationResult> {
    void userId;
    await wait();
    card = { ...card, visit_streak: card.visit_streak + 1, updated_at: now() };
    const operation: HistoryItem = {
      id: `visit-${Date.now()}`,
      type: "visit_mark",
      description: "Отмечено посещение",
      delta_points: 0,
      balance_after: card.balance_points,
      created_at: now(),
      status: "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      operation_type: operation.type,
      status: "completed",
      delta_points: 0,
      balance_after: card.balance_points,
      created_at: operation.created_at,
      streak_after: card.visit_streak,
    };
  },
  async addStamp(userId: string): Promise<OperationResult> {
    void userId;
    await wait();
    card = { ...card, stamps: card.stamps + 1, updated_at: now() };
    const operation: HistoryItem = {
      id: `stamp-${Date.now()}`,
      type: "stamp_added",
      description: "Добавлен штамп",
      delta_points: 0,
      balance_after: card.balance_points,
      created_at: now(),
      status: "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      operation_type: operation.type,
      status: "completed",
      delta_points: 0,
      balance_after: card.balance_points,
      created_at: operation.created_at,
      stamps_after: card.stamps,
    };
  },
  async redeemReward(rewardId: string): Promise<OperationResult> {
    await wait();
    const reward = rewards.find(
      (candidate) => candidate.id === rewardId && candidate.status === "active",
    );
    if (!reward)
      throw new ApiError("Активная награда не найдена", {
        status: 404,
        code: "reward_not_found",
      });
    rewards = rewards.map((candidate) =>
      candidate.id === rewardId
        ? { ...candidate, status: "redeemed", redeemed_at: now() }
        : candidate,
    );
    const operation: HistoryItem = {
      id: `reward-${Date.now()}`,
      type: "reward_redeemed",
      description: `Погашена награда «${reward.title}»`,
      delta_points: 0,
      balance_after: card.balance_points,
      created_at: now(),
      status: "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      operation_type: operation.type,
      status: "completed",
      delta_points: 0,
      balance_after: card.balance_points,
      created_at: operation.created_at,
      reward_ids: [rewardId],
    };
  },
  async reverseOperation(
    operationId: string,
    reason: string,
  ): Promise<OperationResult> {
    await wait();
    if (!reason.trim())
      throw new ApiError("Укажите причину отмены", {
        status: 422,
        code: "reason_required",
      });
    const original = history.find((item) => item.id === operationId);
    if (!original)
      throw new ApiError("Операция не найдена", {
        status: 404,
        code: "operation_not_found",
      });
    const delta = -(original.delta_points ?? 0);
    card = {
      ...card,
      balance_points: card.balance_points + delta,
      updated_at: now(),
    };
    const operation: HistoryItem = {
      id: `reverse-${Date.now()}`,
      type: "operation_reversal",
      description: `Операция отменена: ${reason.trim()}`,
      delta_points: delta,
      balance_after: card.balance_points,
      created_at: now(),
      status: "completed",
    };
    history = [operation, ...history];
    return {
      operation_id: operation.id,
      operation_type: operation.type,
      status: "completed",
      delta_points: delta,
      balance_after: card.balance_points,
      created_at: operation.created_at,
    };
  },
  async getRecentOperations() {
    await wait();
    return list(history.slice(0, 8));
  },
  async getTipProfile() {
    await wait();
    return { ...tipProfile };
  },
  async saveTipProfile(profile: TipProfile) {
    await wait();
    tipProfile = { ...profile, moderation_status: "pending_review" };
    return { ...tipProfile };
  },
  async getAdminOverview(): Promise<AdminOverview> {
    await wait();
    return {
      users_total: adminUsers.length,
      blocked_users: adminUsers.filter((item) => item.status === "blocked")
        .length,
      suspicious_events: events.filter((item) => item.suspicious).length,
      active_promotions: promotions.filter(
        (item) => item.status === "published",
      ).length,
      recent_events: events.slice(0, 5),
    };
  },
  async getAdminUsers(query?: string, status?: string) {
    await wait();
    const normalized = query?.trim().toLowerCase();
    return list(
      adminUsers.filter((user) => {
        const matchesQuery =
          !normalized ||
          [user.display_name, user.username, user.short_code, user.telegram_id]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(normalized));
        return matchesQuery && (!status || user.status === status);
      }),
    );
  },
  async getAdminUser(id: string) {
    await wait();
    const user = adminUsers.find((item) => item.id === id);
    if (!user)
      throw new ApiError("Пользователь не найден", {
        status: 404,
        code: "user_not_found",
      });
    return { ...user };
  },
  async getAdminEvents(filters: { severity?: string; suspicious?: boolean }) {
    await wait();
    return list(
      events.filter(
        (event) =>
          (!filters.severity || event.severity === filters.severity) &&
          (filters.suspicious === undefined ||
            event.suspicious === filters.suspicious),
      ),
    );
  },
  async getAdminFeedback(status?: string) {
    await wait();
    return list(
      status
        ? feedback.filter((item) => item.status === status)
        : [...feedback],
    );
  },
  async updateAdminFeedback(
    id: string,
    payload: {
      status: AdminFeedback["status"];
      internal_note?: string | null;
    },
  ) {
    await wait();
    const item = feedback.find((candidate) => candidate.id === id);
    if (!item)
      throw new ApiError("Отзыв не найден", {
        status: 404,
        code: "feedback_not_found",
      });
    const updated: AdminFeedback = {
      ...item,
      ...payload,
      resolved_at:
        payload.status === "resolved" ? new Date().toISOString() : null,
    };
    feedback = feedback.map((candidate) =>
      candidate.id === id ? updated : candidate,
    );
    return { ...updated };
  },
  async deleteAdminFeedback(id: string) {
    await wait();
    const item = feedback.find((candidate) => candidate.id === id);
    if (!item)
      throw new ApiError("Отзыв не найден", {
        status: 404,
        code: "feedback_not_found",
      });
    if (item.status !== "archived")
      throw new ApiError("Сначала переместите отзыв в архив", {
        status: 409,
        code: "feedback_not_archived",
      });
    feedback = feedback.filter((candidate) => candidate.id !== id);
  },
  async getAdminStaff(query?: string, active?: boolean) {
    await wait();
    const normalized = query?.trim().toLowerCase();
    return list(
      adminStaff.filter((item) => {
        const matchesQuery =
          !normalized ||
          [item.display_name, item.username, item.position, item.telegram_id]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(normalized));
        return (
          matchesQuery && (active === undefined || item.is_active === active)
        );
      }),
    );
  },
  async createAdminStaff(
    payload: StaffMemberDraft & {
      user_id: string;
      role: Exclude<Role, "customer">;
    },
  ) {
    await wait();
    const user = adminUsers.find(
      (candidate) => candidate.id === payload.user_id,
    );
    if (!user)
      throw new ApiError("Клиент не найден", {
        status: 404,
        code: "user_not_found",
      });
    if (adminStaff.some((candidate) => candidate.user_id === payload.user_id))
      throw new ApiError("У клиента уже есть профиль сотрудника", {
        status: 409,
        code: "staff_exists",
      });
    const item: AdminStaffMember = {
      id: `staff-${Date.now()}`,
      user_id: user.id,
      telegram_id: user.telegram_id,
      username: user.username,
      display_name: payload.display_name || user.display_name,
      position: payload.position,
      bio: payload.bio,
      role: payload.role,
      is_active: true,
      can_edit_tip_profile: payload.can_edit_tip_profile,
      permissions: Object.entries(payload.permissions).map(
        ([permission, allowed]) => ({
          permission:
            permission as AdminStaffMember["permissions"][number]["permission"],
          allowed: Boolean(allowed),
        }),
      ),
      created_at: now(),
      updated_at: now(),
    };
    adminStaff = [...adminStaff, item];
    return { ...item };
  },
  async updateAdminStaff(
    id: string,
    payload: Partial<StaffMemberDraft> & { is_active?: boolean },
  ) {
    await wait();
    const item = adminStaff.find((candidate) => candidate.id === id);
    if (!item)
      throw new ApiError("Сотрудник не найден", {
        status: 404,
        code: "staff_not_found",
      });
    const updated: AdminStaffMember = {
      ...item,
      ...payload,
      display_name: payload.display_name ?? item.display_name,
      permissions: payload.permissions
        ? Object.entries(payload.permissions).map(([permission, allowed]) => ({
            permission:
              permission as AdminStaffMember["permissions"][number]["permission"],
            allowed: Boolean(allowed),
          }))
        : item.permissions,
      updated_at: now(),
    };
    adminStaff = adminStaff.map((candidate) =>
      candidate.id === id ? updated : candidate,
    );
    return { ...updated };
  },
  async deleteAdminStaff(id: string) {
    await wait();
    if (!adminStaff.some((candidate) => candidate.id === id))
      throw new ApiError("Сотрудник не найден", {
        status: 404,
        code: "staff_not_found",
      });
    adminStaff = adminStaff.filter((candidate) => candidate.id !== id);
  },
  async changeAdminStaffRole(id: string, role: Exclude<Role, "customer">) {
    await wait();
    const item = adminStaff.find((candidate) => candidate.id === id);
    if (!item)
      throw new ApiError("Сотрудник не найден", {
        status: 404,
        code: "staff_not_found",
      });
    const updated = { ...item, role, permissions: [], updated_at: now() };
    adminStaff = adminStaff.map((candidate) =>
      candidate.id === id ? updated : candidate,
    );
    return { ...updated };
  },
  async revokeAdminStaffSessions(id: string) {
    await wait();
    if (!adminStaff.some((candidate) => candidate.id === id))
      throw new ApiError("Сотрудник не найден", {
        status: 404,
        code: "staff_not_found",
      });
    return { revoked_sessions: 1 };
  },
  async getSettings() {
    await wait();
    return { ...settings };
  },
  async saveSettings(value: LoyaltySettings) {
    await wait();
    settings = { ...value };
    return { ...settings };
  },
  async toggleMenuItem(item: MenuItem) {
    await wait();
    const updated = { ...item, visible: !item.visible };
    menuItems = menuItems.map((candidate) =>
      candidate.id === item.id ? updated : candidate,
    );
    return updated;
  },
  async saveMenuCategory(
    category: MenuCategory | null,
    payload: MenuCategoryDraft,
  ) {
    await wait();
    const updated: MenuCategory = {
      id: category?.id ?? `category-${Date.now()}`,
      ...payload,
    };
    categories = category
      ? categories.map((candidate) =>
          candidate.id === category.id ? updated : candidate,
        )
      : [...categories, updated];
    return { ...updated };
  },
  async saveMenuItem(item: MenuItem | null, payload: MenuItemDraft) {
    await wait();
    const updated: MenuItem = {
      id: item?.id ?? `item-${Date.now()}`,
      ...payload,
    };
    menuItems = item
      ? menuItems.map((candidate) =>
          candidate.id === item.id ? updated : candidate,
        )
      : [...menuItems, updated];
    return { ...updated };
  },
  async getAdminPromotions() {
    await wait();
    return list([...promotions]);
  },
  async publishPromotion(promotion: Promotion) {
    await wait();
    const updated: Promotion = { ...promotion, status: "published" };
    promotions = promotions.map((candidate) =>
      candidate.id === promotion.id ? updated : candidate,
    );
    return updated;
  },
  async savePromotion(promotion: Promotion | null, payload: PromotionDraft) {
    await wait();
    const updated: Promotion = {
      id: promotion?.id ?? `promotion-${Date.now()}`,
      status: promotion?.status ?? "draft",
      ...payload,
      created_at: promotion?.created_at ?? now(),
      updated_at: now(),
    };
    promotions = promotion
      ? promotions.map((candidate) =>
          candidate.id === promotion.id ? updated : candidate,
        )
      : [...promotions, updated];
    return { ...updated };
  },
  async archivePromotion(promotion: Promotion) {
    await wait();
    const updated: Promotion = { ...promotion, status: "archived" };
    promotions = promotions.map((candidate) =>
      candidate.id === promotion.id ? updated : candidate,
    );
    return updated;
  },
  async confirmAdjustment(payload: {
    user_id: string;
    delta_points: number;
    reason: string;
  }): Promise<OperationResult> {
    await wait();
    if (!payload.reason.trim())
      throw new ApiError("Укажите причину корректировки", {
        status: 422,
        code: "reason_required",
      });
    const user = adminUsers.find(
      (candidate) => candidate.id === payload.user_id,
    );
    if (!user)
      throw new ApiError("Пользователь не найден", {
        status: 404,
        code: "user_not_found",
      });
    const newBalance = user.balance_points + payload.delta_points;
    if (newBalance < 0)
      throw new ApiError("Баланс не может стать отрицательным", {
        status: 409,
        code: "insufficient_balance",
      });
    adminUsers = adminUsers.map((candidate) =>
      candidate.id === user.id
        ? { ...candidate, balance_points: newBalance }
        : candidate,
    );
    if (user.id === card.user_id)
      card = { ...card, balance_points: newBalance, updated_at: now() };
    const operationId = `adjustment-${Date.now()}`;
    events = [
      {
        id: `event-${Date.now()}`,
        type: "balance.adjusted",
        message: `Администратор скорректировал баланс ${user.display_name} на ${payload.delta_points} баллов. Причина: ${payload.reason}`,
        actor_name: "Владелец",
        subject_name: user.display_name,
        severity: "warning",
        suspicious: false,
        created_at: now(),
      },
      ...events,
    ];
    return {
      operation_id: operationId,
      status: "completed",
      delta_points: payload.delta_points,
      balance_after: newBalance,
      created_at: now(),
    };
  },
};

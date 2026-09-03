import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { CartProvider } from "../components/CartContext";
import type {
  AdminFeedback,
  AdminLoyaltyV2Settings,
  AdminStaffMember,
  AdminUserListItem,
  AdminUser,
  CardData,
  ContactLocation,
  ContactsData,
  CustomerMergePreview,
  CustomerMergeResult,
  LoyaltySettings,
  MenuCategory,
  OperationResult,
  PurchasePreview,
  RedemptionPreview,
  StaffClient,
  StaffPassLookup,
  Venue,
} from "../api/types";
import {
  CardPage,
  getTimeGreeting,
  HomePage,
  MenuPage,
  MorePage,
  RewardsPage,
} from "../pages/customer";
import {
  AccrualPanel,
  ClientPreviewPage,
  QuickOperationsPanel,
  ScannerPage,
  STAFF_LOCATION_STORAGE_KEY,
  StaffWorkspaceProvider,
  SubscriptionRedemptionDialog,
} from "../pages/staff";
import {
  AdminAdjustmentPage,
  AdminCustomerMergePage,
  AdminFeedbackPage,
  AdminMenuPage,
  AdminPromotionsPage,
  AdminSettingsPage,
  AdminStaffPage,
  AdminUsersPage,
} from "../pages/admin";
import { AdminAnalyticsPage, AdminHelpPage } from "../pages/web-admin";
import { AuthContext, AuthProvider } from "../auth/AuthContext";
import { AuthGate } from "../components/AppShell";
import {
  SELECTED_VENUE_STORAGE_KEY,
  VenueSelector,
  useVenueSelection,
} from "../components/VenueSelector";
import { applyTheme, readTheme } from "../theme";

const card: CardData = {
  user_id: "user-1",
  display_name: "Анна",
  qr_payload: "opaque-card-token",
  short_code: "BEAN2026",
  balance_points: 284,
  currency_name: "бобов",
  visits_enabled: true,
  visit_streak: 3,
  visit_goal: 5,
  stamps_enabled: true,
  stamps: 6,
  stamp_goal: 9,
  blocked: false,
  updated_at: "2026-07-21T10:00:00Z",
};

const client: StaffClient = {
  user_id: "user-1",
  display_name: "Анна",
  short_code: "BEAN2026",
  masked_short_code: "••••2026",
  balance_points: 284,
  currency_name: "бобов",
  visit_streak: 3,
  visit_goal: 5,
  stamps: 6,
  stamp_goal: 9,
  available_rewards: [],
  blocked: false,
  suspicious: false,
  recent_operations: [],
};

const coffeeVenue: Venue = {
  id: "venue-coffee",
  slug: "coffee-point",
  name: "Кофейня и точка",
  description: "Кофе и десерты",
  phone: null,
  email: null,
  website: null,
  telegram: null,
  logo_url: null,
  sort_order: 10,
};

const foodVenue: Venue = {
  id: "venue-food",
  slug: "food-court",
  name: "ФудДворик",
  description: "Еда и напитки",
  phone: null,
  email: null,
  website: null,
  telegram: null,
  logo_url: null,
  sort_order: 20,
};

const grillVenue: Venue = {
  id: "venue-grill",
  slug: "shashlik-dzhan",
  name: "Шашлык Джан",
  description: "Блюда на огне",
  phone: null,
  email: null,
  website: null,
  telegram: null,
  logo_url: null,
  sort_order: 30,
};

const venues = [coffeeVenue, foodVenue, grillVenue];

const staffLocations: ContactLocation[] = [
  {
    id: "location-coffee",
    venue_id: coffeeVenue.id,
    name: "Кофейня на Ленина",
    address: "ул. Ленина, 1",
    hours: "08:00–22:00",
  },
  {
    id: "location-food",
    venue_id: foodVenue.id,
    name: "ФудДворик в парке",
    address: "Парковая ул., 7",
    hours: "10:00–23:00",
  },
];

const staffContacts: ContactsData = {
  coffee_shop_name: "Coffie Bot",
  description: "",
  privacy_policy: "",
  locations: staffLocations,
};

function adminLoyaltySettings(
  walletMode: AdminLoyaltyV2Settings["wallet_mode"],
): AdminLoyaltyV2Settings {
  return {
    wallet_mode: walletMode,
    point_value_minor: 100,
    max_redemption_percent: 50,
    expiry_months: 6,
    expiry_days_override: null,
    expiry_reminder_days: 14,
    default_bonus_venue_id: coffeeVenue.id,
    rounding: "floor",
    venue_rates: [
      {
        venue_id: coffeeVenue.id,
        venue_name: coffeeVenue.name,
        available: true,
        loyalty_points_enabled: true,
        accrual_basis_points: 1_000,
        rounding_mode: "floor",
      },
      {
        venue_id: foodVenue.id,
        venue_name: foodVenue.name,
        available: true,
        loyalty_points_enabled: true,
        accrual_basis_points: 700,
        rounding_mode: "half_up",
      },
    ],
    birthday: {
      enabled: true,
      discount_percent: 10,
      window_days: 7,
      eligible_venue_ids: [],
      stackable: false,
    },
  };
}

function VenueSelectionHarness({ items }: { items: Venue[] }) {
  const selection = useVenueSelection(items);
  return (
    <VenueSelector
      venues={items}
      selectedVenueId={selection.selectedVenueId}
      onSelect={selection.selectVenue}
    />
  );
}

describe("critical Mini App flows", () => {
  it("renders PostgreSQL admin analytics and changes the reporting period", async () => {
    const user = userEvent.setup();
    const analytics = vi
      .spyOn(coffeeApi, "getAdminAnalytics")
      .mockResolvedValue({
        generated_at: "2026-08-28T09:00:00Z",
        days: 30,
        started_at: "2026-07-29T09:00:00Z",
        ended_at: "2026-08-28T09:00:00Z",
        orders_by_day: [
          { day: "2026-08-28", orders: 4, revenue_minor: 120000 },
        ],
        orders_by_venue: [
          { id: "venue-1", name: "Кофейня", count: 4, amount_minor: 120000 },
        ],
        popular_items: [],
        promotion_usage: [],
        employee_activity: [],
        loyalty: { accrued_points: 30, redeemed_points: 10 },
        customers: { active_customers: 3, repeat_customers: 1 },
        subscriptions: { issued: 1, uses: 2, active: 1 },
        receipts: { created: 2, amount_minor: 50000, suspicious: 1 },
        delivery: { orders: 2, completed: 1, cancelled: 0 },
      });

    render(
      <MemoryRouter>
        <AdminAnalyticsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Заказы по дням")).toBeInTheDocument();
    expect(screen.getByText("Кофейня")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "7 дней" }));
    await waitFor(() => expect(analytics).toHaveBeenLastCalledWith(7));
  });

  it("keeps the operational help available inside the admin", () => {
    render(
      <MemoryRouter>
        <AdminHelpPage />
      </MemoryRouter>,
    );

    expect(screen.getByText("Добавить сотрудника")).toBeInTheDocument();
    expect(screen.getByText("Назначить курьера")).toBeInTheDocument();
    expect(screen.getByText("Проверить suspicious event")).toBeInTheDocument();
  });

  it("delegates empty initData acceptance to the backend DEV_AUTH boundary", async () => {
    const originalDemoMode = coffeeApi.isDemo;
    coffeeApi.isDemo = false;
    window.sessionStorage.clear();
    const bootstrap = vi.spyOn(coffeeApi, "bootstrapAuth").mockResolvedValue({
      access_token: "local-dev-session",
      expires_at: "2026-08-24T12:00:00Z",
      actor: {
        id: "local-owner",
        telegram_id: "1000000000000",
        display_name: "Локальный владелец",
        role: "owner",
        available_roles: ["customer", "owner"],
        permissions: [],
      },
    });

    try {
      render(
        <AuthProvider>
          <AuthContext.Consumer>
            {(auth) => <span>{auth?.actor?.display_name ?? "Входим"}</span>}
          </AuthContext.Consumer>
        </AuthProvider>,
      );

      expect(await screen.findByText("Локальный владелец")).toBeInTheDocument();
      expect(bootstrap).toHaveBeenCalledWith("");
    } finally {
      coffeeApi.isDemo = originalDemoMode;
      window.sessionStorage.clear();
    }
  });

  it("renders the personal card with an opaque QR and short code", async () => {
    vi.spyOn(coffeeApi, "getCard").mockResolvedValue(card);
    render(
      <MemoryRouter>
        <CardPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Анна")).toBeInTheDocument();
    expect(screen.getByTestId("customer-card-qr")).toBeInTheDocument();
    expect(screen.getByLabelText("Короткий код BEAN2026")).toBeInTheDocument();
    expect(screen.getByText("284")).toBeInTheDocument();
  });

  it("falls back to manual code and opens the scanned client", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getContacts").mockResolvedValue(staffContacts);
    const lookup = vi
      .spyOn(coffeeApi, "lookupStaffClient")
      .mockResolvedValue(client);
    render(
      <MemoryRouter initialEntries={["/staff/scan"]}>
        <StaffWorkspaceProvider>
          <Routes>
            <Route path="/staff/scan" element={<ScannerPage />} />
            <Route
              path="/staff/client/:userId"
              element={<div>Карточка найдена</div>}
            />
          </Routes>
        </StaffWorkspaceProvider>
      </MemoryRouter>,
    );

    await user.click(
      screen.getByRole("button", { name: /открыть сканер telegram/i }),
    );
    expect(screen.getByText(/сканер Telegram недоступен/i)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Короткий код"), "bean2026");
    await user.click(screen.getByRole("button", { name: /найти клиента/i }));

    expect(await screen.findByText("Карточка найдена")).toBeInTheDocument();
    expect(lookup).toHaveBeenCalledWith({ short_code: "BEAN2026" });
  });

  it("uses a scanned subscription in a dedicated confirmation flow", async () => {
    const user = userEvent.setup();
    const lookup: StaffPassLookup = {
      customer_name: "Анна",
      customer_short_code: "BEAN2026",
      subscription: {
        id: "pass-1",
        template_id: "template-1",
        user_id: "user-1",
        name: "Кофейный месяц",
        description: "Один напиток каждый день",
        image_media_id: null,
        image_url: null,
        qr_payload: "coffee-pass:v1:opaque-token",
        total_uses: 30,
        remaining_uses: 12,
        status: "active",
        issued_at: "2026-09-01T10:00:00Z",
        expires_at: "2026-10-01T10:00:00Z",
        usage_count: 18,
        replay: false,
      },
    };
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [],
      items: [
        {
          id: "item-1",
          venue_id: "venue-coffee",
          category_id: "category-1",
          name: "Капучино",
          price_minor: 25000,
          available: true,
          visible: true,
        },
      ],
    });
    const usePass = vi.spyOn(coffeeApi, "usePass").mockResolvedValue({
      id: "usage-1",
      pass_id: "pass-1",
      venue_id: "venue-coffee",
      item_id: "item-1",
      uses_before: 12,
      uses_after: 11,
      created_at: "2026-09-03T12:00:00Z",
      replay: false,
    });
    const cancel = vi.fn();
    const next = vi.fn();

    render(
      <MemoryRouter>
        <SubscriptionRedemptionDialog
          lookup={lookup}
          venueId="venue-coffee"
          onCancel={cancel}
          onNext={next}
        />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Кофейный месяц")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Использовать" }));
    expect(
      screen.getByRole("heading", { name: "Списать одно использование?" }),
    ).toBeInTheDocument();
    await user.selectOptions(
      await screen.findByLabelText("Позиция заказа"),
      "item-1",
    );
    await user.click(
      screen.getByRole("button", { name: "Подтвердить использование" }),
    );

    expect(
      await screen.findByRole("heading", {
        name: "Абонемент успешно использован",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/осталось/i)).toHaveTextContent("11");
    expect(usePass).toHaveBeenCalledWith(
      "pass-1",
      "venue-coffee",
      "item-1",
      expect.any(String),
    );
    await user.click(screen.getByRole("button", { name: "Следующий заказ" }));
    expect(next).toHaveBeenCalledOnce();
    expect(cancel).not.toHaveBeenCalled();
  });

  it("passes a formatted phone to the backend customer lookup", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getContacts").mockResolvedValue(staffContacts);
    const lookup = vi
      .spyOn(coffeeApi, "lookupStaffClient")
      .mockResolvedValue(client);
    render(
      <MemoryRouter initialEntries={["/staff/scan"]}>
        <StaffWorkspaceProvider>
          <Routes>
            <Route path="/staff/scan" element={<ScannerPage />} />
            <Route
              path="/staff/client/:userId"
              element={<div>Клиент найден по телефону</div>}
            />
          </Routes>
        </StaffWorkspaceProvider>
      </MemoryRouter>,
    );

    await user.type(
      screen.getByLabelText("Телефон клиента"),
      "8 (999) 123-45-67",
    );
    await user.click(screen.getByRole("button", { name: "Найти по телефону" }));

    expect(
      await screen.findByText("Клиент найден по телефону"),
    ).toBeInTheDocument();
    expect(lookup).toHaveBeenCalledWith({ phone: "8 (999) 123-45-67" });
  });

  it("reuses one idempotency key when phone customer creation is retried", async () => {
    const user = userEvent.setup();
    window.sessionStorage.removeItem(STAFF_LOCATION_STORAGE_KEY);
    vi.spyOn(coffeeApi, "getContacts").mockResolvedValue(staffContacts);
    const phoneClient: StaffClient = {
      ...client,
      user_id: "user-phone",
      display_name: "Мария",
      short_code: "PHONE123",
      masked_short_code: "••••E123",
      balance_points: 0,
    };
    const create = vi
      .spyOn(coffeeApi, "createPhoneCustomer")
      .mockRejectedValueOnce(new Error("Соединение потеряно"))
      .mockResolvedValue({
        user_id: phoneClient.user_id,
        card_id: "card-phone",
        display_name: phoneClient.display_name,
        masked_phone: "+7*******4567",
        short_code: phoneClient.short_code,
        points_balance: 0,
        idempotent_replay: true,
      });
    const lookup = vi
      .spyOn(coffeeApi, "lookupStaffClient")
      .mockResolvedValue(phoneClient);
    render(
      <MemoryRouter initialEntries={["/staff/scan"]}>
        <StaffWorkspaceProvider>
          <Routes>
            <Route path="/staff/scan" element={<ScannerPage />} />
            <Route
              path="/staff/client/:userId"
              element={<ClientPreviewPage />}
            />
          </Routes>
        </StaffWorkspaceProvider>
      </MemoryRouter>,
    );

    const locationSelector = await screen.findByLabelText(
      "Активная физическая точка",
    );
    await user.selectOptions(locationSelector, staffLocations[1]!.id);
    expect(screen.getByText(/Сейчас:/)).toHaveTextContent(
      staffLocations[1]!.name,
    );
    await user.click(
      screen.getByRole("button", { name: "Создать нового клиента" }),
    );
    await user.type(
      screen.getByLabelText("Телефон нового клиента"),
      "+7 999 123-45-67",
    );
    await user.type(screen.getByLabelText("Имя"), "Мария");
    await user.click(screen.getByRole("button", { name: "Создать карту" }));

    expect(await screen.findByText("Соединение потеряно")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Создать карту" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Мария" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Активная физическая точка")).toHaveValue(
      staffLocations[1]!.id,
    );
    expect(create).toHaveBeenCalledTimes(2);
    expect(create.mock.calls[0]?.[0]).toEqual({
      phone: "+7 999 123-45-67",
      display_name: "Мария",
      venue_id: foodVenue.id,
    });
    const firstKey = create.mock.calls[0]?.[1];
    const retryKey = create.mock.calls[1]?.[1];
    expect(firstKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(retryKey).toBe(firstKey);
    expect(lookup).toHaveBeenCalledWith({ phone: "+7 999 123-45-67" });
    expect(window.sessionStorage.getItem(STAFF_LOCATION_STORAGE_KEY)).toBe(
      staffLocations[1]!.id,
    );
    window.sessionStorage.removeItem(STAFF_LOCATION_STORAGE_KEY);
  });

  it("previews and confirms a purchase with stamps and automatic visit", async () => {
    const user = userEvent.setup();
    const preview: PurchasePreview = {
      user_id: client.user_id,
      customer_name: client.display_name,
      purchase_amount_minor: 46000,
      points_to_accrue: 46,
      balance_before: 284,
      balance_after: 330,
      stamps_to_add: 2,
      stamps_before: 6,
      stamps_after: 8,
      stamp_rewards_earned: 0,
      reward_bonus_points: 0,
      visit_will_be_recorded: true,
      visit_already_counted: false,
      visit_streak_after: 4,
      requires_approval: false,
      location_id: staffLocations[0]!.id,
    };
    const operation: OperationResult = {
      operation_id: "operation-1",
      status: "completed",
      delta_points: 46,
      balance_after: 330,
      created_at: "2026-07-21T10:00:00Z",
      stamps_after: 8,
      streak_after: 4,
    };
    const previewCall = vi
      .spyOn(coffeeApi, "previewPurchase")
      .mockResolvedValue(preview);
    const confirmCall = vi
      .spyOn(coffeeApi, "confirmPurchase")
      .mockResolvedValue(operation);
    const newPurchase = vi.fn();
    render(
      <AccrualPanel
        client={client}
        location={staffLocations[0]!}
        onNewPurchase={newPurchase}
      />,
    );

    await user.type(screen.getByLabelText(/сумма покупки/i), "460");
    await user.clear(screen.getByLabelText(/штампы за покупку/i));
    await user.type(screen.getByLabelText(/штампы за покупку/i), "2");
    await user.click(screen.getByRole("button", { name: "Рассчитать" }));
    expect(
      await screen.findByLabelText("Предпросмотр покупки"),
    ).toHaveTextContent("Баланс после покупки");
    expect(screen.getByLabelText("Предпросмотр покупки")).toHaveTextContent(
      "330",
    );
    await user.click(
      screen.getByRole("button", { name: /подтвердить покупку/i }),
    );

    expect(await screen.findByText("Покупка засчитана")).toBeInTheDocument();
    expect(previewCall).toHaveBeenCalledWith({
      user_id: "user-1",
      purchase_amount_minor: 46000,
      stamps_to_add: 2,
      location_id: staffLocations[0]!.id,
    });
    expect(confirmCall).toHaveBeenCalledWith({
      user_id: "user-1",
      purchase_amount_minor: 46000,
      stamps_to_add: 2,
      location_id: staffLocations[0]!.id,
    });
    await user.click(screen.getByRole("button", { name: "Новая покупка" }));
    expect(newPurchase).toHaveBeenCalledOnce();
  });

  it("buys a configured menu reward with points after confirmation", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [
        {
          id: "category-1",
          name: "Кофе",
          sort_order: 0,
          visible: true,
        },
      ],
      items: [
        {
          id: "item-1",
          category_id: "category-1",
          name: "Капучино",
          price_minor: 29000,
          points_price: 80,
          available: true,
          visible: true,
        },
      ],
    });
    const purchase = vi
      .spyOn(coffeeApi, "purchaseMenuItemWithPoints")
      .mockResolvedValue({
        operation_id: "operation-2",
        reward_id: "reward-1",
        item_id: "item-1",
        item_name: "Капучино",
        points_spent: 80,
        balance_after: 204,
        qr_payload: "coffee-reward:v1:opaque-token",
        idempotent_replay: false,
      });
    render(
      <MemoryRouter>
        <CartProvider>
          <MenuPage />
        </CartProvider>
      </MemoryRouter>,
    );

    const pointsButton = await screen.findByRole("button", {
      name: "Купить за 80 баллов",
    });
    expect(pointsButton).toHaveClass("menu-card__points-button");
    await user.click(pointsButton);
    const confirmation = screen.getByRole("dialog", {
      name: "Подтвердите покупку",
    });
    expect(confirmation).toHaveClass("purchase-sheet");
    expect(confirmation).toHaveAttribute("aria-modal", "true");
    await user.click(screen.getByRole("button", { name: "Списать баллы" }));

    expect(await screen.findByText("Награда готова")).toBeInTheDocument();
    expect(screen.getByText(/204/)).toBeInTheDocument();
    expect(purchase).toHaveBeenCalledWith("item-1", expect.any(String));
    expect(
      screen.getByRole("dialog", { name: "Капучино" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("centers an active reward QR in a full-width redemption row", async () => {
    vi.spyOn(coffeeApi, "getMyPasses").mockResolvedValue({ items: [] });
    vi.spyOn(coffeeApi, "getMyPassPurchases").mockResolvedValue({ items: [] });
    vi.spyOn(coffeeApi, "getRewards").mockResolvedValue({
      items: [
        {
          id: "reward-1",
          title: "Латте",
          description: "Награда: латте",
          type: "free_product",
          status: "active",
          created_at: "2026-07-21T10:00:00Z",
          qr_payload: "coffee-reward:v1:opaque-token",
        },
      ],
      page: 1,
      page_size: 20,
      total: 1,
    });

    render(
      <MemoryRouter>
        <RewardsPage />
      </MemoryRouter>,
    );

    const redemption = await screen.findByTestId("reward-card-redemption");
    expect(redemption).toHaveClass("reward-card__redemption");
    expect(screen.getByTitle("QR-код награды Латте")).toBeInTheDocument();
  });

  it("keeps manual visits and stamps out of secondary actions", () => {
    render(
      <QuickOperationsPanel
        client={client}
        location={staffLocations[0]!}
        onCompleted={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Посещение" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Штамп" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Списать" })).toBeInTheDocument();
  });

  it("uses the preview location again when confirming a redemption", async () => {
    const user = userEvent.setup();
    const preview: RedemptionPreview = {
      user_id: client.user_id,
      customer_name: client.display_name,
      purchase_amount_minor: 10_000,
      requested_points: 40,
      discount_minor: 4_000,
      maximum_points_for_purchase: 50,
      balance_before: 284,
      balance_after: 244,
      location_id: staffLocations[1]!.id,
    };
    const previewCall = vi
      .spyOn(coffeeApi, "previewRedemption")
      .mockResolvedValue(preview);
    const confirmCall = vi
      .spyOn(coffeeApi, "confirmRedemption")
      .mockResolvedValue({
        operation_id: "redemption-1",
        status: "completed",
        delta_points: -40,
        balance_after: 244,
        created_at: "2026-08-24T10:00:00Z",
      });

    render(
      <QuickOperationsPanel
        client={client}
        location={staffLocations[1]!}
        onCompleted={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Списать" }));
    await user.type(screen.getByLabelText("Сумма покупки, ₽"), "100");
    await user.type(screen.getByLabelText("Сколько баллов списать"), "40");
    await user.click(screen.getByRole("button", { name: "Рассчитать" }));
    expect(
      await screen.findByLabelText("Предпросмотр списания"),
    ).toHaveTextContent(staffLocations[1]!.name);
    await user.click(
      screen.getByRole("button", { name: "Подтвердить списание" }),
    );

    const expectedPayload = {
      user_id: client.user_id,
      purchase_amount_minor: 10_000,
      requested_points: 40,
      location_id: staffLocations[1]!.id,
    };
    expect(previewCall).toHaveBeenCalledWith(expectedPayload);
    expect(confirmCall).toHaveBeenCalledWith(expectedPayload);
  });

  it("keeps simple reward redemption independent from location payloads", async () => {
    const user = userEvent.setup();
    const redeem = vi.spyOn(coffeeApi, "redeemReward").mockResolvedValue({
      operation_id: "reward-redemption-1",
      status: "completed",
      delta_points: 0,
      balance_after: client.balance_points,
      created_at: "2026-08-24T10:00:00Z",
    });
    render(
      <QuickOperationsPanel
        client={{
          ...client,
          available_rewards: [
            {
              id: "reward-1",
              title: "Бесплатный кофе",
              description: "Любой напиток 300 мл",
              type: "free_product",
              status: "active",
              created_at: "2026-08-24T09:00:00Z",
            },
          ],
        }}
        location={staffLocations[0]!}
        onCompleted={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Погасить награду" }));
    await user.click(screen.getByLabelText(/Бесплатный кофе/));
    await user.click(
      screen.getByRole("button", { name: "Подтвердить погашение" }),
    );

    expect(redeem).toHaveBeenCalledWith("reward-1");
  });

  it("shows a safe retryable error state", async () => {
    vi.spyOn(coffeeApi, "getHome").mockRejectedValue(
      new Error("Сервис временно недоступен"),
    );
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Что-то пошло не так");
    expect(alert).toHaveTextContent("Сервис временно недоступен");
    expect(
      screen.getByRole("button", { name: /попробовать снова/i }),
    ).toBeInTheDocument();
  });

  it("submits the backend feedback category for food and drinks", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getMore").mockResolvedValue({
      contacts: {
        coffee_shop_name: "Кофейня",
        description: "Описание",
        privacy_policy: "Политика",
        locations: [],
      },
      staff: [],
      promotions: [],
    });
    const submit = vi.spyOn(coffeeApi, "submitFeedback").mockResolvedValue({
      id: "feedback-1",
      status: "new",
    });

    render(
      <MemoryRouter>
        <MorePage />
      </MemoryRouter>,
    );

    await screen.findByText("Кофейня");
    await user.selectOptions(
      screen.getByLabelText("Категория"),
      "food_and_drinks",
    );
    await user.type(screen.getByLabelText("Сообщение"), "Очень вкусный кофе");
    await user.click(screen.getByRole("button", { name: "Отправить" }));

    expect(submit).toHaveBeenCalledWith({
      rating: 5,
      category: "food_and_drinks",
      message: "Очень вкусный кофе",
      may_contact: true,
    });
  });

  it("hides disabled loyalty progress and uses time-aware greetings", async () => {
    vi.spyOn(coffeeApi, "getHome").mockResolvedValue({
      card: { ...card, visits_enabled: false, stamps_enabled: false },
      active_rewards: [],
      promotions: [],
    });
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("284")).toBeInTheDocument();
    expect(screen.queryByText("До следующей награды")).not.toBeInTheDocument();
    expect(getTimeGreeting(new Date(2026, 0, 1, 4))).toBe("Доброй ночи");
    expect(getTimeGreeting(new Date(2026, 0, 1, 5))).toBe("Доброе утро");
    expect(getTimeGreeting(new Date(2026, 0, 1, 12))).toBe("Добрый день");
    expect(getTimeGreeting(new Date(2026, 0, 1, 18))).toBe("Добрый вечер");
    expect(getTimeGreeting(new Date(2026, 0, 1, 23))).toBe("Доброй ночи");
  });

  it("shows purchasable subscriptions together with home promotions", async () => {
    vi.spyOn(coffeeApi, "getHome").mockResolvedValue({
      card,
      active_rewards: [],
      promotions: [],
      subscription_products: [
        {
          id: "pass-template-1",
          name: "Кофейный месяц",
          description: "Кофе каждое утро",
          image_media_id: null,
          image_url: "/subscription.webp",
          total_uses: 30,
          validity_days: 30,
          price_minor: 150000,
          purchase_enabled: true,
          venue_ids: [],
          category_ids: [],
          item_ids: [],
          is_active: true,
          created_at: "2026-09-03T10:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Кофейный месяц")).toBeVisible();
    expect(screen.getByText("Абонемент")).toBeVisible();
    expect(screen.getByRole("link", { name: "Подробнее" })).toHaveAttribute(
      "href",
      "/menu#subscriptions",
    );
  });

  it("restores and persists the customer venue selection on home", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(SELECTED_VENUE_STORAGE_KEY, foodVenue.id);
    vi.spyOn(coffeeApi, "getHome").mockResolvedValue({
      card,
      active_rewards: [],
      promotions: [],
    });
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: venues,
      page: 1,
      page_size: venues.length,
      total: venues.length,
    });

    try {
      render(
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>,
      );

      const selector = await screen.findByLabelText("Заведение");
      expect(selector).toHaveValue(foodVenue.id);
      await user.selectOptions(selector, grillVenue.id);

      expect(selector).toHaveValue(grillVenue.id);
      expect(window.localStorage.getItem(SELECTED_VENUE_STORAGE_KEY)).toBe(
        grillVenue.id,
      );
    } finally {
      window.localStorage.removeItem(SELECTED_VENUE_STORAGE_KEY);
    }
  });

  it("falls back when the selected venue disappears from the public list", async () => {
    window.localStorage.setItem(SELECTED_VENUE_STORAGE_KEY, foodVenue.id);

    try {
      const view = render(<VenueSelectionHarness items={venues} />);
      expect(screen.getByLabelText("Заведение")).toHaveValue(foodVenue.id);

      view.rerender(
        <VenueSelectionHarness items={[grillVenue, coffeeVenue]} />,
      );

      await waitFor(() => {
        expect(screen.getByLabelText("Заведение")).toHaveValue(grillVenue.id);
        expect(window.localStorage.getItem(SELECTED_VENUE_STORAGE_KEY)).toBe(
          grillVenue.id,
        );
      });
    } finally {
      window.localStorage.removeItem(SELECTED_VENUE_STORAGE_KEY);
    }
  });

  it("shows an earned visit or stamp reward as a scannable QR on home", async () => {
    vi.spyOn(coffeeApi, "getHome").mockResolvedValue({
      card,
      active_rewards: [
        {
          id: "reward-stamps-1",
          title: "Капучино за 9 штампов",
          description: "Бесплатный капучино",
          type: "free_product",
          status: "active",
          created_at: "2026-08-02T10:00:00Z",
          qr_payload: "coffee-reward:v1:earned-opaque-token",
        },
      ],
      promotions: [],
    });

    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId("home-reward-qr")).toBeInTheDocument();
    expect(
      screen.getByTitle("QR-код награды Капучино за 9 штампов"),
    ).toBeInTheDocument();
    expect(screen.getByText("Покажите этот QR-код бариста.")).toBeVisible();
  });

  it("shows the Telegram avatar in the Mini App header", () => {
    const { container } = render(
      <AuthContext.Provider
        value={{
          actor: {
            id: "customer-1",
            telegram_id: "10001",
            display_name: "Анна",
            photo_url: "https://telegram.example/avatar.jpg",
            role: "customer",
            available_roles: ["customer"],
            permissions: [],
          },
          activeRole: "customer",
          availableRoles: ["customer"],
          loading: false,
          error: null,
          isDemo: false,
          setActiveRole: vi.fn(),
          retry: vi.fn(),
          loginWithTelegram: vi.fn().mockResolvedValue(undefined),
          loginWithPassword: vi.fn().mockResolvedValue(undefined),
          logout: vi.fn().mockResolvedValue(undefined),
        }}
      >
        <MemoryRouter>
          <Routes>
            <Route element={<AuthGate />}>
              <Route index element={<div>Главная</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthContext.Provider>,
    );

    expect(container.querySelector(".topbar .avatar")).toHaveAttribute(
      "src",
      "https://telegram.example/avatar.jpg",
    );
    expect(screen.getByRole("link", { name: "Карта" })).toHaveAttribute(
      "href",
      "/card",
    );
  });

  it("requires a reason, previews, and confirms an admin adjustment", async () => {
    const user = userEvent.setup();
    const adminUser: AdminUser = {
      id: "user-1",
      telegram_id: "10001",
      display_name: "Анна",
      short_code: "BEAN2026",
      balance_points: 284,
      status: "active",
      visit_streak: 3,
      stamps: 6,
      active_rewards: 1,
      created_at: "2026-07-01T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminUser").mockResolvedValue(adminUser);
    vi.spyOn(coffeeApi, "getAdminLoyaltyV2").mockResolvedValue(
      adminLoyaltySettings("shared"),
    );
    const confirm = vi.spyOn(coffeeApi, "confirmAdjustment").mockResolvedValue({
      operation_id: "adjustment-1",
      status: "completed",
      delta_points: 50,
      balance_after: 334,
      created_at: "2026-07-21T10:00:00Z",
    });
    render(
      <MemoryRouter initialEntries={["/admin/users/user-1/adjust"]}>
        <Routes>
          <Route
            path="/admin/users/:userId/adjust"
            element={<AdminAdjustmentPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Анна")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начислить" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const amountInput = screen.getByLabelText("Количество баллов");
    expect(amountInput).toHaveAttribute("type", "number");
    expect(amountInput).toHaveAttribute("inputmode", "numeric");
    expect(amountInput).toHaveAttribute("min", "1");
    await user.type(amountInput, "50");
    await user.selectOptions(
      await screen.findByLabelText("Заведение корректировки"),
      coffeeVenue.id,
    );
    await user.type(screen.getByLabelText("Причина"), "Компенсация за ошибку");
    await user.click(screen.getByRole("button", { name: "Показать итог" }));
    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent("334");
    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent(`источник «${coffeeVenue.name}»`);
    await user.click(
      screen.getByRole("button", { name: /подтвердить корректировку/i }),
    );

    expect(
      await screen.findByText("Баланс скорректирован"),
    ).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledWith({
      user_id: "user-1",
      delta_points: 50,
      reason: "Компенсация за ошибку",
      venue_id: coffeeVenue.id,
    });
  });

  it("forms a negative adjustment after an explicit debit choice", async () => {
    const user = userEvent.setup();
    const adminUser: AdminUser = {
      id: "user-1",
      telegram_id: "10001",
      display_name: "Анна",
      short_code: "BEAN2026",
      balance_points: 284,
      status: "active",
      visit_streak: 3,
      stamps: 6,
      active_rewards: 1,
      created_at: "2026-07-01T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminUser").mockResolvedValue(adminUser);
    vi.spyOn(coffeeApi, "getAdminLoyaltyV2").mockResolvedValue(
      adminLoyaltySettings("shared"),
    );
    const confirm = vi.spyOn(coffeeApi, "confirmAdjustment").mockResolvedValue({
      operation_id: "adjustment-2",
      status: "completed",
      delta_points: -20,
      balance_after: 264,
      created_at: "2026-07-21T10:00:00Z",
    });
    render(
      <MemoryRouter initialEntries={["/admin/users/user-1/adjust"]}>
        <Routes>
          <Route
            path="/admin/users/:userId/adjust"
            element={<AdminAdjustmentPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Анна")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Списать" }));
    expect(screen.getByRole("button", { name: "Списать" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.type(screen.getByLabelText("Количество баллов"), "20");
    await user.type(screen.getByLabelText("Причина"), "Исправление начисления");
    await user.click(screen.getByRole("button", { name: "Показать итог" }));

    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent("-20");
    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent("264");
    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent("Общий кошелёк (master wallet)");
    await user.click(
      screen.getByRole("button", { name: /подтвердить корректировку/i }),
    );

    expect(
      await screen.findByText("Баланс скорректирован"),
    ).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledWith({
      user_id: "user-1",
      delta_points: -20,
      reason: "Исправление начисления",
      venue_id: null,
    });
  });

  it("requires and sends a venue for a separate-wallet adjustment", async () => {
    const user = userEvent.setup();
    const adminUser: AdminUser = {
      id: "user-1",
      telegram_id: null,
      display_name: "Гость",
      short_code: "PHONE123",
      balance_points: 120,
      status: "active",
      visit_streak: 0,
      stamps: 0,
      active_rewards: 0,
      created_at: "2026-08-24T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminUser").mockResolvedValue(adminUser);
    vi.spyOn(coffeeApi, "getAdminLoyaltyV2").mockResolvedValue(
      adminLoyaltySettings("separate"),
    );
    const confirm = vi.spyOn(coffeeApi, "confirmAdjustment").mockResolvedValue({
      operation_id: "adjustment-venue",
      status: "completed",
      delta_points: 15,
      balance_after: 135,
      created_at: "2026-08-24T10:10:00Z",
    });

    render(
      <MemoryRouter initialEntries={["/admin/users/user-1/adjust"]}>
        <Routes>
          <Route
            path="/admin/users/:userId/adjust"
            element={<AdminAdjustmentPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Гость")).toBeInTheDocument();
    const venue = await screen.findByLabelText("Заведение корректировки");
    expect(venue).toBeRequired();
    await user.selectOptions(venue, foodVenue.id);
    await user.type(screen.getByLabelText("Количество баллов"), "15");
    await user.type(screen.getByLabelText("Причина"), "Welcome-компенсация");
    await user.click(screen.getByRole("button", { name: "Показать итог" }));

    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent(`Кошелёк «${foodVenue.name}»`);
    await user.click(
      screen.getByRole("button", { name: "Подтвердить корректировку" }),
    );
    expect(confirm).toHaveBeenCalledWith({
      user_id: adminUser.id,
      delta_points: 15,
      reason: "Welcome-компенсация",
      venue_id: foodVenue.id,
    });
  });

  it("previews a merge and preserves its idempotency key across retries", async () => {
    const user = userEvent.setup();
    const sourceUserId = "11111111-1111-4111-8111-111111111111";
    const canonicalUserId = "22222222-2222-4222-8222-222222222222";
    const preview: CustomerMergePreview = {
      source: {
        user_id: sourceUserId,
        display_name: "Телефонный дубль",
        status: "active",
        identity_providers: ["phone"],
        points_balance: 70,
        stamp_count: 3,
        visit_streak: 2,
        last_visit_business_date: "2026-08-23",
        staff_role: null,
        birthday_set: true,
      },
      canonical: {
        user_id: canonicalUserId,
        display_name: "Основной клиент",
        status: "active",
        identity_providers: ["telegram"],
        points_balance: 120,
        stamp_count: 4,
        visit_streak: 5,
        last_visit_business_date: "2026-08-24",
        staff_role: null,
        birthday_set: true,
      },
      preview_hash: "a".repeat(64),
      points_to_transfer: 70,
      stamps_to_transfer: 3,
      visit_snapshot_from_user_id: canonicalUserId,
      identities_to_move: 1,
      rewards_to_move: 2,
      sessions_to_revoke: 3,
      cards_to_revoke: 2,
      feedback_to_move: 1,
      source_staff_rebound: false,
      birthday_conflict: true,
      birthday_resolution_required: true,
    };
    const result: CustomerMergeResult = {
      merge_id: "33333333-3333-4333-8333-333333333333",
      source_user_id: sourceUserId,
      canonical_user_id: canonicalUserId,
      preview_hash: preview.preview_hash,
      completed_at: "2026-08-24T12:00:00Z",
      points_transferred: 70,
      canonical_points_after: 190,
      stamps_transferred: 3,
      canonical_stamps_after: 7,
      visit_snapshot_from_user_id: canonicalUserId,
      identities_moved: 1,
      rewards_moved: 2,
      sessions_revoked: 3,
      cards_revoked: 2,
      feedback_moved: 1,
      birthday_resolution: "keep_canonical",
      source_staff_rebound: false,
      idempotent_replay: false,
    };
    const requestPreview = vi
      .spyOn(coffeeApi, "previewCustomerMerge")
      .mockResolvedValue(preview);
    const confirm = vi
      .spyOn(coffeeApi, "confirmCustomerMerge")
      .mockRejectedValueOnce(new Error("Ответ сервера потерян"))
      .mockRejectedValueOnce(new Error("Ответ сервера потерян"))
      .mockResolvedValue(result);

    render(
      <MemoryRouter>
        <AdminCustomerMergePage />
      </MemoryRouter>,
    );

    await user.type(
      screen.getByLabelText("UUID исходного профиля"),
      sourceUserId,
    );
    await user.type(
      screen.getByLabelText("UUID основного профиля"),
      canonicalUserId,
    );
    await user.click(
      screen.getByRole("button", { name: "Показать последствия" }),
    );

    const previewRegion = await screen.findByLabelText(
      "Предпросмотр объединения",
    );
    expect(requestPreview).toHaveBeenCalledWith({
      source_user_id: sourceUserId,
      canonical_user_id: canonicalUserId,
    });
    expect(previewRegion).toHaveTextContent(
      "Исходный профиль станет недоступен",
    );
    expect(previewRegion).toHaveTextContent("карт к отзыву");
    expect(previewRegion).toHaveTextContent("сеансов к отзыву");
    expect(previewRegion).toHaveTextContent("карты будут отозваны (2)");
    expect(previewRegion).toHaveTextContent("сеансы завершены (3)");
    expect(previewRegion).toHaveTextContent("разные дни рождения");

    await user.selectOptions(
      screen.getByLabelText("Дата рождения"),
      "keep_canonical",
    );

    await user.type(
      screen.getByLabelText("Причина объединения"),
      "Подтверждённый дубликат",
    );
    await user.click(screen.getByRole("checkbox", { name: /я понимаю/i }));
    const confirmButton = screen.getByRole("button", {
      name: "Объединить профили",
    });
    await user.click(confirmButton);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ответ сервера потерян",
    );

    await user.click(confirmButton);
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
    const firstKey = confirm.mock.calls[0]?.[1];
    const retryKey = confirm.mock.calls[1]?.[1];
    expect(confirm.mock.calls[0]?.[0]).toEqual({
      source_user_id: sourceUserId,
      canonical_user_id: canonicalUserId,
      preview_hash: preview.preview_hash,
      reason: "Подтверждённый дубликат",
      confirm: true,
      birthday_resolution: "keep_canonical",
    });
    expect(confirm.mock.calls[1]?.[0]).toEqual(confirm.mock.calls[0]?.[0]);
    expect(firstKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(retryKey).toBe(firstKey);

    await user.clear(screen.getByLabelText("Причина объединения"));
    await user.type(
      screen.getByLabelText("Причина объединения"),
      "Клиент подтвердил дубликат",
    );
    await user.click(screen.getByRole("checkbox", { name: /я понимаю/i }));
    await user.click(confirmButton);

    expect(await screen.findByText("Профили объединены")).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(3);
    expect(confirm.mock.calls[2]?.[0]).toEqual({
      source_user_id: sourceUserId,
      canonical_user_id: canonicalUserId,
      preview_hash: preview.preview_hash,
      reason: "Клиент подтвердил дубликат",
      confirm: true,
      birthday_resolution: "keep_canonical",
    });
    expect(confirm.mock.calls[2]?.[1]).not.toBe(firstKey);
  });

  it("shows only list-safe client fields before opening a client", async () => {
    const clientItem: AdminUserListItem = {
      id: "user-1",
      telegram_id: "10001",
      display_name: "Анна",
      username: "anna",
      status: "active",
      created_at: "2026-07-01T10:00:00Z",
      last_seen_at: "2026-07-21T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminUsers").mockResolvedValue({
      items: [clientItem],
      page: 1,
      page_size: 50,
      total: 1,
    });

    render(
      <MemoryRouter>
        <AdminUsersPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Анна")).toBeInTheDocument();
    expect(screen.getByText("@anna")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Открыть клиента" }),
    ).toHaveAttribute("href", "/admin/users/user-1/adjust");
    expect(screen.queryByText(/баллов/i)).not.toBeInTheDocument();
  });

  it("renders a phone-only customer without a null Telegram label", async () => {
    const clientItem: AdminUserListItem = {
      id: "phone-user",
      telegram_id: null,
      display_name: "Мария",
      username: null,
      status: "active",
      created_at: "2026-08-24T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminUsers").mockResolvedValue({
      items: [clientItem],
      page: 1,
      page_size: 50,
      total: 1,
    });

    render(
      <MemoryRouter>
        <AdminUsersPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Мария")).toBeInTheDocument();
    expect(screen.getByText("Без Telegram")).toBeInTheDocument();
    expect(screen.queryByText("Telegram null")).not.toBeInTheDocument();
  });

  it("lets the owner process a customer review", async () => {
    const user = userEvent.setup();
    const feedback: AdminFeedback = {
      id: "feedback-1",
      user_id: "user-1",
      user_display_name: "Анна",
      rating: 2,
      category: "service",
      message: "Долго ждала напиток",
      may_contact: true,
      status: "new",
      created_at: "2026-07-21T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminFeedback").mockResolvedValue({
      items: [feedback],
      page: 1,
      page_size: 50,
      total: 1,
    });
    const update = vi
      .spyOn(coffeeApi, "updateAdminFeedback")
      .mockResolvedValue({
        ...feedback,
        status: "in_progress",
        internal_note: "Связаться завтра",
      });

    render(
      <MemoryRouter>
        <AdminFeedbackPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Долго ждала напиток")).toBeInTheDocument();
    await user.selectOptions(
      screen.getAllByLabelText("Статус")[1]!,
      "in_progress",
    );
    await user.type(
      screen.getByLabelText("Внутренняя заметка"),
      "Связаться завтра",
    );
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(update).toHaveBeenCalledWith("feedback-1", {
      status: "in_progress",
      internal_note: "Связаться завтра",
      assigned_to_staff_id: null,
    });
  });

  it("keeps hidden reviews in an archive and deletes only from there", async () => {
    const user = userEvent.setup();
    const archived: AdminFeedback = {
      id: "feedback-archived",
      user_id: "user-1",
      user_display_name: "Анна",
      rating: 1,
      category: "service",
      message: "Архивный отзыв",
      may_contact: false,
      status: "archived",
      created_at: "2026-07-21T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminFeedback").mockImplementation(
      async (status) => ({
        items: status === "archived" ? [archived] : [],
        page: 1,
        page_size: 50,
        total: status === "archived" ? 1 : 0,
      }),
    );
    const remove = vi
      .spyOn(coffeeApi, "deleteAdminFeedback")
      .mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter>
        <AdminFeedbackPage />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "Архив" }));
    expect(await screen.findByText("Архивный отзыв")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Удалить навсегда" }));

    expect(remove).toHaveBeenCalledWith("feedback-archived");
  });

  it("keeps courier settings available and supports disable and delete", async () => {
    const user = userEvent.setup();
    const member: AdminStaffMember = {
      id: "staff-1",
      user_id: "user-1",
      telegram_id: null,
      display_name: "Анна",
      position: "Бариста",
      role: "courier",
      is_active: true,
      can_edit_tip_profile: true,
      permissions: [],
      created_at: "2026-07-01T10:00:00Z",
      updated_at: "2026-07-21T10:00:00Z",
    };
    vi.spyOn(coffeeApi, "getAdminStaff").mockResolvedValue({
      items: [member],
      page: 1,
      page_size: 100,
      total: 1,
    });
    vi.spyOn(coffeeApi, "getAdminUsers").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
    });
    const update = vi
      .spyOn(coffeeApi, "updateAdminStaff")
      .mockResolvedValue({ ...member, is_active: false });
    const remove = vi.spyOn(coffeeApi, "deleteAdminStaff").mockResolvedValue();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <AuthContext.Provider
        value={{
          actor: {
            id: "owner-1",
            telegram_id: "1",
            display_name: "Владелец",
            role: "owner",
            available_roles: ["customer", "owner"],
            permissions: [],
          },
          activeRole: "owner",
          availableRoles: ["customer", "staff", "owner"],
          loading: false,
          error: null,
          isDemo: false,
          setActiveRole: vi.fn(),
          retry: vi.fn(),
          loginWithTelegram: vi.fn().mockResolvedValue(undefined),
          loginWithPassword: vi.fn().mockResolvedValue(undefined),
          logout: vi.fn().mockResolvedValue(undefined),
        }}
      >
        <MemoryRouter>
          <AdminStaffPage />
        </MemoryRouter>
      </AuthContext.Provider>,
    );

    expect(await screen.findByText("Анна")).toBeInTheDocument();
    expect(screen.getByText("Без Telegram")).toBeInTheDocument();
    expect(screen.queryByText("Telegram null")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Сохранить" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Завершить сеансы")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Настройки" }));
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Отключить" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Удалить" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Отключить" }));

    expect(update).toHaveBeenCalledWith("staff-1", { is_active: false });
    await user.click(screen.getByRole("button", { name: "Удалить" }));
    expect(remove).toHaveBeenCalledWith("staff-1");
  });

  it("creates a menu item from the owner content editor", async () => {
    const user = userEvent.setup();
    const category: MenuCategory = {
      id: "category-1",
      name: "Кофе",
      description: "Классика",
      sort_order: 1,
      visible: true,
    };
    vi.spyOn(coffeeApi, "getAdminMenu").mockResolvedValue({
      categories: [category],
      items: [
        {
          id: "item-with-photo",
          category_id: category.id,
          name: "Латте",
          image_url: "/api/v1/media/photo-1",
          price_minor: 31000,
          labels: [],
          available: true,
          visible: true,
          sort_order: 0,
        },
      ],
    });
    const save = vi.spyOn(coffeeApi, "saveMenuItem").mockResolvedValue({
      id: "item-1",
      category_id: category.id,
      name: "Капучино",
      price_minor: 29000,
      labels: [],
      available: true,
      visible: true,
      sort_order: 0,
    });

    render(
      <MemoryRouter>
        <AdminMenuPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Кофе")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Фото Латте" })).toHaveAttribute(
      "src",
      "/api/v1/media/photo-1",
    );
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));
    await user.type(screen.getByLabelText("Название позиции"), "Капучино");
    await user.type(screen.getByLabelText("Цена, ₽"), "290");
    await user.click(screen.getByRole("button", { name: "Сохранить позицию" }));

    expect(save).toHaveBeenCalledWith(null, {
      category_id: "category-1",
      name: "Капучино",
      description: null,
      image_media_id: null,
      price_minor: 29000,
      old_price_minor: null,
      points_price: null,
      composition: null,
      volume: null,
      labels: [],
      available: true,
      visible: true,
      sort_order: 0,
    });
  });

  it("edits promotions as static cards without a manual link", async () => {
    const user = userEvent.setup();
    const promotion = {
      id: "promotion-1",
      title: "Летний напиток",
      text: "Попробуйте новинку",
      button_label: "Старая кнопка",
      button_url: "https://example.com/old",
      image_url: "/api/v1/media/promotion-cover",
      status: "draft" as const,
    };
    vi.spyOn(coffeeApi, "getAdminPromotions").mockResolvedValue({
      items: [promotion],
      page: 1,
      page_size: 50,
      total: 1,
    });
    const save = vi
      .spyOn(coffeeApi, "savePromotion")
      .mockResolvedValue(promotion);

    render(
      <MemoryRouter>
        <AdminPromotionsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Летний напиток")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Изменить" }));
    expect(
      screen.getByRole("img", { name: "Предпросмотр обложки акции" }),
    ).toHaveClass("promotion-cover-preview");
    expect(screen.queryByLabelText("Ссылка акции")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Надпись на кнопке"),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Сохранить черновик" }),
    );

    expect(save).toHaveBeenCalledWith(promotion, {
      title: "Летний напиток",
      text: "Попробуйте новинку",
      image_media_id: null,
      starts_at: null,
      ends_at: null,
    });
  });

  it("shows the promotion archive and permanently deletes with confirmation", async () => {
    const user = userEvent.setup();
    const archivedPromotion = {
      id: "promotion-archived",
      title: "Прошлая акция",
      text: "Уже завершилась",
      status: "archived" as const,
    };
    const getPromotions = vi
      .spyOn(coffeeApi, "getAdminPromotions")
      .mockImplementation(async (status) => ({
        items: status === "archived" ? [archivedPromotion] : [],
        page: 1,
        page_size: 50,
        total: status === "archived" ? 1 : 0,
      }));
    const remove = vi
      .spyOn(coffeeApi, "deletePromotion")
      .mockResolvedValue(undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter>
        <AdminPromotionsPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Архив" }));
    expect(await screen.findByText("Прошлая акция")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Удалить навсегда" }));

    expect(remove).toHaveBeenCalledWith(archivedPromotion);
    expect(getPromotions).toHaveBeenCalledWith("archived");
  });

  it("moves promotions into the archive and restores them as drafts", async () => {
    const user = userEvent.setup();
    const currentPromotion = {
      id: "promotion-current",
      title: "Текущая акция",
      text: "Ещё действует",
      status: "published" as const,
    };
    const archivedPromotion = {
      ...currentPromotion,
      status: "archived" as const,
    };
    const archive = vi
      .spyOn(coffeeApi, "archivePromotion")
      .mockResolvedValue(archivedPromotion);
    const restore = vi
      .spyOn(coffeeApi, "restorePromotion")
      .mockResolvedValue({ ...currentPromotion, status: "draft" });
    vi.spyOn(coffeeApi, "getAdminPromotions").mockImplementation(
      async (status) => ({
        items: status === "archived" ? [archivedPromotion] : [currentPromotion],
        page: 1,
        page_size: 50,
        total: 1,
      }),
    );

    render(
      <MemoryRouter>
        <AdminPromotionsPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Текущая акция")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "В архив" }));
    expect(archive).toHaveBeenCalledWith(currentPromotion);

    await user.click(screen.getByRole("button", { name: "Архив" }));
    await user.click(
      await screen.findByRole("button", { name: "Восстановить" }),
    );
    expect(restore).toHaveBeenCalledWith(archivedPromotion);
  });

  it("configures visit and stamp rewards with compact conditional fields", async () => {
    const user = userEvent.setup();
    const settings: LoyaltySettings = {
      points_enabled: true,
      currency_name: "баллы",
      rubles_per_point: 10,
      redemption_rubles_per_point: 1,
      minimum_purchase_minor: 0,
      maximum_purchase_minor: 1_000_000,
      rounding: "floor",
      max_redemption_percent: 50,
      minimum_redemption_points: 1,
      welcome_bonus_points: 0,
      points_validity_days: null,
      daily_accrual_limit_points: null,
      operation_accrual_limit_points: null,
      large_operation_threshold_minor: null,
      large_operation_requires_approval: false,
      visit_enabled: true,
      visit_goal: 5,
      visits_must_be_consecutive: true,
      visit_daily_limit: 1,
      timezone: "Europe/Moscow",
      business_day_boundary: "04:00",
      visit_allowed_misses: 0,
      visit_reset_on_miss: true,
      visit_reward_validity_days: 7,
      visit_restart_cycle: true,
      visit_reward: { kind: "custom", name: "Напиток за серию" },
      stamps_enabled: true,
      stamp_goal: 9,
      stamps_per_purchase: 1,
      stamp_operation_limit: 10,
      stamp_reward_validity_days: 30,
      reset_stamps_after_reward: true,
      stamp_reward: { kind: "menu_item", menu_item_id: "item-1" },
    };
    vi.spyOn(coffeeApi, "getSettings").mockResolvedValue(settings);
    vi.spyOn(coffeeApi, "getAdminMenu").mockResolvedValue({
      categories: [
        {
          id: "category-1",
          name: "Кофе",
          sort_order: 0,
          visible: true,
        },
      ],
      items: [
        {
          id: "item-1",
          category_id: "category-1",
          name: "Капучино",
          price_minor: 29000,
          labels: [],
          available: true,
          visible: true,
          sort_order: 0,
        },
      ],
    });
    const save = vi
      .spyOn(coffeeApi, "saveSettings")
      .mockImplementation(async (value) => value);

    render(
      <MemoryRouter>
        <AdminSettingsPage />
      </MemoryRouter>,
    );

    const rewardSelectors =
      await screen.findAllByLabelText("Что получит клиент");
    await user.selectOptions(rewardSelectors[0]!, "points");
    const points = screen.getByLabelText("Сколько баллов");
    await user.clear(points);
    await user.type(points, "75");
    await user.click(
      screen.getByRole("button", { name: "Сохранить настройки" }),
    );

    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        visit_reward: { kind: "points", points: 75 },
        stamp_reward: { kind: "menu_item", menu_item_id: "item-1" },
      }),
    );
  });

  it("persists the anime visual theme", () => {
    applyTheme("anime");

    expect(document.documentElement.dataset.appTheme).toBe("anime");
    expect(readTheme()).toBe("anime");
    window.localStorage.removeItem("coffie.theme");
  });
});

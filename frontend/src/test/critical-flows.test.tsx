import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import type {
  AdminFeedback,
  AdminStaffMember,
  AdminUserListItem,
  AdminUser,
  CardData,
  LoyaltySettings,
  MenuCategory,
  OperationResult,
  PurchasePreview,
  StaffClient,
} from "../api/types";
import {
  CardPage,
  getTimeGreeting,
  HomePage,
  MenuPage,
  RewardsPage,
} from "../pages/customer";
import {
  AccrualPanel,
  QuickOperationsPanel,
  ScannerPage,
  StaffWorkspaceProvider,
} from "../pages/staff";
import {
  AdminAdjustmentPage,
  AdminFeedbackPage,
  AdminMenuPage,
  AdminPromotionsPage,
  AdminSettingsPage,
  AdminStaffPage,
  AdminUsersPage,
} from "../pages/admin";
import { AuthContext } from "../auth/AuthContext";
import { AuthGate } from "../components/AppShell";
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

describe("critical Mini App flows", () => {
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
    render(<AccrualPanel client={client} onNewPurchase={newPurchase} />);

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
    });
    expect(confirmCall).toHaveBeenCalledWith({
      user_id: "user-1",
      purchase_amount_minor: 46000,
      stamps_to_add: 2,
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
        <MenuPage />
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
    render(<QuickOperationsPanel client={client} onCompleted={vi.fn()} />);

    expect(
      screen.queryByRole("button", { name: "Посещение" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Штамп" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Списать" })).toBeInTheDocument();
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
    await user.type(screen.getByLabelText("Причина"), "Компенсация за ошибку");
    await user.click(screen.getByRole("button", { name: "Показать итог" }));
    expect(
      screen.getByLabelText("Предпросмотр корректировки"),
    ).toHaveTextContent("334");
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
    });
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

  it("shows employee actions only in settings and supports disable and delete", async () => {
    const user = userEvent.setup();
    const member: AdminStaffMember = {
      id: "staff-1",
      user_id: "user-1",
      telegram_id: "10001",
      username: "anna",
      display_name: "Анна",
      position: "Бариста",
      role: "staff",
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
          logout: vi.fn().mockResolvedValue(undefined),
        }}
      >
        <MemoryRouter>
          <AdminStaffPage />
        </MemoryRouter>
      </AuthContext.Provider>,
    );

    expect(await screen.findByText("Анна")).toBeInTheDocument();
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

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
  MenuCategory,
  OperationResult,
  PurchasePreview,
  StaffClient,
} from "../api/types";
import { CardPage, HomePage } from "../pages/customer";
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
  AdminStaffPage,
  AdminUsersPage,
} from "../pages/admin";
import { AuthContext } from "../auth/AuthContext";
import { applyTheme, readTheme } from "../theme";

const card: CardData = {
  user_id: "user-1",
  display_name: "Анна",
  qr_payload: "opaque-card-token",
  short_code: "BEAN2026",
  balance_points: 284,
  currency_name: "бобов",
  visit_streak: 3,
  visit_goal: 5,
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
    render(<AccrualPanel client={client} />);

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
    await user.type(screen.getByLabelText("Изменение баллов"), "50");
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

  it("lets the owner revoke an employee access immediately", async () => {
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
    await user.click(screen.getByRole("button", { name: "Отключить доступ" }));

    expect(update).toHaveBeenCalledWith("staff-1", { is_active: false });
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
      items: [],
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
    await user.click(screen.getByRole("button", { name: "Добавить позицию" }));
    await user.type(screen.getByLabelText("Название позиции"), "Капучино");
    await user.type(screen.getByLabelText("Цена, ₽"), "290");
    await user.click(screen.getByRole("button", { name: "Сохранить позицию" }));

    expect(save).toHaveBeenCalledWith(null, {
      category_id: "category-1",
      name: "Капучино",
      description: null,
      price_minor: 29000,
      old_price_minor: null,
      composition: null,
      volume: null,
      labels: [],
      available: true,
      visible: true,
      sort_order: 0,
    });
  });

  it("persists an explicit visual theme", () => {
    applyTheme("matcha");

    expect(document.documentElement.dataset.appTheme).toBe("matcha");
    expect(readTheme()).toBe("matcha");
    window.localStorage.removeItem("coffie.theme");
  });
});

import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import type {
  AccrualPreview,
  AdminUser,
  CardData,
  OperationResult,
  StaffClient,
} from "../api/types";
import { CardPage, HomePage } from "../pages/customer";
import {
  AccrualPanel,
  ScannerPage,
  StaffWorkspaceProvider,
} from "../pages/staff";
import { AdminAdjustmentPage } from "../pages/admin";

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
  masked_short_code: "••••2026",
  balance_points: 284,
  currency_name: "бобов",
  visit_streak: 3,
  stamps: 6,
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

  it("previews and explicitly confirms an accrual", async () => {
    const user = userEvent.setup();
    const preview: AccrualPreview = {
      user_id: client.user_id,
      customer_name: client.display_name,
      purchase_amount_minor: 46000,
      points_to_accrue: 46,
      balance_before: 284,
      balance_after: 330,
      requires_approval: false,
    };
    const operation: OperationResult = {
      operation_id: "operation-1",
      status: "completed",
      delta_points: 46,
      balance_after: 330,
      created_at: "2026-07-21T10:00:00Z",
    };
    const previewCall = vi
      .spyOn(coffeeApi, "previewAccrual")
      .mockResolvedValue(preview);
    const confirmCall = vi
      .spyOn(coffeeApi, "confirmAccrual")
      .mockResolvedValue(operation);
    render(<AccrualPanel client={client} />);

    await user.type(screen.getByLabelText(/сумма покупки/i), "460");
    await user.click(screen.getByRole("button", { name: "Рассчитать" }));
    expect(
      await screen.findByLabelText("Предпросмотр начисления"),
    ).toHaveTextContent("Новый баланс");
    expect(screen.getByLabelText("Предпросмотр начисления")).toHaveTextContent(
      "330",
    );
    await user.click(
      screen.getByRole("button", { name: /подтвердить начисление/i }),
    );

    expect(await screen.findByText("Баллы начислены")).toBeInTheDocument();
    expect(previewCall).toHaveBeenCalledWith({
      user_id: "user-1",
      purchase_amount_minor: 46000,
    });
    expect(confirmCall).toHaveBeenCalledWith({
      user_id: "user-1",
      purchase_amount_minor: 46000,
    });
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
});

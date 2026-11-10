import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { StaffBenefitEditor } from "../components/StaffBenefitEditor";
import type { StaffBenefits } from "../api/types";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "../auth/AuthContext";
import { CartProvider } from "../components/CartContext";
import { MenuPage } from "../pages/customer";

const benefits: StaffBenefits = {
  staff_id: "staff-1",
  enabled: true,
  monthly_points: 3000,
  all_items: false,
  item_ids: ["coffee-1"],
  balance_points: 2500,
  expires_at: "2026-11-30T21:00:00Z",
};

describe("employee monthly allowance settings", () => {
  it("validates modifiers and reuses the purchase key after a network error", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 0,
      total: 0,
    });
    vi.spyOn(coffeeApi, "getSubscriptionProducts").mockResolvedValue({
      items: [],
    });
    vi.spyOn(coffeeApi, "getStaffBenefits").mockResolvedValue({
      ...benefits,
      all_items: true,
      balance_points: 3000,
    });
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [],
      items: [
        {
          id: "coffee-1",
          category_id: "category-1",
          name: "Капучино",
          price_minor: 20000,
          available: true,
          visible: true,
          modifier_groups: [
            {
              id: "size",
              name: "Объём",
              min_selections: 1,
              max_selections: 1,
              required: true,
              options: [
                {
                  id: "350ml",
                  name: "350 мл",
                  price_delta_minor: 5000,
                  allows_quantity: false,
                  max_quantity: 1,
                },
              ],
            },
          ],
        },
      ],
    });
    const buy = vi
      .spyOn(coffeeApi, "purchaseStaffBenefit")
      .mockRejectedValueOnce(new Error("Повторите запрос"))
      .mockResolvedValue({
        operation_id: "op-1",
        reward_id: "reward-1",
        item_id: "coffee-1",
        item_name: "Капучино",
        points_spent: 250,
        balance_after: 2750,
        qr_payload: "coffee-reward:v1:opaque",
        idempotent_replay: true,
      });
    render(
      <AuthContext.Provider
        value={{
          actor: {
            id: "employee-1",
            telegram_id: "123",
            display_name: "Employee",
            role: "staff",
            available_roles: ["customer", "staff"],
            permissions: [],
          },
          activeRole: "customer",
          availableRoles: ["customer", "staff"],
          loading: false,
          error: null,
          isDemo: false,
          setActiveRole: vi.fn(),
          retry: vi.fn(),
          loginWithTelegram: vi.fn(),
          loginWithPassword: vi.fn(),
          logout: vi.fn(),
        }}
      >
        <MemoryRouter>
          <CartProvider>
            <MenuPage />
          </CartProvider>
        </MemoryRouter>
      </AuthContext.Provider>,
    );
    await user.click(
      await screen.findByRole("button", { name: "За бонусы сотрудника" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Купить за 200 бонусов сотрудника" }),
    );
    expect(buy).not.toHaveBeenCalled();
    await user.selectOptions(screen.getByLabelText("Объём"), "350ml");
    await user.click(
      screen.getByRole("button", { name: "Купить за 250 бонусов сотрудника" }),
    );
    expect(await screen.findByText("Повторите запрос")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Купить за 250 бонусов сотрудника" }),
    );
    expect(await screen.findByText("Награда готова")).toBeInTheDocument();
    expect(buy).toHaveBeenCalledTimes(2);
    expect(buy.mock.calls[0]?.[1]).toEqual([
      { option_id: "350ml", quantity: 1 },
    ]);
    expect(buy.mock.calls[0]?.[2]).toBe(buy.mock.calls[1]?.[2]);
  });
  it("loads on open and enables the complete menu with one button", async () => {
    const user = userEvent.setup();
    const load = vi
      .spyOn(coffeeApi, "getAdminStaffBenefits")
      .mockResolvedValue(benefits);
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [],
      items: [],
    });
    const save = vi
      .spyOn(coffeeApi, "updateAdminStaffBenefits")
      .mockResolvedValue({ ...benefits, all_items: true, item_ids: [] });
    render(<StaffBenefitEditor staffId="staff-1" />);
    expect(load).not.toHaveBeenCalled();
    await user.click(screen.getByText("Бонусы сотрудника"));
    await screen.findByDisplayValue("3000");
    await user.click(screen.getByRole("button", { name: "Все позиции" }));
    await user.click(screen.getByRole("button", { name: "Сохранить бонусы" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith("staff-1", {
        enabled: true,
        monthly_points: 3000,
        all_items: true,
        item_ids: [],
      }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Настройки бонусов сохранены",
    );
  });

  it("shows a failed save without reporting success", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getAdminStaffBenefits").mockResolvedValue(benefits);
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [],
      items: [],
    });
    vi.spyOn(coffeeApi, "updateAdminStaffBenefits").mockRejectedValue(
      new Error("Нет прав"),
    );
    render(<StaffBenefitEditor staffId="staff-1" />);
    await user.click(screen.getByText("Бонусы сотрудника"));
    await screen.findByDisplayValue("3000");
    await user.click(screen.getByRole("button", { name: "Сохранить бонусы" }));
    expect(await screen.findByText("Нет прав")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { CartProvider } from "../components/CartContext";
import { MenuPage } from "../pages/customer";
import { CartPage, StaffOrdersPage } from "../pages/orders";
import type { CustomerOrder } from "../api/types";

describe("order flows", () => {
  beforeEach(() => localStorage.clear());

  it("requires a configured modifier and keeps the item in the cart", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [{ id: "cat", name: "Кофе", visible: true, sort_order: 0 }],
      items: [
        {
          id: "coffee",
          category_id: "cat",
          name: "Капучино",
          price_minor: 30000,
          available: true,
          visible: true,
          modifier_groups: [
            {
              id: "milk",
              name: "Молоко",
              min_selections: 1,
              max_selections: 1,
              required: true,
              options: [
                {
                  id: "oat",
                  name: "Овсяное",
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
    render(
      <MemoryRouter initialEntries={["/menu"]}>
        <CartProvider>
          <Routes>
            <Route path="/menu" element={<MenuPage />} />
            <Route path="/cart" element={<CartPage />} />
          </Routes>
        </CartProvider>
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "В корзину" }));
    await user.click(screen.getByRole("radio", { name: /Овсяное/ }));
    await user.click(screen.getByRole("button", { name: "Добавить" }));
    await user.click(screen.getByRole("link", { name: "Корзина · 1" }));

    expect(
      screen.getByRole("heading", { name: "Корзина" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Овсяное")).toBeInTheDocument();
    expect(screen.getAllByText("350 ₽")).toHaveLength(2);
  });

  it("moves a new staff order to confirmation", async () => {
    const user = userEvent.setup();
    const order = {
      id: "order-1",
      number: 7,
      status: "new",
      fulfillment_mode: "pickup",
      total_minor: 30000,
      created_at: "2026-08-27T10:00:00Z",
      suborders: [],
    } as unknown as CustomerOrder;
    vi.spyOn(coffeeApi, "getStaffOrders")
      .mockResolvedValueOnce({ items: [order] })
      .mockResolvedValueOnce({ items: [{ ...order, status: "confirmed" }] });
    const transition = vi
      .spyOn(coffeeApi, "transitionOrder")
      .mockResolvedValue({ ...order, status: "confirmed" });
    render(
      <MemoryRouter>
        <StaffOrdersPage />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: "Следующий этап: Подтверждён",
      }),
    );

    expect(transition).toHaveBeenCalledWith("order-1", "confirmed");
    expect(await screen.findByText("Подтверждён")).toBeInTheDocument();
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { AdminPricingPage } from "../pages/admin-pricing";

describe("admin menu pricing", () => {
  it("creates a modifier group with a trusted item and option price", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: [
        {
          id: "venue-1",
          slug: "coffee",
          name: "Кофейня",
          description: null,
          phone: null,
          email: null,
          website: null,
          telegram: null,
          logo_url: null,
          sort_order: 0,
        },
      ],
      page: 1,
      page_size: 100,
      total: 1,
    });
    vi.spyOn(coffeeApi, "getAdminMenu").mockResolvedValue({
      categories: [
        {
          id: "category-1",
          venue_id: "venue-1",
          name: "Кофе",
          sort_order: 0,
          visible: true,
        },
      ],
      items: [
        {
          id: "item-1",
          venue_id: "venue-1",
          category_id: "category-1",
          name: "Латте",
          price_minor: 25000,
          available: true,
          visible: true,
        },
      ],
    });
    vi.spyOn(coffeeApi, "getAdminPromotions").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
    });
    vi.spyOn(coffeeApi, "getAdminModifierGroups").mockResolvedValue([]);
    const save = vi
      .spyOn(coffeeApi, "saveAdminModifierGroup")
      .mockResolvedValue({
        id: "group-1",
        venue_id: "venue-1",
        name: "Молоко",
        min_selections: 0,
        max_selections: 1,
        required: false,
        enabled: true,
        sort_order: 0,
        item_ids: ["item-1"],
        options: [],
      });

    render(
      <MemoryRouter>
        <AdminPricingPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Цены и модификаторы" }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Создать модификатор" }),
    );
    await user.type(screen.getByLabelText("Название группы"), "Молоко");
    await user.type(screen.getByLabelText("Название варианта 1"), "Кокосовое");
    await user.clear(screen.getByLabelText("Доплата варианта 1"));
    await user.type(screen.getByLabelText("Доплата варианта 1"), "60");
    await user.click(screen.getByLabelText("Латте"));
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith(
      null,
      expect.objectContaining({
        venue_id: "venue-1",
        name: "Молоко",
        item_ids: ["item-1"],
        options: [
          expect.objectContaining({
            name: "Кокосовое",
            price_delta_minor: 6000,
          }),
        ],
      }),
    );
  });

  it("changes the customer-facing order of modifier options", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: [
        {
          id: "venue-1",
          slug: "coffee",
          name: "Кофейня",
          description: null,
          phone: null,
          email: null,
          website: null,
          telegram: null,
          logo_url: null,
          sort_order: 0,
        },
      ],
      page: 1,
      page_size: 100,
      total: 1,
    });
    vi.spyOn(coffeeApi, "getAdminMenu").mockResolvedValue({
      categories: [],
      items: [],
    });
    vi.spyOn(coffeeApi, "getAdminPromotions").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
    });
    const group = {
      id: "group-1",
      venue_id: "venue-1",
      name: "Молоко",
      description: null,
      min_selections: 0,
      max_selections: 1,
      required: false,
      enabled: true,
      sort_order: 0,
      archived_at: null,
      item_ids: [],
      options: [
        {
          id: "option-1",
          name: "Обычное",
          price_delta_minor: 0,
          allows_quantity: false,
          max_quantity: 1,
          enabled: true,
          sort_order: 0,
        },
        {
          id: "option-2",
          name: "Овсяное",
          price_delta_minor: 5_000,
          allows_quantity: false,
          max_quantity: 1,
          enabled: true,
          sort_order: 1,
        },
      ],
    };
    vi.spyOn(coffeeApi, "getAdminModifierGroups").mockResolvedValue([group]);
    const save = vi
      .spyOn(coffeeApi, "saveAdminModifierGroup")
      .mockResolvedValue(group);

    render(
      <MemoryRouter>
        <AdminPricingPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("button", { name: "Изменить" }));
    await user.click(
      screen.getByRole("button", { name: "Поднять вариант Овсяное" }),
    );
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const payload = save.mock.calls[0]?.[1];
    expect(payload?.options.map((option) => option.name)).toEqual([
      "Овсяное",
      "Обычное",
    ]);
    expect(payload?.options.map((option) => option.sort_order)).toEqual([0, 1]);
  });
});

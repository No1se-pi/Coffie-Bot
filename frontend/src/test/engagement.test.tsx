import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import type { BulkBonusPreview, CustomerPass } from "../api/types";
import {
  AdminBulkBonusPage,
  AdminSubscriptionsPage,
  MySubscriptionsSection,
  StaffPendingPassPurchases,
  StaffPassPanel,
} from "../pages/engagement";

const activePass: CustomerPass = {
  id: "pass-1",
  template_id: "template-1",
  user_id: "customer-1",
  name: "Кофе на выбор",
  description: "Один тестовый кофе",
  image_media_id: null,
  image_url: "/media/subscription-cover.png",
  qr_payload: "coffee-pass:v1:opaque-subscription-token",
  total_uses: 2,
  remaining_uses: 1,
  status: "active",
  issued_at: "2026-08-27T10:00:00Z",
  expires_at: "2026-09-27T10:00:00Z",
  usage_count: 1,
  replay: false,
};

describe("engagement workflows", () => {
  it("opens an active subscription as a scannable QR", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getMyPasses").mockResolvedValue({
      items: [activePass],
    });
    vi.spyOn(coffeeApi, "getMyPassPurchases").mockResolvedValue({ items: [] });

    render(
      <MemoryRouter>
        <MySubscriptionsSection />
      </MemoryRouter>,
    );

    await screen.findByText("Кофе на выбор");
    expect(document.querySelector(".pass-card__image")).toHaveAttribute(
      "src",
      "/media/subscription-cover.png",
    );
    await user.click(await screen.findByRole("button", { name: "Открыть QR" }));
    expect(screen.getByTestId("subscription-qr")).toBeInTheDocument();
    expect(
      screen.getByTitle("QR-код абонемента Кофе на выбор"),
    ).toBeInTheDocument();
  });

  it("lets any staff member confirm a pending subscription purchase", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getPendingPassPurchases")
      .mockResolvedValueOnce({
        items: [
          {
            id: "purchase-1",
            number: 42,
            template_id: "template-1",
            user_id: "customer-1",
            name: "Кофе на выбор",
            price_minor: 149000,
            payment_method: "card_on_receipt",
            status: "pending",
            customer_pass_id: null,
            created_at: "2026-09-03T10:00:00Z",
            paid_at: null,
          },
        ],
      })
      .mockResolvedValueOnce({ items: [] });
    const confirm = vi
      .spyOn(coffeeApi, "confirmPassPurchase")
      .mockResolvedValue({
        id: "purchase-1",
        number: 42,
        template_id: "template-1",
        user_id: "customer-1",
        name: "Кофе на выбор",
        price_minor: 149000,
        payment_method: "card_on_receipt",
        status: "paid",
        customer_pass_id: "pass-1",
        created_at: "2026-09-03T10:00:00Z",
        paid_at: "2026-09-03T10:01:00Z",
      });

    render(
      <MemoryRouter>
        <StaffPendingPassPurchases />
      </MemoryRouter>,
    );
    await user.click(
      await screen.findByRole("button", { name: "Оплата получена" }),
    );
    await waitFor(() => expect(confirm).toHaveBeenCalledWith("purchase-1"));
  });

  it("keeps selected venues, categories and items in a pass template", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getPassTemplates").mockResolvedValue({ items: [] });
    vi.spyOn(coffeeApi, "getPendingPassPurchases").mockResolvedValue({
      items: [],
    });
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: [
        {
          id: "venue-1",
          slug: "coffee-point",
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
      page_size: 50,
      total: 1,
    });
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
          price_minor: 25000,
          available: true,
          visible: true,
        },
      ],
    });
    const create = vi.spyOn(coffeeApi, "createPassTemplate").mockResolvedValue({
      id: "template-1",
      name: "Абонемент",
      description: "Тест",
      image_media_id: null,
      total_uses: 20,
      validity_days: 90,
      price_minor: 0,
      purchase_enabled: true,
      venue_ids: ["venue-1"],
      category_ids: ["category-1"],
      item_ids: ["item-1"],
      is_active: true,
      created_at: "2026-08-27T10:00:00Z",
    });

    render(
      <MemoryRouter>
        <AdminSubscriptionsPage />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText("Название"), "Абонемент");
    await user.type(screen.getByLabelText("Описание"), "Тест");
    await user.clear(screen.getByLabelText("Цена, ₽"));
    await user.type(screen.getByLabelText("Цена, ₽"), "1490");
    await user.selectOptions(
      await screen.findByLabelText("Заведения (пусто — все)"),
      "venue-1",
    );
    await user.selectOptions(
      screen.getByLabelText("Категории (пусто — все)"),
      "category-1",
    );
    await user.selectOptions(
      screen.getByLabelText("Конкретные позиции (пусто — все)"),
      "item-1",
    );
    await user.click(screen.getByRole("button", { name: "Создать абонемент" }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        expect.objectContaining({
          venue_ids: ["venue-1"],
          category_ids: ["category-1"],
          item_ids: ["item-1"],
          price_minor: 149000,
          purchase_enabled: true,
        }),
      ),
    );
  });

  it("lets staff choose a trusted menu item and use one pass entry", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getCustomerPasses")
      .mockResolvedValueOnce({ items: [activePass] })
      .mockResolvedValueOnce({
        items: [{ ...activePass, remaining_uses: 0, status: "exhausted" }],
      });
    vi.spyOn(coffeeApi, "getMenu").mockResolvedValue({
      categories: [],
      items: [
        {
          id: "item-1",
          venue_id: "venue-1",
          category_id: "category-1",
          name: "Капучино",
          price_minor: 25000,
          available: true,
          visible: true,
          modifier_groups: [],
        },
      ],
    });
    const usePass = vi.spyOn(coffeeApi, "usePass").mockResolvedValue({
      id: "usage-1",
      pass_id: "pass-1",
      venue_id: "venue-1",
      item_id: "item-1",
      uses_before: 1,
      uses_after: 0,
      created_at: "2026-08-27T11:00:00Z",
      replay: false,
    });

    render(
      <MemoryRouter>
        <StaffPassPanel userId="customer-1" venueId="venue-1" />
      </MemoryRouter>,
    );
    await user.selectOptions(await screen.findByLabelText("Товар"), "item-1");
    await user.click(
      screen.getByRole("button", { name: "Использовать один раз" }),
    );
    await waitFor(() =>
      expect(usePass).toHaveBeenCalledWith("pass-1", "venue-1", "item-1"),
    );
  });

  it("keeps bulk confirmation behind a server preview", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
    });
    const preview: BulkBonusPreview = {
      customer_ids: ["11111111-1111-1111-1111-111111111111"],
      points_per_user: 30,
      reason: "Компенсация",
      venue_id: null,
      recipient_count: 1,
      total_points: 30,
      preview_hash: "a".repeat(64),
    };
    vi.spyOn(coffeeApi, "previewBulkBonus").mockResolvedValue(preview);
    const confirm = vi.spyOn(coffeeApi, "confirmBulkBonus").mockResolvedValue({
      id: "batch-1",
      recipient_count: 1,
      points_per_user: 30,
      total_points: 30,
      reason: "Компенсация",
      venue_id: null,
      created_at: "2026-08-27T12:00:00Z",
      replay: false,
      items: [],
    });

    render(
      <MemoryRouter>
        <AdminBulkBonusPage />
      </MemoryRouter>,
    );
    await user.type(
      screen.getByLabelText("UUID клиентов"),
      preview.customer_ids[0]!,
    );
    await user.clear(screen.getByLabelText("Баллов каждому"));
    await user.type(screen.getByLabelText("Баллов каждому"), "30");
    await user.type(screen.getByLabelText("Причина"), "Компенсация");
    await user.click(screen.getByRole("button", { name: "Рассчитать" }));
    expect(await screen.findByText(/Получателей:/)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Подтвердить начисление" }),
    );
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({ preview_hash: "a".repeat(64) }),
    );
  });
});

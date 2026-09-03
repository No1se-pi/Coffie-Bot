import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { AdminDeliveryPage } from "../pages/admin-delivery";

describe("delivery settings", () => {
  it("keeps physical locations collapsed until the administrator selects one", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getVenues").mockResolvedValue({
      items: [],
      page: 1,
      page_size: 50,
      total: 0,
    });
    vi.spyOn(coffeeApi, "getAdminDelivery").mockResolvedValue({
      settings: {
        id: "settings-1",
        delivery_enabled: true,
        minimum_order_minor: 0,
        fixed_fee_minor: 0,
        free_delivery_threshold_minor: null,
        scheduling_allowed: false,
        earliest_preparation_minutes: 20,
        operating_hours: {},
        default_pickup_location_id: null,
        consolidation_location_id: null,
      },
      zones: [],
      locations: [
        {
          id: "location-1",
          venue_id: "venue-1",
          slug: "central",
          name: "Центральная точка",
          address: "Москва, Тверская, 1",
          phone: null,
          map_url: null,
          image_media_id: null,
          latitude: null,
          longitude: null,
          timezone: "Europe/Moscow",
          is_active: true,
          pickup_enabled: true,
          consolidation_enabled: false,
          pickup_comment: null,
          preparation_minutes: 20,
        },
      ],
    });

    render(<AdminDeliveryPage />);

    const title = await screen.findByText("Центральная точка", {
      selector: "strong",
    });
    const details = title.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(screen.queryByLabelText("Название точки")).not.toBeInTheDocument();

    await user.click(title);
    expect(details).toHaveAttribute("open");
    expect(await screen.findByLabelText("Название точки")).toBeVisible();
    expect(
      screen.getByText(/курьер забирает здесь готовые заказы/i),
    ).toBeVisible();
  });
});

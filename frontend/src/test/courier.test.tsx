import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import type { CourierOrder } from "../api/types";
import { CourierAvailablePage } from "../pages/courier";

const availableOrder: CourierOrder = {
  id: "delivery-1",
  number: 81,
  status: "waiting_for_courier",
  status_version: 4,
  venue_names: ["Кофейня у парка"],
  delivery_zone_name: "Центр",
  desired_delivery_at: null,
  created_at: "2026-08-27T10:00:00Z",
  customer_name: null,
  contact_phone: null,
  delivery_address: null,
  entrance: null,
  apartment: null,
  floor: null,
  customer_comment: null,
};

describe("courier flow", () => {
  it("shows an anonymized available order and claims it atomically through the API", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getAvailableCourierOrders")
      .mockResolvedValueOnce({ items: [availableOrder] })
      .mockResolvedValueOnce({ items: [] });
    const claim = vi.spyOn(coffeeApi, "claimCourierOrder").mockResolvedValue({
      ...availableOrder,
      status: "courier_assigned",
      customer_name: "Анна",
      contact_phone: "+79990000000",
      delivery_address: "ул. Тестовая, 1",
    });

    render(
      <MemoryRouter>
        <CourierAvailablePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Заказ №81")).toBeInTheDocument();
    expect(screen.queryByText("ул. Тестовая, 1")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Принять заказ" }));

    expect(claim).toHaveBeenCalledWith("delivery-1");
    expect(
      await screen.findByText("Свободных заказов нет"),
    ).toBeInTheDocument();
  });
});

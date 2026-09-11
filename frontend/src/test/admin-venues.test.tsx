import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { AdminVenuesPage } from "../pages/admin-venues";

describe("admin venues", () => {
  it("opens and focuses the editor when change is selected", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getAdminVenues").mockResolvedValue({
      items: [
        {
          id: "venue-1",
          slug: "coffee",
          name: "Кофейня и Точка!",
          description: "Описание",
          phone: null,
          email: null,
          website: null,
          telegram: null,
          logo_media_id: null,
          logo_url: null,
          active: true,
          sort_order: 0,
          archived_at: null,
        },
      ],
      page: 1,
      page_size: 50,
      total: 1,
    });

    render(
      <MemoryRouter>
        <AdminVenuesPage />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: "Изменить заведение Кофейня и Точка!",
      }),
    );

    const name = screen.getByLabelText("Название");
    expect(name).toHaveValue("Кофейня и Точка!");
    await waitFor(() => expect(name).toHaveFocus());
  });
});

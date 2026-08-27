import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import { ReceiptQuickForm } from "../pages/receipts";

describe("manual receipt", () => {
  it("uploads the image before saving the trusted amount", async () => {
    const user = userEvent.setup();
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "receipt.jpg", {
      type: "image/jpeg",
    });
    vi.spyOn(coffeeApi, "uploadReceiptMedia").mockResolvedValue({
      id: "media-1",
      url: "/api/v1/media/media-1",
    });
    const create = vi.spyOn(coffeeApi, "createReceipt").mockResolvedValue({
      id: "receipt-12345678",
    } as never);

    render(
      <MemoryRouter>
        <ReceiptQuickForm userId="customer-1" venueId="venue-1" />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText("Сумма, ₽"), "450.50");
    const fileInput = screen.getByLabelText(
      "Фотография чека",
    ) as HTMLInputElement;
    await user.upload(fileInput, file);
    expect(fileInput.files).toHaveLength(1);
    fireEvent.submit(
      screen.getByRole("button", { name: "Сохранить чек" }).closest("form")!,
    );

    await waitFor(() =>
      expect(coffeeApi.uploadReceiptMedia).toHaveBeenCalledWith(file),
    );
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        user_id: "customer-1",
        venue_id: "venue-1",
        amount_minor: 45050,
        image_media_id: "media-1",
      }),
      expect.any(String),
    );
    expect(await screen.findByText(/Чек receipt-/)).toBeInTheDocument();
  });
});

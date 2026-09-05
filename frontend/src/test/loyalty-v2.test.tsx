import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { coffeeApi } from "../api/client";
import type {
  AdminLoyaltyV2Settings,
  CustomerBirthday,
  CustomerWalletSummary,
  WalletModePreview,
} from "../api/types";
import {
  AdminBirthdayEditor,
  AdminLoyaltyV2Controls,
} from "../pages/admin-loyalty";
import { LoyaltyPage } from "../pages/loyalty";
import { AuthContext } from "../auth/AuthContext";

const wallets: CustomerWalletSummary = {
  mode: "separate",
  total_balance_points: 120,
  point_value_minor: 100,
  max_redemption_percent: 50,
  entries: [
    {
      id: "wallet-active",
      venue: { id: "venue-1", name: "Кофейня", available: true },
      balance_points: 100,
      expiring_points: 30,
      expires_at: "2027-01-15T00:00:00Z",
    },
    {
      id: "wallet-archived",
      venue: { id: "venue-old", name: "Старая точка", available: false },
      balance_points: 20,
      expiring_points: 0,
      expires_at: null,
    },
  ],
};

const emptyBirthday: CustomerBirthday = {
  birthday: null,
  locked: false,
  offer: null,
};

const adminSettings: AdminLoyaltyV2Settings = {
  wallet_mode: "shared",
  point_value_minor: 100,
  max_redemption_percent: 50,
  expiry_months: 6,
  expiry_days_override: null,
  expiry_reminder_days: 14,
  default_bonus_venue_id: "venue-1",
  rounding: "floor",
  venue_rates: [
    {
      venue_id: "venue-1",
      venue_name: "Кофейня",
      available: true,
      loyalty_points_enabled: true,
      accrual_basis_points: 1000,
      rounding_mode: "floor",
    },
    {
      venue_id: "venue-2",
      venue_name: "ФудДворик",
      available: true,
      loyalty_points_enabled: true,
      accrual_basis_points: 700,
      rounding_mode: "half_up",
    },
    {
      venue_id: "venue-3",
      venue_name: "Шашлык Джан",
      available: true,
      loyalty_points_enabled: true,
      accrual_basis_points: 500,
      rounding_mode: "ceiling",
    },
    {
      venue_id: "venue-old",
      venue_name: "Архивное кафе",
      available: false,
      loyalty_points_enabled: true,
      accrual_basis_points: 500,
      rounding_mode: "floor",
    },
  ],
  birthday: {
    enabled: true,
    discount_percent: 10,
    window_days: 1,
    eligible_venue_ids: [],
    stackable: false,
  },
};

describe("Loyalty V2 frontend", () => {
  beforeEach(() => {
    vi.spyOn(coffeeApi, "getMyIdentities").mockResolvedValue({
      items: [
        {
          id: "telegram-identity",
          provider: "telegram",
          subject: "1000000000000",
          verified: true,
          verified_at: "2026-09-05T12:00:00Z",
        },
      ],
    });
  });

  it("shows separate balances, expiry and an unavailable venue without hiding its balance", async () => {
    vi.spyOn(coffeeApi, "getMyWallets").mockResolvedValue(wallets);
    vi.spyOn(coffeeApi, "getMyBirthday").mockResolvedValue(emptyBirthday);

    render(
      <MemoryRouter>
        <LoyaltyPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("120 баллов")).toBeInTheDocument();
    expect(screen.getByText("По заведениям")).toBeInTheDocument();
    expect(screen.getByText("Старая точка")).toBeInTheDocument();
    expect(screen.getByText("Заведение недоступно")).toBeInTheDocument();
    expect(screen.getByText("20 баллов")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Ближайшее сгорание: 30 баллов",
    );
    expect(screen.getByText(/1 балл =/)).toHaveTextContent("1 ₽");
    expect(screen.getByText(/Баллами можно оплатить/)).toHaveTextContent("50%");
    expect(screen.queryByText(/скидка 10%/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Месяц рождения")).toBeInTheDocument();
    expect(document.querySelector('input[type="date"]')).toBeNull();
  });

  it("saves February 29 without a year and renders the locked offer returned by backend", async () => {
    const user = userEvent.setup();
    const locked: CustomerBirthday = {
      birthday: { month: 2, day: 29 },
      locked: true,
      offer: {
        enabled: true,
        discount_percent: 10,
        window_days: 1,
        eligible_venues: [],
        stackable: false,
      },
    };
    vi.spyOn(coffeeApi, "getMyWallets").mockResolvedValue({
      ...wallets,
      mode: "shared",
      entries: [],
    });
    vi.spyOn(coffeeApi, "getMyBirthday")
      .mockResolvedValueOnce(emptyBirthday)
      .mockResolvedValue(locked);
    const save = vi.spyOn(coffeeApi, "setMyBirthday").mockResolvedValue(locked);

    render(
      <MemoryRouter>
        <LoyaltyPage />
      </MemoryRouter>,
    );

    await user.selectOptions(
      await screen.findByLabelText("Месяц рождения"),
      "2",
    );
    expect(screen.getByText("Общий кошелёк")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("День рождения"), "29");
    await user.click(screen.getByRole("button", { name: "Сохранить дату" }));

    expect(save).toHaveBeenCalledWith({ month: 2, day: 29 });
    expect(await screen.findByText("Дата зафиксирована")).toBeInTheDocument();
    expect(screen.getByText("29 февраля")).toBeInTheDocument();
    expect(screen.getByText(/скидка 10%/i)).toBeInTheDocument();
    expect(screen.getByText(/Заведения:/)).toHaveTextContent(
      "все активные заведения",
    );
    expect(screen.getByText(/28 февраля/)).toBeInTheDocument();
  });

  it("requests the Telegram contact and refreshes a merged phone profile", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getMyWallets").mockResolvedValue(wallets);
    vi.spyOn(coffeeApi, "getMyBirthday").mockResolvedValue(emptyBirthday);
    vi.mocked(coffeeApi.getMyIdentities)
      .mockResolvedValueOnce({
        items: [
          {
            id: "telegram-identity",
            provider: "telegram",
            subject: "1000000000000",
            verified: true,
            verified_at: "2026-09-05T12:00:00Z",
          },
        ],
      })
      .mockResolvedValue({
        items: [
          {
            id: "phone-identity",
            provider: "phone",
            subject: "+79261234567",
            verified: true,
            verified_at: "2026-09-05T12:01:00Z",
          },
        ],
      });
    const requestContact = vi.fn((callback?: (shared: boolean) => void) =>
      callback?.(true),
    );
    window.Telegram = { WebApp: { requestContact } };

    render(
      <MemoryRouter>
        <LoyaltyPage />
      </MemoryRouter>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: "Добавить номер из Telegram",
      }),
    );

    expect(requestContact).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText(
        "Телефон подключён. Баланс и история прежнего профиля объединены.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Телефон +79261234567")).toBeInTheDocument();
  });

  it("re-previews unresolved points with an active fallback and keeps the idempotency key on retry", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getAdminLoyaltyV2").mockResolvedValue(adminSettings);
    vi.spyOn(coffeeApi, "saveAdminLoyaltyV2").mockImplementation(
      async (value) => ({
        ...adminSettings,
        ...value,
        venue_rates: adminSettings.venue_rates.map((rate) => ({
          ...rate,
          ...value.venue_rates.find(
            (candidate) => candidate.venue_id === rate.venue_id,
          ),
        })),
      }),
    );
    const basePreview: WalletModePreview = {
      current_mode: "shared",
      target_mode: "separate",
      preview_hash: "a".repeat(64),
      customers_affected: 2,
      wallets_affected: 4,
      total_balance_points: 120,
      transfer_operations: 4,
      fallback_required: true,
      fallback_venue_id: null,
      unresolved_points: 20,
      eligible_fallback_venues: [
        { id: "venue-1", name: "Кофейня", available: true },
        { id: "venue-old", name: "Архив", available: false },
      ],
      warnings: ["Суммарный баланс не изменится"],
    };
    const preview = vi
      .spyOn(coffeeApi, "previewWalletMode")
      .mockResolvedValueOnce(basePreview)
      .mockResolvedValueOnce({
        ...basePreview,
        preview_hash: "b".repeat(64),
        fallback_venue_id: "venue-1",
      });
    const confirm = vi
      .spyOn(coffeeApi, "confirmWalletMode")
      .mockRejectedValueOnce(new Error("Ответ сервера потерян"))
      .mockResolvedValue({
        wallet_mode: "separate",
        wallets_created: 4,
        transfer_operations: 4,
        total_balance_points: 120,
        completed_at: "2026-08-24T12:00:00Z",
        idempotent_replay: true,
      });

    render(<AdminLoyaltyV2Controls />);

    expect(await screen.findByLabelText("Кофейня, %")).toHaveValue(10);
    expect(screen.getByLabelText("ФудДворик, %")).toHaveValue(7);
    expect(screen.getByLabelText("Шашлык Джан, %")).toHaveValue(5);
    await user.click(
      screen.getByRole("button", { name: "Показать предпросмотр" }),
    );
    await user.selectOptions(
      await screen.findByLabelText("Активное fallback-заведение"),
      "venue-1",
    );
    expect(screen.queryByRole("option", { name: "Архив" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Сменить режим" }),
    ).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: "Обновить предпросмотр" }),
    );
    expect(preview).toHaveBeenLastCalledWith({
      target_mode: "separate",
      fallback_venue_id: "venue-1",
    });
    await user.type(
      screen.getByLabelText("Причина смены режима"),
      "Переход на отдельные кошельки",
    );
    await user.click(screen.getByLabelText("Подтверждаю миграцию кошельков"));
    await user.click(screen.getByRole("button", { name: "Сменить режим" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ответ сервера потерян",
    );
    await user.click(screen.getByRole("button", { name: "Сменить режим" }));

    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
    expect(confirm.mock.calls[0]?.[1]).toBe(confirm.mock.calls[1]?.[1]);
    expect(confirm.mock.calls[0]?.[0]).toEqual({
      target_mode: "separate",
      preview_hash: "b".repeat(64),
      fallback_venue_id: "venue-1",
      reason: "Переход на отдельные кошельки",
      confirm: true,
    });
  });

  it("saves per-venue enabled, rate and rounding settings without changing wallet mode", async () => {
    const user = userEvent.setup();
    vi.spyOn(coffeeApi, "getAdminLoyaltyV2").mockResolvedValue(adminSettings);
    const save = vi
      .spyOn(coffeeApi, "saveAdminLoyaltyV2")
      .mockImplementation(async (value) => ({
        ...adminSettings,
        ...value,
        venue_rates: adminSettings.venue_rates.map((rate) => ({
          ...rate,
          ...value.venue_rates.find(
            (candidate) => candidate.venue_id === rate.venue_id,
          ),
        })),
      }));

    render(<AdminLoyaltyV2Controls />);

    const foodRate = await screen.findByLabelText("ФудДворик, %");
    expect(screen.getByText("Все активные заведения")).toBeInTheDocument();
    expect(screen.getByLabelText("Кофейня")).toBeChecked();
    expect(screen.getByLabelText("ФудДворик")).toBeChecked();
    expect(screen.getByText(/Пустой список в API/)).toHaveTextContent(
      "все активные заведения",
    );
    expect(
      screen.getByLabelText(
        "Архивное кафе: начислять баллы · Заведение недоступно",
      ),
    ).toBeDisabled();
    expect(screen.queryByLabelText("Архивное кафе")).toBeNull();
    await user.clear(foodRate);
    await user.type(foodRate, "8.5");
    await user.selectOptions(
      screen.getByLabelText("ФудДворик: округление"),
      "floor",
    );
    await user.click(screen.getByLabelText("Шашлык Джан: начислять баллы"));
    await user.clear(screen.getByLabelText("Override срока в днях"));
    await user.type(screen.getByLabelText("Override срока в днях"), "180");
    await user.clear(screen.getByLabelText("Напомнить о сгорании за, дней"));
    await user.type(
      screen.getByLabelText("Напомнить о сгорании за, дней"),
      "21",
    );
    await user.selectOptions(
      screen.getByLabelText("Заведение для бонусов без origin"),
      "venue-2",
    );
    await user.click(screen.getByLabelText("ФудДворик"));
    await user.click(
      screen.getByRole("button", { name: "Сохранить Loyalty V2" }),
    );

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const payload = save.mock.calls[0]?.[0];
    expect(payload).not.toHaveProperty("wallet_mode");
    expect(payload).toMatchObject({
      expiry_days_override: 180,
      expiry_reminder_days: 21,
      default_bonus_venue_id: "venue-2",
      birthday: { eligible_venue_ids: ["venue-1", "venue-3"] },
    });
    expect(payload?.venue_rates[1]).toMatchObject({
      venue_id: "venue-2",
      loyalty_points_enabled: true,
      accrual_basis_points: 850,
      rounding_mode: "floor",
    });
    expect(payload?.venue_rates[2]).toMatchObject({
      loyalty_points_enabled: false,
      accrual_basis_points: 500,
      rounding_mode: "ceiling",
    });
  });

  it("hides wallet-mode migration from an admin while keeping safe settings visible", async () => {
    vi.spyOn(coffeeApi, "getAdminLoyaltyV2").mockResolvedValue(adminSettings);

    render(
      <AuthContext.Provider
        value={{
          actor: {
            id: "admin-1",
            telegram_id: "100",
            display_name: "Admin",
            role: "admin",
            available_roles: ["customer", "staff", "admin"],
            permissions: [],
          },
          activeRole: "admin",
          availableRoles: ["customer", "staff", "admin"],
          loading: false,
          error: null,
          isDemo: false,
          setActiveRole: vi.fn(),
          retry: vi.fn(),
          loginWithTelegram: vi.fn().mockResolvedValue(undefined),
          loginWithPassword: vi.fn().mockResolvedValue(undefined),
          logout: vi.fn(),
        }}
      >
        <AdminLoyaltyV2Controls />
      </AuthContext.Provider>,
    );

    expect(await screen.findByText("Общие правила")).toBeInTheDocument();
    expect(screen.queryByText("Смена режима кошельков")).toBeNull();
  });

  it("lets an admin change only birthday month/day with an audited reason", async () => {
    const user = userEvent.setup();
    const change = vi
      .spyOn(coffeeApi, "changeAdminCustomerBirthday")
      .mockResolvedValue({
        user_id: "user-1",
        birthday: { month: 3, day: 15 },
        locked: true,
        updated_at: "2026-08-24T12:00:00Z",
      });

    render(<AdminBirthdayEditor userId="user-1" initialBirthday={null} />);

    await user.click(screen.getByRole("button", { name: "Указать дату" }));
    await user.selectOptions(screen.getByLabelText("Месяц рождения"), "3");
    await user.selectOptions(screen.getByLabelText("День рождения"), "15");
    await user.type(
      screen.getByLabelText("Причина изменения"),
      "Подтверждено клиентом",
    );
    await user.click(
      screen.getByRole("button", { name: "Сохранить дату клиента" }),
    );

    expect(change).toHaveBeenCalledWith("user-1", {
      birthday: { month: 3, day: 15 },
      reason: "Подтверждено клиентом",
    });
    expect(await screen.findByText("15 марта")).toBeInTheDocument();
    expect(document.querySelector('input[type="date"]')).toBeNull();
  });
});

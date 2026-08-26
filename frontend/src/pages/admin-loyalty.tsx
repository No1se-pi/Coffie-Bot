import { useContext, useEffect, useRef, useState, type FormEvent } from "react";
import { coffeeApi, createIdempotencyKey } from "../api/client";
import type {
  AdminLoyaltyV2Settings,
  BirthdayValue,
  LoyaltyWalletMode,
  WalletModePreview,
} from "../api/types";
import {
  BirthdayFields,
  birthdayDaysInMonth,
  formatBirthday,
} from "../components/BirthdayFields";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Metric,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { AuthContext } from "../auth/AuthContext";

const walletModeLabels: Record<LoyaltyWalletMode, string> = {
  shared: "Общий кошелёк",
  separate: "По заведениям",
};

export function AdminLoyaltyV2Controls() {
  const auth = useContext(AuthContext);
  const canChangeWalletMode = !auth || auth.actor?.role === "owner";
  const resource = useResource(coffeeApi.getAdminLoyaltyV2);
  const [form, setForm] = useState<AdminLoyaltyV2Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [targetMode, setTargetMode] = useState<LoyaltyWalletMode>("separate");
  const [preview, setPreview] = useState<WalletModePreview | null>(null);
  const [fallbackVenueId, setFallbackVenueId] = useState("");
  const [previewFallbackVenueId, setPreviewFallbackVenueId] = useState("");
  const [modeReason, setModeReason] = useState("");
  const [modeConfirmed, setModeConfirmed] = useState(false);
  const [modeBusy, setModeBusy] = useState(false);
  const [modeError, setModeError] = useState<string | null>(null);
  const [modeSaved, setModeSaved] = useState(false);
  const idempotencyKey = useRef(createIdempotencyKey());

  useEffect(() => {
    if (!resource.data) return;
    setForm(resource.data);
    setTargetMode(
      resource.data.wallet_mode === "shared" ? "separate" : "shared",
    );
  }, [resource.data]);

  const update = <K extends keyof AdminLoyaltyV2Settings>(
    key: K,
    value: AdminLoyaltyV2Settings[K],
  ) => setForm((current) => (current ? { ...current, [key]: value } : current));

  const saveSettings = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const safeSettings = {
        point_value_minor: form.point_value_minor,
        max_redemption_percent: form.max_redemption_percent,
        expiry_months: form.expiry_months,
        expiry_days_override: form.expiry_days_override,
        expiry_reminder_days: form.expiry_reminder_days,
        default_bonus_venue_id: form.default_bonus_venue_id,
        rounding: form.rounding,
        venue_rates: form.venue_rates.map(
          ({
            venue_id,
            loyalty_points_enabled,
            accrual_basis_points,
            rounding_mode,
          }) => ({
            venue_id,
            loyalty_points_enabled,
            accrual_basis_points,
            rounding_mode,
          }),
        ),
        birthday: form.birthday,
      };
      setForm(await coffeeApi.saveAdminLoyaltyV2(safeSettings));
      setSaved(true);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить Loyalty V2",
      );
    } finally {
      setSaving(false);
    }
  };

  const rotateModeRequest = () => {
    // Retrying an ambiguous response keeps the key; changing any business
    // input rotates it so one receipt cannot authorize another migration.
    idempotencyKey.current = createIdempotencyKey();
    setModeConfirmed(false);
    setModeSaved(false);
    setModeError(null);
  };

  const loadPreview = async () => {
    setModeBusy(true);
    setModeError(null);
    try {
      setPreview(
        await coffeeApi.previewWalletMode({
          target_mode: targetMode,
          fallback_venue_id: fallbackVenueId || null,
        }),
      );
      setPreviewFallbackVenueId(fallbackVenueId);
      setModeReason("");
      rotateModeRequest();
    } catch (reason) {
      setModeError(
        reason instanceof Error
          ? reason.message
          : "Не удалось подготовить переход",
      );
    } finally {
      setModeBusy(false);
    }
  };

  const confirmMode = async (event: FormEvent) => {
    event.preventDefault();
    if (!preview) return;
    const reason = modeReason.trim().replace(/\s+/g, " ");
    if (reason.length < 3) {
      setModeError("Укажите причину минимум из трёх символов");
      return;
    }
    if (!modeConfirmed) {
      setModeError("Подтвердите миграцию кошельков");
      return;
    }
    if (
      preview.fallback_required &&
      (!fallbackVenueId || fallbackVenueId !== previewFallbackVenueId)
    ) {
      setModeError("Обновите предпросмотр с выбранным заведением");
      return;
    }
    setModeBusy(true);
    setModeError(null);
    try {
      const result = await coffeeApi.confirmWalletMode(
        {
          target_mode: preview.target_mode,
          preview_hash: preview.preview_hash,
          fallback_venue_id: fallbackVenueId || null,
          reason,
          confirm: true,
        },
        idempotencyKey.current,
      );
      setForm((current) =>
        current ? { ...current, wallet_mode: result.wallet_mode } : current,
      );
      setModeSaved(true);
    } catch (reasonValue) {
      setModeError(
        reasonValue instanceof Error
          ? reasonValue.message
          : "Не удалось сменить режим",
      );
    } finally {
      setModeBusy(false);
    }
  };

  return (
    <section aria-labelledby="loyalty-v2-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Loyalty V2</p>
          <h2 id="loyalty-v2-heading">Баллы и birthday-правила</h2>
        </div>
      </div>
      {resource.loading && <Loader label="Загружаем Loyalty V2…" />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {!resource.loading && !resource.error && !form && (
        <EmptyState title="Настройки пока недоступны" text="Повторите позже." />
      )}
      {form && (
        <>
          <form
            className="settings-form"
            onSubmit={(event) => void saveSettings(event)}
          >
            <Panel>
              <div className="section-heading">
                <div>
                  <h2>Общие правила</h2>
                  <p className="muted">
                    Срок действия считается календарными месяцами.
                  </p>
                </div>
                <Badge tone="accent">
                  {walletModeLabels[form.wallet_mode]}
                </Badge>
              </div>
              <div className="form-grid">
                <Field label="Скидка за 1 балл, ₽">
                  <input
                    required
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.point_value_minor / 100}
                    onChange={(event) =>
                      update(
                        "point_value_minor",
                        Math.round(Number(event.target.value) * 100),
                      )
                    }
                  />
                </Field>
                <Field label="Максимум оплаты баллами, %">
                  <input
                    required
                    type="number"
                    min="0"
                    max="100"
                    value={form.max_redemption_percent}
                    onChange={(event) =>
                      update(
                        "max_redemption_percent",
                        Number(event.target.value),
                      )
                    }
                  />
                </Field>
                <Field label="Срок действия баллов, месяцев">
                  <input
                    required
                    type="number"
                    min="1"
                    value={form.expiry_months}
                    onChange={(event) =>
                      update("expiry_months", Number(event.target.value))
                    }
                  />
                </Field>
                <Field
                  label="Override срока в днях"
                  hint="Если задан, имеет приоритет над календарным сроком в месяцах. Очистите поле, чтобы использовать срок выше."
                >
                  <input
                    type="number"
                    min="1"
                    max="3650"
                    value={form.expiry_days_override ?? ""}
                    onChange={(event) =>
                      update(
                        "expiry_days_override",
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                      )
                    }
                    placeholder="Не задан"
                  />
                </Field>
                <Field
                  label="Напомнить о сгорании за, дней"
                  hint="0 — не отправлять напоминание"
                >
                  <input
                    required
                    type="number"
                    min="0"
                    max="365"
                    value={form.expiry_reminder_days}
                    onChange={(event) =>
                      update("expiry_reminder_days", Number(event.target.value))
                    }
                  />
                </Field>
                <Field
                  label="Заведение для бонусов без origin"
                  hint="Не задано — backend не будет выбирать заведение"
                >
                  <select
                    value={form.default_bonus_venue_id ?? ""}
                    onChange={(event) =>
                      update(
                        "default_bonus_venue_id",
                        event.target.value || null,
                      )
                    }
                  >
                    <option value="">Не задано</option>
                    {form.venue_rates
                      .filter(
                        (rate) => rate.available && rate.loyalty_points_enabled,
                      )
                      .map((rate) => (
                        <option key={rate.venue_id} value={rate.venue_id}>
                          {rate.venue_name}
                        </option>
                      ))}
                  </select>
                </Field>
                <Field label="Округление">
                  <select
                    value={form.rounding}
                    onChange={(event) =>
                      update(
                        "rounding",
                        event.target
                          .value as AdminLoyaltyV2Settings["rounding"],
                      )
                    }
                  >
                    <option value="floor">Вниз</option>
                    <option value="half_up">До ближайшего</option>
                    <option value="ceiling">Вверх</option>
                  </select>
                </Field>
              </div>
            </Panel>
            <Panel>
              <h2>Ставки начисления</h2>
              <div className="form-grid">
                {form.venue_rates.map((rate, index) => (
                  <div key={rate.venue_id}>
                    <label className="checkbox">
                      <input
                        type="checkbox"
                        checked={rate.loyalty_points_enabled}
                        disabled={!rate.available}
                        onChange={(event) => {
                          const enabled = event.target.checked;
                          setForm((current) =>
                            current
                              ? {
                                  ...current,
                                  default_bonus_venue_id:
                                    !enabled &&
                                    current.default_bonus_venue_id ===
                                      rate.venue_id
                                      ? null
                                      : current.default_bonus_venue_id,
                                  venue_rates: current.venue_rates.map(
                                    (candidate, candidateIndex) =>
                                      candidateIndex === index
                                        ? {
                                            ...candidate,
                                            loyalty_points_enabled: enabled,
                                          }
                                        : candidate,
                                  ),
                                }
                              : current,
                          );
                        }}
                      />
                      <span>
                        {rate.venue_name}: начислять баллы
                        {!rate.available && " · Заведение недоступно"}
                      </span>
                    </label>
                    <Field label={`${rate.venue_name}, %`}>
                      <input
                        required
                        type="number"
                        min="0"
                        max="100"
                        step="0.01"
                        disabled={
                          !rate.available || !rate.loyalty_points_enabled
                        }
                        value={rate.accrual_basis_points / 100}
                        onChange={(event) =>
                          update(
                            "venue_rates",
                            form.venue_rates.map((candidate, candidateIndex) =>
                              candidateIndex === index
                                ? {
                                    ...candidate,
                                    accrual_basis_points: Math.round(
                                      Number(event.target.value) * 100,
                                    ),
                                  }
                                : candidate,
                            ),
                          )
                        }
                      />
                    </Field>
                    <Field label={`${rate.venue_name}: округление`}>
                      <select
                        disabled={
                          !rate.available || !rate.loyalty_points_enabled
                        }
                        value={rate.rounding_mode}
                        onChange={(event) =>
                          update(
                            "venue_rates",
                            form.venue_rates.map((candidate, candidateIndex) =>
                              candidateIndex === index
                                ? {
                                    ...candidate,
                                    rounding_mode: event.target
                                      .value as typeof rate.rounding_mode,
                                  }
                                : candidate,
                            ),
                          )
                        }
                      >
                        <option value="floor">Вниз</option>
                        <option value="half_up">До ближайшего</option>
                        <option value="ceiling">Вверх</option>
                      </select>
                    </Field>
                  </div>
                ))}
              </div>
            </Panel>
            <Panel>
              <div className="toggle-heading">
                <div>
                  <h2>День рождения</h2>
                  <p>Клиент передаёт только день и месяц.</p>
                </div>
                <label className="switch">
                  <input
                    type="checkbox"
                    aria-label="Birthday-предложение включено"
                    checked={form.birthday.enabled}
                    onChange={(event) =>
                      update("birthday", {
                        ...form.birthday,
                        enabled: event.target.checked,
                      })
                    }
                  />
                  <span />
                </label>
              </div>
              <div className="form-grid">
                <Field label="Birthday-скидка, %">
                  <input
                    required
                    type="number"
                    min="0"
                    max="100"
                    value={form.birthday.discount_percent}
                    onChange={(event) =>
                      update("birthday", {
                        ...form.birthday,
                        discount_percent: Number(event.target.value),
                      })
                    }
                  />
                </Field>
                <Field label="Срок предложения, дней">
                  <input
                    required
                    type="number"
                    min="1"
                    value={form.birthday.window_days}
                    onChange={(event) =>
                      update("birthday", {
                        ...form.birthday,
                        window_days: Number(event.target.value),
                      })
                    }
                  />
                </Field>
              </div>
              <div
                className="chip-row"
                aria-label="Заведения birthday-предложения"
              >
                {form.birthday.eligible_venue_ids.length === 0 && (
                  <Badge tone="success">Все активные заведения</Badge>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() =>
                    update("birthday", {
                      ...form.birthday,
                      eligible_venue_ids: [],
                    })
                  }
                >
                  Выбрать все
                </Button>
                {form.venue_rates
                  .filter((rate) => rate.available)
                  .map((rate) => (
                    <label className="checkbox" key={rate.venue_id}>
                      <input
                        type="checkbox"
                        checked={
                          form.birthday.eligible_venue_ids.length === 0 ||
                          form.birthday.eligible_venue_ids.includes(
                            rate.venue_id,
                          )
                        }
                        onChange={(event) => {
                          const currentIds =
                            form.birthday.eligible_venue_ids.length === 0
                              ? form.venue_rates
                                  .filter((venue) => venue.available)
                                  .map((venue) => venue.venue_id)
                              : form.birthday.eligible_venue_ids;
                          update("birthday", {
                            ...form.birthday,
                            eligible_venue_ids: event.target.checked
                              ? Array.from(
                                  new Set([...currentIds, rate.venue_id]),
                                )
                              : currentIds.filter((id) => id !== rate.venue_id),
                          });
                        }}
                      />
                      <span>{rate.venue_name}</span>
                    </label>
                  ))}
              </div>
              <p className="muted">
                Пустой список в API означает все активные заведения, а не
                «нигде».
              </p>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={form.birthday.stackable}
                  onChange={(event) =>
                    update("birthday", {
                      ...form.birthday,
                      stackable: event.target.checked,
                    })
                  }
                />
                <span>Складывать с другими скидками</span>
              </label>
            </Panel>
            {saved && (
              <div className="inline-success" role="status">
                Loyalty V2 сохранена
              </div>
            )}
            {error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
            <Button type="submit" disabled={saving}>
              {saving ? "Сохраняем…" : "Сохранить Loyalty V2"}
            </Button>
          </form>

          {canChangeWalletMode && (
            <Panel className="operation-panel">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Только владелец</p>
                  <h2>Смена режима кошельков</h2>
                </div>
              </div>
              {modeSaved ? (
                <div className="operation-success" role="status">
                  <span>✓</span>
                  <h3>Режим изменён</h3>
                  <p>{walletModeLabels[form.wallet_mode]}</p>
                </div>
              ) : preview ? (
                <form
                  className="form"
                  onSubmit={(event) => void confirmMode(event)}
                >
                  <div className="metrics-grid">
                    <Metric
                      value={preview.customers_affected}
                      label="клиентов"
                    />
                    <Metric
                      value={preview.wallets_affected}
                      label="кошельков"
                    />
                    <Metric
                      value={preview.total_balance_points}
                      label="баллов сохранится"
                    />
                    <Metric
                      value={preview.transfer_operations}
                      label="transfer-операций"
                    />
                  </div>
                  {preview.warnings.map((warning) => (
                    <div className="inline-warning" key={warning}>
                      {warning}
                    </div>
                  ))}
                  {preview.fallback_required && (
                    <>
                      <div className="inline-warning">
                        {preview.unresolved_points} баллов не имеют активного
                        заведения. Выберите, куда их перенести.
                      </div>
                      <Field label="Активное fallback-заведение">
                        <select
                          required
                          value={fallbackVenueId}
                          onChange={(event) => {
                            setFallbackVenueId(event.target.value);
                            rotateModeRequest();
                          }}
                        >
                          <option value="">Выберите заведение</option>
                          {preview.eligible_fallback_venues
                            .filter((venue) => venue.available)
                            .map((venue) => (
                              <option key={venue.id} value={venue.id}>
                                {venue.name}
                              </option>
                            ))}
                        </select>
                      </Field>
                      {fallbackVenueId !== previewFallbackVenueId && (
                        <Button
                          type="button"
                          variant="secondary"
                          disabled={modeBusy || !fallbackVenueId}
                          onClick={() => void loadPreview()}
                        >
                          Обновить предпросмотр
                        </Button>
                      )}
                    </>
                  )}
                  <Field label="Причина смены режима" hint="Попадёт в аудит">
                    <textarea
                      required
                      minLength={3}
                      rows={3}
                      value={modeReason}
                      onChange={(event) => {
                        if (event.target.value !== modeReason)
                          rotateModeRequest();
                        setModeReason(event.target.value);
                      }}
                    />
                  </Field>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={modeConfirmed}
                      onChange={(event) => {
                        setModeConfirmed(event.target.checked);
                        setModeError(null);
                      }}
                    />
                    <span>Подтверждаю миграцию кошельков</span>
                  </label>
                  <div className="action-row">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => {
                        setPreview(null);
                        setFallbackVenueId("");
                        setPreviewFallbackVenueId("");
                        rotateModeRequest();
                      }}
                    >
                      Изменить
                    </Button>
                    <Button
                      type="submit"
                      variant="danger"
                      disabled={
                        modeBusy ||
                        (preview.fallback_required &&
                          (!fallbackVenueId ||
                            fallbackVenueId !== previewFallbackVenueId))
                      }
                    >
                      {modeBusy ? "Подтверждаем…" : "Сменить режим"}
                    </Button>
                  </div>
                </form>
              ) : (
                <div className="form">
                  <Field label="Новый режим">
                    <select
                      value={targetMode}
                      onChange={(event) => {
                        setTargetMode(event.target.value as LoyaltyWalletMode);
                        setFallbackVenueId("");
                        setPreviewFallbackVenueId("");
                        rotateModeRequest();
                      }}
                    >
                      <option value="shared">Общий кошелёк</option>
                      <option value="separate">По заведениям</option>
                    </select>
                  </Field>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={modeBusy || targetMode === form.wallet_mode}
                    onClick={() => void loadPreview()}
                  >
                    {modeBusy ? "Готовим…" : "Показать предпросмотр"}
                  </Button>
                </div>
              )}
              {modeError && (
                <div className="inline-error" role="alert">
                  {modeError}
                </div>
              )}
            </Panel>
          )}
        </>
      )}
    </section>
  );
}

export function AdminBirthdayEditor({
  userId,
  initialBirthday,
}: {
  userId: string;
  initialBirthday: BirthdayValue | null;
}) {
  const [current, setCurrent] = useState(initialBirthday);
  const [month, setMonth] = useState(
    initialBirthday ? String(initialBirthday.month) : "",
  );
  const [day, setDay] = useState(
    initialBirthday ? String(initialBirthday.day) : "",
  );
  const [reason, setReason] = useState("");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const birthday = { month: Number(month), day: Number(day) };
    const normalizedReason = reason.trim().replace(/\s+/g, " ");
    if (
      birthday.month < 1 ||
      birthday.month > 12 ||
      birthday.day < 1 ||
      birthday.day > birthdayDaysInMonth(birthday.month)
    ) {
      setError("Выберите корректные день и месяц");
      return;
    }
    if (normalizedReason.length < 3) {
      setError("Укажите причину изменения");
      return;
    }
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const result = await coffeeApi.changeAdminCustomerBirthday(userId, {
        birthday,
        reason: normalizedReason,
      });
      setCurrent(result.birthday);
      setMonth(String(result.birthday.month));
      setDay(String(result.birthday.day));
      setReason("");
      setEditing(false);
      setSaved(true);
    } catch (reasonValue) {
      setError(
        reasonValue instanceof Error
          ? reasonValue.message
          : "Не удалось изменить дату рождения",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Профиль</p>
          <h2>День рождения</h2>
        </div>
        {current && <Badge>{formatBirthday(current)}</Badge>}
      </div>
      {editing ? (
        <form className="form" onSubmit={(event) => void save(event)}>
          <BirthdayFields
            month={month}
            day={day}
            disabled={saving}
            onMonthChange={(value) => {
              setMonth(value);
              if (Number(day) > birthdayDaysInMonth(Number(value))) setDay("");
              setError(null);
            }}
            onDayChange={(value) => {
              setDay(value);
              setError(null);
            }}
          />
          <Field label="Причина изменения" hint="Обязательна для аудита">
            <textarea
              required
              minLength={3}
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
          {month === "2" && day === "29" && (
            <p className="muted">
              В невисокосный год backend применит 28 февраля.
            </p>
          )}
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <div className="action-row">
            <Button
              type="button"
              variant="secondary"
              disabled={saving}
              onClick={() => setEditing(false)}
            >
              Отмена
            </Button>
            <Button type="submit" disabled={saving || !month || !day}>
              {saving ? "Сохраняем…" : "Сохранить дату клиента"}
            </Button>
          </div>
        </form>
      ) : (
        <>
          <p className="muted">
            {current
              ? "Изменение с причиной попадёт в аудит."
              : "Дата не указана; год рождения не собирается."}
          </p>
          {saved && (
            <div className="inline-success" role="status">
              Дата рождения обновлена
            </div>
          )}
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setEditing(true);
              setSaved(false);
              setError(null);
            }}
          >
            {current ? "Изменить дату" : "Указать дату"}
          </Button>
        </>
      )}
    </Panel>
  );
}

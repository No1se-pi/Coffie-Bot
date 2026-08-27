import { useEffect, useState, type FormEvent } from "react";
import { coffeeApi } from "../api/client";
import type {
  AdminDeliverySettingsDraft,
  AdminDeliveryZone,
  AdminDeliveryZoneDraft,
  AdminFulfillmentLocation,
} from "../api/types";
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { formatMoney, rublesToMinor } from "../utils/format";

const emptyZone: AdminDeliveryZoneDraft = {
  name: "",
  description: null,
  fee_minor: 0,
  minimum_order_minor: null,
  is_active: true,
  sort_order: 0,
};

const weekdays = [
  ["monday", "Понедельник"],
  ["tuesday", "Вторник"],
  ["wednesday", "Среда"],
  ["thursday", "Четверг"],
  ["friday", "Пятница"],
  ["saturday", "Суббота"],
  ["sunday", "Воскресенье"],
] as const;

export function AdminDeliveryPage() {
  const resource = useResource(coffeeApi.getAdminDelivery);
  const [settings, setSettings] = useState<AdminDeliverySettingsDraft | null>(
    null,
  );
  const [zone, setZone] = useState<AdminDeliveryZone | null>(null);
  const [zoneDraft, setZoneDraft] = useState<AdminDeliveryZoneDraft>(emptyZone);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  useEffect(() => {
    if (!resource.data) return;
    setSettings(
      Object.fromEntries(
        Object.entries(resource.data.settings).filter(([key]) => key !== "id"),
      ) as AdminDeliverySettingsDraft,
    );
  }, [resource.data]);

  const saveSettings = async (event: FormEvent) => {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveAdminDeliverySettings(settings);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason : new Error("Не удалось сохранить"),
      );
    } finally {
      setSaving(false);
    }
  };

  const saveZone = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveAdminDeliveryZone(zone, zoneDraft);
      setZone(null);
      setZoneDraft(emptyZone);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось сохранить зону"),
      );
    } finally {
      setSaving(false);
    }
  };

  const saveLocation = async (location: AdminFulfillmentLocation) => {
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveAdminFulfillmentLocation(location);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось сохранить точку"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Page
      title="Заказы и доставка"
      eyebrow="Выдача, консолидация и простые зоны"
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <ErrorState error={error} compact />}
      {resource.data && settings && (
        <div className="card-list">
          <Panel>
            <h2>Общие настройки</h2>
            <form
              className="order-form"
              onSubmit={(event) => void saveSettings(event)}
            >
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={settings.delivery_enabled}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      delivery_enabled: event.target.checked,
                    })
                  }
                />
                <span>Доставка включена</span>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={settings.scheduling_allowed}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      scheduling_allowed: event.target.checked,
                    })
                  }
                />
                <span>Разрешить заказ ко времени</span>
              </label>
              <Field label="Минимальная сумма, ₽">
                <input
                  type="number"
                  min={0}
                  value={settings.minimum_order_minor / 100}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      minimum_order_minor:
                        rublesToMinor(event.target.value) ?? 0,
                    })
                  }
                />
              </Field>
              <Field label="Фиксированная доставка, ₽">
                <input
                  type="number"
                  min={0}
                  value={settings.fixed_fee_minor / 100}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      fixed_fee_minor: rublesToMinor(event.target.value) ?? 0,
                    })
                  }
                />
              </Field>
              <Field
                label="Бесплатно от, ₽"
                hint="Оставьте пустым, чтобы отключить"
              >
                <input
                  type="number"
                  min={0}
                  value={
                    settings.free_delivery_threshold_minor === null
                      ? ""
                      : settings.free_delivery_threshold_minor / 100
                  }
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      free_delivery_threshold_minor: event.target.value
                        ? rublesToMinor(event.target.value)
                        : null,
                    })
                  }
                />
              </Field>
              <Field label="Минимальное время приготовления, мин">
                <input
                  type="number"
                  min={0}
                  max={1440}
                  value={settings.earliest_preparation_minutes}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      earliest_preparation_minutes: Number(event.target.value),
                    })
                  }
                />
              </Field>
              <div className="delivery-hours-grid">
                {weekdays.map(([key, label]) => (
                  <Field key={key} label={label} hint="HH:MM-HH:MM или closed">
                    <input
                      value={String(settings.operating_hours[key] ?? "")}
                      placeholder="10:00-22:00"
                      onChange={(event) => {
                        const operatingHours = { ...settings.operating_hours };
                        if (event.target.value)
                          operatingHours[key] = event.target.value;
                        else delete operatingHours[key];
                        setSettings({
                          ...settings,
                          operating_hours: operatingHours,
                        });
                      }}
                    />
                  </Field>
                ))}
              </div>
              <Field label="Точка выдачи по умолчанию">
                <select
                  value={settings.default_pickup_location_id ?? ""}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      default_pickup_location_id: event.target.value || null,
                    })
                  }
                >
                  <option value="">Не выбрана</option>
                  {resource.data.locations
                    .filter((value) => value.pickup_enabled)
                    .map((value) => (
                      <option key={value.id} value={value.id}>
                        {value.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Field label="Точка консолидации">
                <select
                  value={settings.consolidation_location_id ?? ""}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      consolidation_location_id: event.target.value || null,
                    })
                  }
                >
                  <option value="">Не выбрана</option>
                  {resource.data.locations
                    .filter((value) => value.consolidation_enabled)
                    .map((value) => (
                      <option key={value.id} value={value.id}>
                        {value.name}
                      </option>
                    ))}
                </select>
              </Field>
              <Button type="submit" disabled={saving}>
                {saving ? "Сохраняем…" : "Сохранить настройки"}
              </Button>
            </form>
          </Panel>

          <Panel>
            <h2>Точки</h2>
            <div className="card-list">
              {resource.data.locations.map((location) => (
                <LocationEditor
                  key={location.id}
                  value={location}
                  disabled={saving}
                  onSave={saveLocation}
                />
              ))}
            </div>
          </Panel>

          <Panel>
            <h2>Зоны доставки</h2>
            {resource.data.zones.filter((value) => !value.archived).length ? (
              <div className="card-list">
                {resource.data.zones
                  .filter((value) => !value.archived)
                  .map((value) => (
                    <div className="order-line-snapshot" key={value.id}>
                      <span>
                        <strong>{value.name}</strong>
                        <small>
                          {formatMoney(value.fee_minor)} · минимум{" "}
                          {value.minimum_order_minor === null
                            ? "общий"
                            : formatMoney(value.minimum_order_minor)}
                        </small>
                      </span>
                      <div className="action-row">
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setZone(value);
                            setZoneDraft({
                              name: value.name,
                              description: value.description,
                              fee_minor: value.fee_minor,
                              minimum_order_minor: value.minimum_order_minor,
                              is_active: value.is_active,
                              sort_order: value.sort_order,
                            });
                          }}
                        >
                          Изменить
                        </Button>
                        <Button
                          variant="danger"
                          onClick={() =>
                            void coffeeApi
                              .archiveAdminDeliveryZone(value.id)
                              .then(resource.reload)
                          }
                        >
                          В архив
                        </Button>
                      </div>
                    </div>
                  ))}
              </div>
            ) : (
              <EmptyState
                title="Зон пока нет"
                text="Добавьте понятную зону, которую клиент выберет вручную."
              />
            )}
            <form
              className="order-form"
              onSubmit={(event) => void saveZone(event)}
            >
              <h3>{zone ? `Редактирование: ${zone.name}` : "Новая зона"}</h3>
              <Field label="Название">
                <input
                  value={zoneDraft.name}
                  onChange={(event) =>
                    setZoneDraft({ ...zoneDraft, name: event.target.value })
                  }
                  required
                />
              </Field>
              <Field label="Описание">
                <textarea
                  value={zoneDraft.description ?? ""}
                  onChange={(event) =>
                    setZoneDraft({
                      ...zoneDraft,
                      description: event.target.value || null,
                    })
                  }
                />
              </Field>
              <Field label="Стоимость, ₽">
                <input
                  type="number"
                  min={0}
                  value={zoneDraft.fee_minor / 100}
                  onChange={(event) =>
                    setZoneDraft({
                      ...zoneDraft,
                      fee_minor: rublesToMinor(event.target.value) ?? 0,
                    })
                  }
                />
              </Field>
              <Field label="Минимальная сумма зоны, ₽">
                <input
                  type="number"
                  min={0}
                  value={
                    zoneDraft.minimum_order_minor === null
                      ? ""
                      : zoneDraft.minimum_order_minor / 100
                  }
                  onChange={(event) =>
                    setZoneDraft({
                      ...zoneDraft,
                      minimum_order_minor: event.target.value
                        ? rublesToMinor(event.target.value)
                        : null,
                    })
                  }
                />
              </Field>
              <div className="action-row">
                <Button type="submit" disabled={saving}>
                  {zone ? "Сохранить" : "Добавить зону"}
                </Button>
                {zone && (
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => {
                      setZone(null);
                      setZoneDraft(emptyZone);
                    }}
                  >
                    Отмена
                  </Button>
                )}
              </div>
            </form>
          </Panel>
        </div>
      )}
    </Page>
  );
}

function LocationEditor({
  value,
  disabled,
  onSave,
}: {
  value: AdminFulfillmentLocation;
  disabled: boolean;
  onSave: (value: AdminFulfillmentLocation) => Promise<void>;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <div className="delivery-location">
      <div>
        <strong>{draft.name}</strong>
        <small>{draft.address}</small>
      </div>
      <label>
        <input
          type="checkbox"
          checked={draft.pickup_enabled}
          onChange={(event) =>
            setDraft({ ...draft, pickup_enabled: event.target.checked })
          }
        />{" "}
        Выдача
      </label>
      <label>
        <input
          type="checkbox"
          checked={draft.consolidation_enabled}
          onChange={(event) =>
            setDraft({ ...draft, consolidation_enabled: event.target.checked })
          }
        />{" "}
        Консолидация
      </label>
      <Field label="Приготовление, мин">
        <input
          type="number"
          min={0}
          max={1440}
          value={draft.preparation_minutes}
          onChange={(event) =>
            setDraft({
              ...draft,
              preparation_minutes: Number(event.target.value),
            })
          }
        />
      </Field>
      <Field label="Комментарий к выдаче">
        <input
          value={draft.pickup_comment ?? ""}
          onChange={(event) =>
            setDraft({ ...draft, pickup_comment: event.target.value || null })
          }
        />
      </Field>
      <Button
        variant="secondary"
        disabled={disabled}
        onClick={() => void onSave(draft)}
      >
        Сохранить точку
      </Button>
    </div>
  );
}

import { useEffect, useState, type FormEvent } from "react";
import { coffeeApi } from "../api/client";
import type {
  AdminDeliverySettingsDraft,
  AdminDeliveryZone,
  AdminDeliveryZoneDraft,
  AdminFulfillmentLocation,
  AdminFulfillmentLocationDraft,
  Venue,
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
import { DeliveryMap } from "../components/DeliveryMap";

const emptyZone: AdminDeliveryZoneDraft = {
  name: "",
  description: null,
  fee_minor: 0,
  minimum_order_minor: null,
  location_id: null,
  radius_meters: null,
  polygon: [],
  is_active: true,
  sort_order: 0,
};

const emptyLocation: AdminFulfillmentLocationDraft = {
  venue_id: null,
  slug: "",
  name: "",
  address: "",
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

type ZoneGeometryMode = "radius" | "polygon";

function hoursParts(value: unknown) {
  if (typeof value !== "string" || !value) {
    return { start: "", end: "", closed: false };
  }
  if (value.toLowerCase() === "closed") {
    return { start: "", end: "", closed: true };
  }
  const [start = "", end = ""] = value.split("-", 2);
  return { start, end, closed: false };
}

export function AdminDeliveryPage() {
  const resource = useResource(coffeeApi.getAdminDelivery);
  const venues = useResource(coffeeApi.getVenues);
  const [settings, setSettings] = useState<AdminDeliverySettingsDraft | null>(
    null,
  );
  const [zone, setZone] = useState<AdminDeliveryZone | null>(null);
  const [zoneDraft, setZoneDraft] = useState<AdminDeliveryZoneDraft>(emptyZone);
  const [zoneGeometryMode, setZoneGeometryMode] =
    useState<ZoneGeometryMode>("radius");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [settingsSaved, setSettingsSaved] = useState(false);
  const [newLocation, setNewLocation] = useState(emptyLocation);
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
    setSettingsSaved(false);
    try {
      await coffeeApi.saveAdminDeliverySettings(settings);
      await resource.reload();
      setSettingsSaved(true);
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
    if (zoneGeometryMode === "polygon" && zoneDraft.polygon.length < 3) {
      setError(new Error("Нарисуйте зону минимум из трёх точек"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveAdminDeliveryZone(zone, zoneDraft);
      setZone(null);
      setZoneDraft(emptyZone);
      setZoneGeometryMode("radius");
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

  const createLocation = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.createAdminFulfillmentLocation(newLocation);
      setNewLocation(emptyLocation);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось добавить точку"),
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
              onChange={() => setSettingsSaved(false)}
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
              <fieldset className="delivery-hours-fieldset">
                <legend>Часы доставки</legend>
                <p className="muted">
                  Пустой день работает без ограничения по времени. Для
                  нерабочего дня включите «Выходной».
                </p>
                <div className="delivery-hours-grid">
                  {weekdays.map(([key, label]) => {
                    const parts = hoursParts(settings.operating_hours[key]);
                    const updateHours = (next: {
                      start: string;
                      end: string;
                      closed: boolean;
                    }) => {
                      const operatingHours = { ...settings.operating_hours };
                      if (next.closed) operatingHours[key] = "closed";
                      else if (next.start || next.end)
                        operatingHours[key] = `${next.start}-${next.end}`;
                      else delete operatingHours[key];
                      setSettings({
                        ...settings,
                        operating_hours: operatingHours,
                      });
                      setSettingsSaved(false);
                    };
                    return (
                      <div className="delivery-hours-row" key={key}>
                        <strong>{label}</strong>
                        <label>
                          <span>С</span>
                          <input
                            aria-label={`${label}: начало`}
                            type="time"
                            disabled={parts.closed}
                            required={Boolean(parts.start || parts.end)}
                            value={parts.start}
                            onChange={(event) =>
                              updateHours({
                                ...parts,
                                start: event.target.value,
                              })
                            }
                          />
                        </label>
                        <label>
                          <span>До</span>
                          <input
                            aria-label={`${label}: окончание`}
                            type="time"
                            disabled={parts.closed}
                            required={Boolean(parts.start || parts.end)}
                            value={parts.end}
                            onChange={(event) =>
                              updateHours({ ...parts, end: event.target.value })
                            }
                          />
                        </label>
                        <label className="checkbox">
                          <input
                            aria-label={`${label}: выходной`}
                            type="checkbox"
                            checked={parts.closed}
                            onChange={(event) =>
                              updateHours({
                                start: "",
                                end: "",
                                closed: event.target.checked,
                              })
                            }
                          />
                          <span>Выходной</span>
                        </label>
                      </div>
                    );
                  })}
                </div>
              </fieldset>
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
              <Field
                label="Где собирают заказы доставки"
                hint="Необязательно. Выберите общий хаб, только если курьеры забирают заказы не из точки приготовления."
              >
                <select
                  value={settings.consolidation_location_id ?? ""}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      consolidation_location_id: event.target.value || null,
                    })
                  }
                >
                  <option value="">Прямо из точки приготовления</option>
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
              {settingsSaved && (
                <span className="success-text" role="status">
                  Настройки и часы работы сохранены
                </span>
              )}
            </form>
          </Panel>

          <Panel id="locations">
            <h2>Точки</h2>
            <p className="muted">
              Точка — физический адрес конкретного заведения. Карточки ниже
              свёрнуты: нажмите на нужную, чтобы изменить адрес, карту или
              режимы работы.
            </p>
            <div className="card-list">
              {resource.data.locations.map((location) => (
                <LocationEditor
                  key={location.id}
                  value={location}
                  disabled={saving}
                  onSave={saveLocation}
                  venues={venues.data?.items ?? []}
                />
              ))}
            </div>
            <form
              className="order-form location-create-form"
              onSubmit={(event) => void createLocation(event)}
            >
              <h3>Новая физическая точка</h3>
              <Field label="Заведение">
                <select
                  required
                  value={newLocation.venue_id ?? ""}
                  onChange={(event) =>
                    setNewLocation({
                      ...newLocation,
                      venue_id: event.target.value || null,
                    })
                  }
                >
                  <option value="">Выберите заведение</option>
                  {venues.data?.items.map((venue) => (
                    <option key={venue.id} value={venue.id}>
                      {venue.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Название">
                <input
                  required
                  value={newLocation.name}
                  onChange={(event) =>
                    setNewLocation({ ...newLocation, name: event.target.value })
                  }
                />
              </Field>
              <Field label="Slug" hint="Латиница, цифры и дефисы">
                <input
                  required
                  pattern="[a-z0-9][a-z0-9-]*"
                  value={newLocation.slug}
                  onChange={(event) =>
                    setNewLocation({
                      ...newLocation,
                      slug: event.target.value.toLowerCase(),
                    })
                  }
                />
              </Field>
              <Field label="Адрес">
                <input
                  required
                  value={newLocation.address}
                  onChange={(event) =>
                    setNewLocation({
                      ...newLocation,
                      address: event.target.value,
                    })
                  }
                />
              </Field>
              <div className="form-grid">
                <Field label="Широта">
                  <input
                    type="number"
                    step="0.000001"
                    min={-90}
                    max={90}
                    value={newLocation.latitude ?? ""}
                    onChange={(event) =>
                      setNewLocation({
                        ...newLocation,
                        latitude: event.target.value
                          ? Number(event.target.value)
                          : null,
                      })
                    }
                  />
                </Field>
                <Field label="Долгота">
                  <input
                    type="number"
                    step="0.000001"
                    min={-180}
                    max={180}
                    value={newLocation.longitude ?? ""}
                    onChange={(event) =>
                      setNewLocation({
                        ...newLocation,
                        longitude: event.target.value
                          ? Number(event.target.value)
                          : null,
                      })
                    }
                  />
                </Field>
              </div>
              <DeliveryMap
                marker={
                  newLocation.latitude !== null &&
                  newLocation.longitude !== null
                    ? {
                        latitude: newLocation.latitude,
                        longitude: newLocation.longitude,
                      }
                    : null
                }
                markerLabel="Новая точка"
                onMarkerChange={(point) =>
                  setNewLocation({
                    ...newLocation,
                    latitude: point.latitude,
                    longitude: point.longitude,
                  })
                }
              />
              <div className="action-row">
                <Button
                  type="submit"
                  disabled={saving || !newLocation.venue_id}
                >
                  {saving ? "Добавляем…" : "Добавить точку"}
                </Button>
              </div>
            </form>
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
                            : formatMoney(value.minimum_order_minor)}{" "}
                          ·{" "}
                          {value.polygon.length
                            ? "контур на карте"
                            : value.location_id && value.radius_meters
                              ? "радиус"
                              : "без ограничения по карте"}
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
                              location_id: value.location_id,
                              radius_meters: value.radius_meters,
                              polygon: value.polygon,
                              is_active: value.is_active,
                              sort_order: value.sort_order,
                            });
                            setZoneGeometryMode(
                              value.polygon.length ? "polygon" : "radius",
                            );
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
              <Field label="Граница зоны">
                <select
                  aria-label="Способ настройки зоны"
                  value={zoneGeometryMode}
                  onChange={(event) => {
                    const mode = event.target.value as ZoneGeometryMode;
                    setZoneGeometryMode(mode);
                    setZoneDraft({
                      ...zoneDraft,
                      location_id: null,
                      radius_meters: null,
                      polygon: [],
                    });
                  }}
                >
                  <option value="radius">Радиус от физической точки</option>
                  <option value="polygon">Нарисовать вручную на карте</option>
                </select>
              </Field>
              {zoneGeometryMode === "radius" ? (
                <>
                  <Field label="Центр зоны">
                    <select
                      value={zoneDraft.location_id ?? ""}
                      onChange={(event) =>
                        setZoneDraft({
                          ...zoneDraft,
                          location_id: event.target.value || null,
                          radius_meters: event.target.value
                            ? (zoneDraft.radius_meters ?? 3000)
                            : null,
                          polygon: [],
                        })
                      }
                    >
                      <option value="">Без ограничения по карте</option>
                      {resource.data.locations
                        .filter(
                          (location) =>
                            location.latitude !== null &&
                            location.longitude !== null,
                        )
                        .map((location) => (
                          <option key={location.id} value={location.id}>
                            {location.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                  {zoneDraft.location_id && (
                    <Field label="Радиус доставки, м">
                      <input
                        type="number"
                        min={100}
                        max={100000}
                        step={100}
                        value={zoneDraft.radius_meters ?? 3000}
                        onChange={(event) =>
                          setZoneDraft({
                            ...zoneDraft,
                            radius_meters: Number(event.target.value),
                          })
                        }
                      />
                    </Field>
                  )}
                  {(() => {
                    const center = resource.data.locations.find(
                      (location) => location.id === zoneDraft.location_id,
                    );
                    return center?.latitude !== null &&
                      center?.latitude !== undefined &&
                      center.longitude !== null ? (
                      <DeliveryMap
                        center={{
                          latitude: center.latitude,
                          longitude: center.longitude,
                        }}
                        radiusMeters={zoneDraft.radius_meters}
                      />
                    ) : null;
                  })()}
                </>
              ) : (
                <div className="delivery-polygon-editor">
                  <p className="muted">
                    Поставьте вершины по границе доставки. Последняя точка
                    автоматически соединится с первой.
                  </p>
                  <DeliveryMap
                    center={(() => {
                      if (zoneDraft.polygon.length) return null;
                      const location = resource.data.locations.find(
                        (value) =>
                          value.latitude !== null && value.longitude !== null,
                      );
                      return location?.latitude !== null &&
                        location?.latitude !== undefined &&
                        location.longitude !== null
                        ? {
                            latitude: location.latitude,
                            longitude: location.longitude,
                          }
                        : null;
                    })()}
                    polygon={zoneDraft.polygon}
                    onPolygonPointAdd={(point) => {
                      if (zoneDraft.polygon.length >= 100) return;
                      setZoneDraft({
                        ...zoneDraft,
                        location_id: null,
                        radius_meters: null,
                        polygon: [...zoneDraft.polygon, point],
                      });
                    }}
                  />
                  <div className="action-row">
                    <span className="muted">
                      Точек: {zoneDraft.polygon.length}
                    </span>
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={!zoneDraft.polygon.length}
                      onClick={() =>
                        setZoneDraft({
                          ...zoneDraft,
                          polygon: zoneDraft.polygon.slice(0, -1),
                        })
                      }
                    >
                      Отменить последнюю точку
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={!zoneDraft.polygon.length}
                      onClick={() =>
                        setZoneDraft({ ...zoneDraft, polygon: [] })
                      }
                    >
                      Очистить контур
                    </Button>
                  </div>
                </div>
              )}
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
                      setZoneGeometryMode("radius");
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
  venues,
}: {
  value: AdminFulfillmentLocation;
  disabled: boolean;
  onSave: (value: AdminFulfillmentLocation) => Promise<void>;
  venues: Venue[];
}) {
  const [draft, setDraft] = useState(value);
  const [uploading, setUploading] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => setDraft(value), [value]);
  return (
    <details
      className="delivery-location"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="delivery-location__summary">
        <span>
          <strong>{draft.name}</strong>
          <small>{draft.address}</small>
        </span>
        <span className="delivery-location__summary-status">
          {draft.pickup_enabled && <small>Самовывоз</small>}
          {draft.consolidation_enabled && <small>Сборка доставки</small>}
          <b aria-hidden="true">⌄</b>
        </span>
      </summary>
      {open && (
        <div className="delivery-location__body">
          <Field label="Заведение">
            <select
              value={draft.venue_id ?? ""}
              onChange={(event) =>
                setDraft({ ...draft, venue_id: event.target.value || null })
              }
            >
              <option value="">Общая точка организации</option>
              {venues.map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Название точки">
            <input
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </Field>
          <Field label="Адрес">
            <input
              value={draft.address}
              onChange={(event) =>
                setDraft({ ...draft, address: event.target.value })
              }
            />
          </Field>
          <div className="form-grid">
            <Field label="Телефон">
              <input
                value={draft.phone ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, phone: event.target.value || null })
                }
              />
            </Field>
            <Field label="Ссылка на карту">
              <input
                type="url"
                value={draft.map_url ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, map_url: event.target.value || null })
                }
              />
            </Field>
          </div>
          <div className="form-grid">
            <Field label="Широта">
              <input
                type="number"
                step="0.000001"
                min={-90}
                max={90}
                value={draft.latitude ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    latitude: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
              />
            </Field>
            <Field label="Долгота">
              <input
                type="number"
                step="0.000001"
                min={-180}
                max={180}
                value={draft.longitude ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    longitude: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
              />
            </Field>
          </div>
          <DeliveryMap
            marker={
              draft.latitude !== null && draft.longitude !== null
                ? { latitude: draft.latitude, longitude: draft.longitude }
                : null
            }
            markerLabel={draft.name}
            onMarkerChange={(point) =>
              setDraft({
                ...draft,
                latitude: point.latitude,
                longitude: point.longitude,
              })
            }
          />
          <Field
            label="Фотография точки"
            hint="Рекомендуемый размер: 1600×900 px (16:9). JPEG, PNG или WebP, до 5 МБ"
          >
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={disabled || uploading}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                setUploading(true);
                void coffeeApi
                  .uploadAdminMedia(file, "location")
                  .then((media) =>
                    setDraft((current) => ({
                      ...current,
                      image_media_id: media.id,
                    })),
                  )
                  .finally(() => setUploading(false));
              }}
            />
          </Field>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.is_active}
              onChange={(event) =>
                setDraft({ ...draft, is_active: event.target.checked })
              }
            />{" "}
            Активна
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.pickup_enabled}
              onChange={(event) =>
                setDraft({ ...draft, pickup_enabled: event.target.checked })
              }
            />{" "}
            Доступна для самовывоза
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.consolidation_enabled}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  consolidation_enabled: event.target.checked,
                })
              }
            />{" "}
            Здесь собирают заказы доставки
          </label>
          <p className="muted">
            Включайте сборку доставки, только если курьер забирает здесь готовые
            заказы. После сохранения точка появится в поле «Где собирают заказы
            доставки» выше.
          </p>
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
                setDraft({
                  ...draft,
                  pickup_comment: event.target.value || null,
                })
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
      )}
    </details>
  );
}

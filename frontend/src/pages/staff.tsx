import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  coffeeApi,
  createIdempotencyKey,
  MEDIA_FILE_ACCEPT,
} from "../api/client";
import type {
  ContactLocation,
  OperationResult,
  PurchasePreview,
  RedemptionPreview,
  StaffClient,
  StaffClientLookup,
  StaffRewardLookup,
  TipProfile,
} from "../api/types";
import { useResource } from "../hooks/useResource";
import { closeTelegramScanner, scanQrWithTelegram } from "../telegram";
import { formatDateTime, formatMoney, rublesToMinor } from "../utils/format";
import { ReceiptQuickForm } from "./receipts";
import {
  Avatar,
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Metric,
  Page,
  Panel,
} from "../components/ui";

interface StaffWorkspaceValue {
  client: StaffClient | null;
  setClient: (client: StaffClient | null) => void;
  locations: ContactLocation[];
  selectedLocation: ContactLocation | null;
  selectLocation: (locationId: string) => void;
  locationsLoading: boolean;
  locationsError: Error | null;
  reloadLocations: () => Promise<void>;
}

const StaffWorkspaceContext = createContext<StaffWorkspaceValue | null>(null);
export const STAFF_LOCATION_STORAGE_KEY = "coffie.staff.active-location-id";

function readStoredLocationId() {
  try {
    return sessionStorage.getItem(STAFF_LOCATION_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

function persistLocationId(locationId: string) {
  try {
    if (locationId)
      sessionStorage.setItem(STAFF_LOCATION_STORAGE_KEY, locationId);
    else sessionStorage.removeItem(STAFF_LOCATION_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in embedded browsers; in-memory selection still works.
  }
}

export function StaffWorkspaceProvider({ children }: { children: ReactNode }) {
  const [client, setClient] = useState<StaffClient | null>(null);
  const contacts = useResource(coffeeApi.getContacts);
  const [selectedLocationId, setSelectedLocationId] =
    useState(readStoredLocationId);
  const locations = (contacts.data?.locations ?? []).filter(
    (location) => location.venue_id !== null,
  );
  const selectedLocation =
    locations.find((location) => location.id === selectedLocationId) ?? null;

  useEffect(() => {
    if (!contacts.data) return;
    const nextId = selectedLocation?.id ?? locations[0]?.id ?? "";
    // A removed location must never remain an invisible origin. Reconcile the
    // stored id with the live public list, then persist the explicit fallback.
    if (nextId !== selectedLocationId) setSelectedLocationId(nextId);
    persistLocationId(nextId);
  }, [contacts.data, locations, selectedLocation, selectedLocationId]);

  const selectLocation = (locationId: string) => {
    if (!locations.some((location) => location.id === locationId)) return;
    setSelectedLocationId(locationId);
    persistLocationId(locationId);
  };

  return (
    <StaffWorkspaceContext.Provider
      value={{
        client,
        setClient,
        locations,
        selectedLocation,
        selectLocation,
        locationsLoading: contacts.loading,
        locationsError: contacts.error,
        reloadLocations: contacts.reload,
      }}
    >
      {children}
    </StaffWorkspaceContext.Provider>
  );
}

function useStaffWorkspace() {
  const value = useContext(StaffWorkspaceContext);
  if (!value) throw new Error("Staff pages require StaffWorkspaceProvider");
  return value;
}

export function StaffLocationSelector() {
  const {
    locations,
    selectedLocation,
    selectLocation,
    locationsLoading,
    locationsError,
    reloadLocations,
  } = useStaffWorkspace();

  return (
    <Panel>
      <div className="section-heading">
        <div>
          <h2>Активная физическая точка</h2>
          <p className="muted">
            Операции с баллами и новый профиль будут привязаны к этой точке.
          </p>
        </div>
        {selectedLocation && <Badge tone="success">Выбрана</Badge>}
      </div>
      {locationsLoading && <Loader label="Загружаем точки…" />}
      {locationsError && (
        <ErrorState error={locationsError} onRetry={reloadLocations} compact />
      )}
      {!locationsLoading && !locationsError && locations.length === 0 && (
        <div className="inline-warning" role="alert">
          Нет доступной физической точки с привязкой к заведению. Операции с
          баллами и создание клиента временно недоступны.
        </div>
      )}
      {locations.length > 0 && (
        <Field label="Точка работы">
          <select
            aria-label="Активная физическая точка"
            value={selectedLocation?.id ?? ""}
            onChange={(event) => selectLocation(event.target.value)}
          >
            {locations.map((location) => (
              <option key={location.id} value={location.id}>
                {location.name} — {location.address}
              </option>
            ))}
          </select>
        </Field>
      )}
      {selectedLocation && (
        <p className="muted" role="status">
          Сейчас: <strong>{selectedLocation.name}</strong>,{" "}
          {selectedLocation.address}
        </p>
      )}
    </Panel>
  );
}

export function StaffHomePage() {
  const resource = useResource(coffeeApi.getRecentOperations);
  return (
    <Page title="Рабочий экран" eyebrow="Быстрая операция">
      <StaffLocationSelector />
      <Panel className="scanner-callout">
        <div className="scanner-callout__icon" aria-hidden="true">
          ▦
        </div>
        <div>
          <h2>Найдите карту клиента</h2>
          <p>Сканирование безопасно: само по себе оно не меняет баланс.</p>
        </div>
        <Link className="button button--primary" to="/staff/scan">
          Сканировать, ввести код или телефон
        </Link>
      </Panel>
      <section>
        <div className="section-heading">
          <h2>Последние операции</h2>
          <Link to="/staff/recent">Все</Link>
        </div>
        {resource.loading && <Loader />}
        {resource.error && (
          <ErrorState
            error={resource.error}
            onRetry={resource.reload}
            compact
          />
        )}
        {resource.data &&
          (resource.data.items.length ? (
            <div className="compact-list">
              {resource.data.items.slice(0, 4).map((item) => (
                <article key={item.id}>
                  <span className="compact-list__icon" aria-hidden="true">
                    {item.delta_points && item.delta_points < 0 ? "−" : "+"}
                  </span>
                  <div>
                    <strong>{item.description}</strong>
                    <small>{formatDateTime(item.created_at)}</small>
                  </div>
                  {item.delta_points != null && (
                    <b>
                      {item.delta_points > 0 ? "+" : ""}
                      {item.delta_points}
                    </b>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              title="Операций ещё нет"
              text="После первой подтверждённой операции она появится здесь."
            />
          ))}
      </section>
    </Page>
  );
}

export function ScannerPage() {
  const navigate = useNavigate();
  const { setClient, selectedLocation } = useStaffWorkspace();
  const [shortCode, setShortCode] = useState("");
  const [phone, setPhone] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newCustomerPhone, setNewCustomerPhone] = useState("");
  const [newCustomerName, setNewCustomerName] = useState("");
  const [creationKey, setCreationKey] = useState(createIdempotencyKey);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [cameraMessage, setCameraMessage] = useState<string | null>(null);
  const [reward, setReward] = useState<StaffRewardLookup | null>(null);
  const [rewardRedeemed, setRewardRedeemed] = useState(false);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => () => closeTelegramScanner(), []);

  useEffect(() => {
    setCreationKey(createIdempotencyKey());
  }, [selectedLocation?.venue_id]);

  const lookup = async (payload: StaffClientLookup) => {
    setLoading(true);
    setError(null);
    try {
      const found = await coffeeApi.lookupStaffClient(payload);
      setClient(found);
      navigate(`/staff/client/${encodeURIComponent(found.user_id)}`);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason : new Error("Не удалось найти карту"),
      );
    } finally {
      setLoading(false);
    }
  };

  const startScanner = () => {
    setCameraMessage(null);
    setError(null);
    const started = scanQrWithTelegram((value) => {
      if (value.startsWith("coffee-reward:v1:")) {
        setLoading(true);
        void coffeeApi
          .lookupStaffReward(value)
          .then((found) => {
            setReward(found);
            setRewardRedeemed(false);
          })
          .catch((reason: unknown) =>
            setError(
              reason instanceof Error
                ? reason
                : new Error("Награда не найдена"),
            ),
          )
          .finally(() => setLoading(false));
        return;
      }
      void lookup({ qr_token: value });
    });
    if (!started) {
      setCameraMessage(
        "Сканер Telegram недоступен в этом окружении. Введите короткий код вручную.",
      );
      codeInput.current?.focus();
    }
  };

  const submitCode = (event: FormEvent) => {
    event.preventDefault();
    const value = shortCode.trim().toUpperCase();
    if (value.length < 4) {
      setError(new Error("Введите не менее четырёх символов кода"));
      return;
    }
    void lookup({ short_code: value });
  };

  const submitPhone = (event: FormEvent) => {
    event.preventDefault();
    const value = phone.trim();
    if (value.length < 5) {
      setError(new Error("Введите корректный номер телефона"));
      return;
    }
    // The browser trims presentation whitespace only. Canonical phone
    // normalization and identity matching remain backend responsibilities.
    void lookup({ phone: value });
  };

  const rotateCreationKey = () => setCreationKey(createIdempotencyKey());
  const createPhoneCustomer = async (event: FormEvent) => {
    event.preventDefault();
    const value = newCustomerPhone.trim();
    if (value.length < 5) {
      setError(new Error("Введите корректный номер телефона нового клиента"));
      return;
    }
    if (!selectedLocation?.venue_id) {
      setError(new Error("Выберите физическую точку для welcome-баллов"));
      return;
    }
    setCreating(true);
    setError(null);
    try {
      // Phone, name and the trusted venue origin form one business request.
      // Its key stays stable on retry, but rotates when any of them changes.
      await coffeeApi.createPhoneCustomer(
        {
          phone: value,
          display_name: newCustomerName.trim() || null,
          venue_id: selectedLocation.venue_id,
        },
        creationKey,
      );
      const found = await coffeeApi.lookupStaffClient({ phone: value });
      setClient(found);
      navigate(`/staff/client/${encodeURIComponent(found.user_id)}`);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось создать клиента"),
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <Page title="Сканер карты" eyebrow="Поиск клиента">
      <StaffLocationSelector />
      {reward && (
        <Panel className="reward-highlight">
          <div>
            <Badge tone={rewardRedeemed ? "success" : "accent"}>
              {rewardRedeemed ? "Награда погашена" : "Награда клиента"}
            </Badge>
            <h2>{reward.reward_name}</h2>
            <p>{reward.description}</p>
            <p>
              Клиент: <strong>{reward.customer_name}</strong>
            </p>
            {reward.terms && <small>{reward.terms}</small>}
          </div>
          <div className="action-row">
            <Button
              variant="secondary"
              onClick={() => {
                setReward(null);
                setRewardRedeemed(false);
              }}
            >
              {rewardRedeemed ? "Сканировать следующий" : "Отмена"}
            </Button>
            {!rewardRedeemed && (
              <Button
                disabled={loading}
                onClick={() => {
                  setLoading(true);
                  setError(null);
                  void coffeeApi
                    .redeemReward(reward.reward_id)
                    .then(() => setRewardRedeemed(true))
                    .catch((reason: unknown) =>
                      setError(
                        reason instanceof Error
                          ? reason
                          : new Error("Не удалось погасить награду"),
                      ),
                    )
                    .finally(() => setLoading(false));
                }}
              >
                {loading ? "Погашаем…" : "Подтвердить выдачу"}
              </Button>
            )}
          </div>
        </Panel>
      )}
      <Panel className="scanner-panel">
        <div className="scanner-frame" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <b>▦</b>
        </div>
        <h2>Наведите камеру на QR-код</h2>
        <p>Сканер распознает карту клиента или QR купленной награды.</p>
        <Button onClick={startScanner} disabled={loading}>
          Открыть сканер Telegram
        </Button>
        {cameraMessage && (
          <div className="inline-warning" role="status">
            {cameraMessage}
          </div>
        )}
      </Panel>
      <div className="divider">
        <span>или</span>
      </div>
      <Panel>
        <form className="form" onSubmit={submitCode}>
          <Field
            label="Короткий код"
            hint="Код находится под QR-картой клиента"
          >
            <input
              ref={codeInput}
              value={shortCode}
              onChange={(event) =>
                setShortCode(event.target.value.toUpperCase())
              }
              placeholder="Например, C0FFEE42"
              autoComplete="off"
              inputMode="text"
              maxLength={16}
            />
          </Field>
          <Button type="submit" disabled={loading}>
            {loading ? "Ищем…" : "Найти клиента"}
          </Button>
        </form>
      </Panel>
      <Panel>
        <h2>Поиск по телефону</h2>
        <form className="form" onSubmit={submitPhone}>
          <Field
            label="Телефон клиента"
            hint="Можно вводить +7, 8 и привычные пробелы или скобки"
          >
            <input
              type="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+7 999 123-45-67"
              autoComplete="tel"
              inputMode="tel"
              maxLength={64}
            />
          </Field>
          <Button type="submit" disabled={loading || creating}>
            {loading ? "Ищем…" : "Найти по телефону"}
          </Button>
        </form>
        <div className="action-row">
          <Button
            type="button"
            variant="ghost"
            disabled={loading || creating}
            onClick={() => {
              setShowCreate((value) => !value);
              setError(null);
              if (!showCreate) setCreationKey(createIdempotencyKey());
            }}
          >
            {showCreate ? "Закрыть создание" : "Создать нового клиента"}
          </Button>
        </div>
      </Panel>
      {showCreate && (
        <Panel>
          <h2>Новый клиент без Telegram</h2>
          <p className="muted">
            Создадим профиль, карту и баланс. Telegram можно будет привязать
            позже после подтверждения телефона.
          </p>
          <form
            className="form"
            onSubmit={(event) => void createPhoneCustomer(event)}
          >
            <Field label="Телефон нового клиента">
              <input
                type="tel"
                value={newCustomerPhone}
                onChange={(event) => {
                  setNewCustomerPhone(event.target.value);
                  rotateCreationKey();
                }}
                placeholder="+7 999 123-45-67"
                autoComplete="tel"
                inputMode="tel"
                maxLength={64}
                required
              />
            </Field>
            <Field label="Имя" hint="Необязательно — по умолчанию «Гость»">
              <input
                value={newCustomerName}
                onChange={(event) => {
                  setNewCustomerName(event.target.value);
                  rotateCreationKey();
                }}
                maxLength={128}
                autoComplete="name"
                placeholder="Например, Мария"
              />
            </Field>
            <Button
              type="submit"
              disabled={creating || loading || !selectedLocation?.venue_id}
            >
              {creating ? "Создаём…" : "Создать карту"}
            </Button>
          </form>
        </Panel>
      )}
      {loading && <Loader label="Проверяем карту…" />}
      {creating && <Loader label="Создаём карту клиента…" />}
      {error && <ErrorState error={error} compact />}
      <div className="notice">
        <span aria-hidden="true">i</span>
        <p>
          Неизвестный и перевыпущенный QR возвращают одинаковую нейтральную
          ошибку и не раскрывают данные клиента.
        </p>
      </div>
    </Page>
  );
}

export function ClientPreviewPage() {
  const navigate = useNavigate();
  const { client, setClient, selectedLocation } = useStaffWorkspace();
  if (!client)
    return (
      <Page title="Карточка клиента">
        <EmptyState
          title="Клиент не выбран"
          text="Сначала отсканируйте QR или найдите карту по коду или телефону."
          action={
            <Link className="button button--primary" to="/staff/scan">
              Перейти к сканеру
            </Link>
          }
        />
      </Page>
    );
  const refreshClient = async () => {
    setClient(
      await coffeeApi.lookupStaffClient({ short_code: client.short_code }),
    );
  };
  return (
    <Page
      title={client.display_name}
      eyebrow="Карточка клиента"
      action={
        <Badge tone={client.blocked ? "danger" : "success"}>
          {client.blocked ? "Заблокирована" : "Активна"}
        </Badge>
      }
    >
      <StaffLocationSelector />
      <ReceiptQuickForm
        userId={client.user_id}
        venueId={selectedLocation?.venue_id ?? null}
      />
      <Panel className="client-summary">
        <Avatar
          name={client.display_name}
          src={client.photo_url}
          size="large"
        />
        <div>
          <h2>{client.display_name}</h2>
          <p className="muted">Код {client.masked_short_code}</p>
        </div>
        <strong className="client-summary__balance">
          {client.balance_points}
          <small>{client.currency_name}</small>
        </strong>
      </Panel>
      {client.suspicious && (
        <div className="inline-warning">
          На карте отмечена необычная активность. Проверьте данные до
          подтверждения.
        </div>
      )}
      {client.blocked ? (
        <ErrorState
          error={new Error("Операции с заблокированной картой недоступны")}
        />
      ) : (
        <AccrualPanel
          client={client}
          location={selectedLocation}
          onCompleted={() => void refreshClient()}
          onNewPurchase={() => {
            setClient(null);
            navigate("/staff/scan");
          }}
        />
      )}
      <div className="metrics-grid">
        <Metric
          value={`${client.visit_streak}/${client.visit_goal}`}
          label="визитов"
        />
        <Metric
          value={`${client.stamps}/${client.stamp_goal}`}
          label="штампов"
        />
        <Metric
          value={client.available_rewards.length}
          label="наград"
          tone="accent"
        />
      </div>
      <QuickOperationsPanel
        client={client}
        location={selectedLocation}
        onCompleted={() => void refreshClient()}
      />
      <Panel>
        <div className="section-heading">
          <h2>Последние операции</h2>
        </div>
        {client.recent_operations.length ? (
          <div className="compact-list">
            {client.recent_operations.map((item) => (
              <article key={item.id}>
                <span className="compact-list__icon">
                  {item.delta_points && item.delta_points < 0 ? "−" : "+"}
                </span>
                <div>
                  <strong>{item.description}</strong>
                  <small>{formatDateTime(item.created_at)}</small>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="muted">Операций пока нет.</p>
        )}
      </Panel>
    </Page>
  );
}

export function QuickOperationsPanel({
  client,
  location,
  onCompleted,
}: {
  client: StaffClient;
  location: ContactLocation | null;
  onCompleted: (operation: OperationResult) => void;
}) {
  const [mode, setMode] = useState<"redemption" | "rewards" | null>(null);
  const [amount, setAmount] = useState("");
  const [points, setPoints] = useState("");
  const [redemption, setRedemption] = useState<RedemptionPreview | null>(null);
  const [redemptionLocationName, setRedemptionLocationName] = useState("");
  const [rewardId, setRewardId] = useState<string | null>(null);
  const [result, setResult] = useState<OperationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete = (operation: OperationResult) => {
    setResult(operation);
    onCompleted(operation);
  };
  const previewRedemption = async (event: FormEvent) => {
    event.preventDefault();
    const purchaseAmount = rublesToMinor(amount);
    const requestedPoints = Number(points);
    if (
      purchaseAmount == null ||
      !Number.isInteger(requestedPoints) ||
      requestedPoints <= 0
    ) {
      setError("Укажите сумму покупки и целое количество баллов");
      return;
    }
    if (!location) {
      setError("Выберите активную физическую точку");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const preview = await coffeeApi.previewRedemption({
        user_id: client.user_id,
        purchase_amount_minor: purchaseAmount,
        requested_points: requestedPoints,
        location_id: location.id,
      });
      setRedemption({ ...preview, customer_name: client.display_name });
      setRedemptionLocationName(location.name);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось рассчитать списание",
      );
    } finally {
      setLoading(false);
    }
  };
  const confirmRedemption = async () => {
    if (!redemption) return;
    setLoading(true);
    setError(null);
    try {
      complete(
        await coffeeApi.confirmRedemption({
          user_id: client.user_id,
          purchase_amount_minor: redemption.purchase_amount_minor,
          requested_points: redemption.requested_points,
          location_id: redemption.location_id,
        }),
      );
      setRedemption(null);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось списать баллы",
      );
    } finally {
      setLoading(false);
    }
  };
  const redeemReward = async () => {
    if (!rewardId) return;
    setLoading(true);
    setError(null);
    try {
      complete(await coffeeApi.redeemReward(rewardId));
      setRewardId(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось погасить награду",
      );
    } finally {
      setLoading(false);
    }
  };
  const reset = () => {
    setMode(null);
    setAmount("");
    setPoints("");
    setRedemption(null);
    setRedemptionLocationName("");
    setRewardId(null);
    setResult(null);
    setError(null);
  };

  return (
    <Panel className="operation-panel">
      <h2>Списание и награды</h2>
      {result ? (
        <div className="operation-success" role="status">
          <span>✓</span>
          <h3>Операция выполнена</h3>
          <p>{result.audit_message || "Изменения записаны в журнал."}</p>
          <Button variant="secondary" onClick={reset}>
            Готово
          </Button>
        </div>
      ) : mode === null ? (
        <div className="action-grid">
          <button type="button" onClick={() => setMode("redemption")}>
            <span aria-hidden="true">−</span>Списать
          </button>
          <button type="button" onClick={() => setMode("rewards")}>
            <span aria-hidden="true">◇</span>Погасить награду
          </button>
        </div>
      ) : mode === "redemption" ? (
        redemption ? (
          <div className="confirm-card" aria-label="Предпросмотр списания">
            <h3>Проверьте списание</h3>
            <dl>
              <div>
                <dt>Покупка</dt>
                <dd>{formatMoney(redemption.purchase_amount_minor)}</dd>
              </div>
              <div>
                <dt>Баллов</dt>
                <dd className="negative">−{redemption.requested_points}</dd>
              </div>
              <div>
                <dt>Скидка</dt>
                <dd>{formatMoney(redemption.discount_minor)}</dd>
              </div>
              <div>
                <dt>Физическая точка</dt>
                <dd>{redemptionLocationName}</dd>
              </div>
              <div className="confirm-card__total">
                <dt>Новый баланс</dt>
                <dd>{redemption.balance_after}</dd>
              </div>
            </dl>
            <div className="action-row">
              <Button
                variant="secondary"
                onClick={() => setRedemption(null)}
                disabled={loading}
              >
                Изменить
              </Button>
              <Button
                onClick={() => void confirmRedemption()}
                disabled={loading}
              >
                {loading ? "Списываем…" : "Подтвердить списание"}
              </Button>
            </div>
          </div>
        ) : (
          <form
            className="form"
            onSubmit={(event) => void previewRedemption(event)}
          >
            <h3>Списать баллы</h3>
            <Field label="Сумма покупки, ₽">
              <input
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                inputMode="decimal"
              />
            </Field>
            <Field
              label="Сколько баллов списать"
              hint={`Доступно: ${client.balance_points}`}
            >
              <input
                value={points}
                onChange={(event) => setPoints(event.target.value)}
                inputMode="numeric"
              />
            </Field>
            <div className="action-row">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setMode(null)}
              >
                Отмена
              </Button>
              <Button type="submit" disabled={loading || !location}>
                {loading ? "Рассчитываем…" : "Рассчитать"}
              </Button>
            </div>
          </form>
        )
      ) : (
        <div>
          <h3>Активные награды</h3>
          {client.available_rewards.length ? (
            <div className="reward-action-list">
              {client.available_rewards.map((reward) => (
                <label key={reward.id} className="reward-action-list__item">
                  <input
                    type="radio"
                    name="reward"
                    checked={rewardId === reward.id}
                    onChange={() => setRewardId(reward.id)}
                  />
                  <span>
                    <strong>{reward.title}</strong>
                    <small>{reward.description}</small>
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <p className="muted">У клиента нет активных наград.</p>
          )}
          <div className="action-row">
            <Button variant="secondary" onClick={() => setMode(null)}>
              Назад
            </Button>
            <Button
              onClick={() => void redeemReward()}
              disabled={!rewardId || loading}
            >
              {loading ? "Погашаем…" : "Подтвердить погашение"}
            </Button>
          </div>
        </div>
      )}
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
    </Panel>
  );
}

export function AccrualPanel({
  client,
  location,
  onCompleted,
  onNewPurchase,
}: {
  client: StaffClient;
  location: ContactLocation | null;
  onCompleted?: (operation: OperationResult) => void;
  onNewPurchase?: () => void;
}) {
  const [amount, setAmount] = useState("");
  const [stamps, setStamps] = useState("1");
  const [preview, setPreview] = useState<PurchasePreview | null>(null);
  const [previewLocationName, setPreviewLocationName] = useState("");
  const [result, setResult] = useState<OperationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const purchaseMinor = rublesToMinor(amount);
  const makePreview = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    const stampsToAdd = Number(stamps);
    if (
      purchaseMinor == null ||
      !Number.isInteger(stampsToAdd) ||
      stampsToAdd < 0 ||
      stampsToAdd > 100
    ) {
      setError("Введите сумму и целое количество штампов от 0 до 100");
      return;
    }
    if (!location) {
      setError("Выберите активную физическую точку");
      return;
    }
    setLoading(true);
    try {
      const next = await coffeeApi.previewPurchase({
        user_id: client.user_id,
        purchase_amount_minor: purchaseMinor,
        stamps_to_add: stampsToAdd,
        location_id: location.id,
      });
      setPreview({ ...next, customer_name: client.display_name });
      setPreviewLocationName(location.name);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось рассчитать покупку",
      );
    } finally {
      setLoading(false);
    }
  };

  const confirm = async () => {
    if (!preview) return;
    setLoading(true);
    setError(null);
    try {
      const operation = await coffeeApi.confirmPurchase({
        user_id: client.user_id,
        purchase_amount_minor: preview.purchase_amount_minor,
        stamps_to_add: preview.stamps_to_add,
        location_id: preview.location_id,
      });
      setResult(operation);
      onCompleted?.(operation);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось засчитать покупку",
      );
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setAmount("");
    setStamps("1");
    setPreview(null);
    setPreviewLocationName("");
    setResult(null);
    setError(null);
  };

  return (
    <Panel className="operation-panel">
      <div className="section-heading">
        <h2>Засчитать покупку</h2>
        <Badge tone="accent">Автоматически</Badge>
      </div>
      {result ? (
        <div className="operation-success" role="status">
          <span aria-hidden="true">✓</span>
          <h3>
            {result.status === "pending"
              ? "Отправлено на подтверждение"
              : "Покупка засчитана"}
          </h3>
          <strong>+{result.delta_points} баллов</strong>
          {result.status === "pending" ? (
            <p>Баллы, штампы и посещение не изменятся до одобрения.</p>
          ) : (
            <>
              <p>
                Баланс: {result.balance_after ?? client.balance_points}. Штампы:{" "}
                {result.stamps_after ?? preview?.stamps_after ?? client.stamps}.
              </p>
              <p>
                {result.streak_after != null
                  ? `Посещение учтено автоматически. Серия: ${result.streak_after}.`
                  : preview?.visit_already_counted
                    ? "Посещение за этот бизнес-день уже было учтено."
                    : "Дополнительное посещение не требовалось."}
              </p>
            </>
          )}
          <Button
            variant="secondary"
            onClick={() => (onNewPurchase ? onNewPurchase() : reset())}
          >
            Новая покупка
          </Button>
        </div>
      ) : preview ? (
        <div className="confirm-card" aria-label="Предпросмотр покупки">
          <h3>Проверьте покупку</h3>
          <dl>
            <div>
              <dt>Клиент</dt>
              <dd>{preview.customer_name}</dd>
            </div>
            <div>
              <dt>Сумма покупки</dt>
              <dd>{formatMoney(preview.purchase_amount_minor)}</dd>
            </div>
            <div>
              <dt>Физическая точка</dt>
              <dd>{previewLocationName}</dd>
            </div>
            <div>
              <dt>Баллы</dt>
              <dd className="positive">+{preview.points_to_accrue}</dd>
            </div>
            {preview.reward_bonus_points > 0 && (
              <div>
                <dt>Бонус за награду</dt>
                <dd className="positive">+{preview.reward_bonus_points}</dd>
              </div>
            )}
            <div>
              <dt>Штампы</dt>
              <dd>
                +{preview.stamps_to_add} ({preview.stamps_before} →{" "}
                {preview.stamps_after})
              </dd>
            </div>
            <div>
              <dt>Посещение</dt>
              <dd>
                {preview.visit_will_be_recorded
                  ? `Учтётся автоматически · серия ${preview.visit_streak_after}`
                  : preview.visit_already_counted
                    ? "Уже учтено сегодня"
                    : "Не добавляется"}
              </dd>
            </div>
            <div className="confirm-card__total">
              <dt>Баланс после покупки</dt>
              <dd>{preview.balance_after}</dd>
            </div>
          </dl>
          {preview.stamp_rewards_earned > 0 && (
            <div className="inline-warning">
              Завершено циклов штампов: {preview.stamp_rewards_earned}.
            </div>
          )}
          {preview.requires_approval && (
            <div className="inline-warning">
              Крупная операция будет отправлена администратору.
            </div>
          )}
          <div className="action-row">
            <Button
              variant="secondary"
              onClick={() => setPreview(null)}
              disabled={loading}
            >
              Изменить
            </Button>
            <Button onClick={() => void confirm()} disabled={loading}>
              {loading ? "Подтверждаем…" : "Подтвердить покупку"}
            </Button>
          </div>
        </div>
      ) : (
        <form className="form" onSubmit={(event) => void makePreview(event)}>
          <Field label="Сумма покупки, ₽" hint="Баллы рассчитает система">
            <input
              type="text"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              placeholder="460"
              autoComplete="off"
            />
          </Field>
          <Field
            label="Штампы за покупку"
            hint="Поставьте 0, если штамп не положен"
            error={error ?? undefined}
          >
            <input
              type="number"
              min="0"
              max="100"
              step="1"
              value={stamps}
              onChange={(event) => setStamps(event.target.value)}
              inputMode="numeric"
              autoComplete="off"
            />
          </Field>
          <p className="muted">
            Посещение добавится само, если оно ещё не учитывалось в текущем
            бизнес-дне.
          </p>
          <Button type="submit" disabled={loading || !location}>
            {loading ? "Рассчитываем…" : "Рассчитать"}
          </Button>
        </form>
      )}
      {preview && error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
    </Panel>
  );
}

export function RecentOperationsPage() {
  const resource = useResource(coffeeApi.getRecentOperations);
  const [reversingId, setReversingId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reverse = async () => {
    if (!reversingId || reason.trim().length < 3) {
      setError("Укажите понятную причину отмены");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await coffeeApi.reverseOperation(reversingId, reason.trim());
      setReversingId(null);
      setReason("");
      await resource.reload();
    } catch (reasonValue) {
      setError(
        reasonValue instanceof Error
          ? reasonValue.message
          : "Не удалось отменить операцию",
      );
    } finally {
      setLoading(false);
    }
  };
  return (
    <Page title="Мои операции" eyebrow="Последние действия">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="timeline">
            {resource.data.items.map((item) => (
              <article className="timeline-item" key={item.id}>
                <span className="timeline-item__mark">
                  {item.delta_points && item.delta_points < 0 ? "−" : "+"}
                </span>
                <div>
                  <h2>{item.description}</h2>
                  <p>{formatDateTime(item.created_at)}</p>
                </div>
                {item.delta_points != null && (
                  <strong>
                    {item.delta_points > 0 ? "+" : ""}
                    {item.delta_points}
                  </strong>
                )}
                {item.status === "completed" &&
                  item.type !== "operation_reversal" && (
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setReversingId(item.id);
                        setReason("");
                        setError(null);
                      }}
                    >
                      Отменить
                    </Button>
                  )}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Операций пока нет"
            text="Здесь появятся только доступные вашей роли операции."
          />
        ))}
      {reversingId && (
        <Panel>
          <h2>Отмена операции</h2>
          <p className="muted">
            Будет создана компенсирующая операция. Исходная запись сохранится.
          </p>
          <Field label="Причина отмены">
            <textarea
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
          {error && <div className="inline-error">{error}</div>}
          <div className="action-row">
            <Button variant="secondary" onClick={() => setReversingId(null)}>
              Назад
            </Button>
            <Button
              variant="danger"
              onClick={() => void reverse()}
              disabled={loading}
            >
              {loading ? "Отменяем…" : "Подтвердить отмену"}
            </Button>
          </div>
        </Panel>
      )}
    </Page>
  );
}

export function StaffProfilePage() {
  const resource = useResource(coffeeApi.getTipProfile);
  const [form, setForm] = useState<TipProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  useEffect(() => {
    if (resource.data) setForm(resource.data);
  }, [resource.data]);
  const update = (key: keyof TipProfile, value: string) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      setForm(await coffeeApi.saveTipProfile(form));
      setSaved(true);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить профиль",
      );
    } finally {
      setSaving(false);
    }
  };
  const upload = async (file: File, kind: "staff_profile" | "tip_qr") => {
    setUploading(true);
    setError(null);
    try {
      const media = await coffeeApi.uploadStaffMedia(file, kind);
      setForm((current) =>
        current
          ? {
              ...current,
              ...(kind === "staff_profile"
                ? { photo_media_id: media.id, photo_url: media.url }
                : { tip_qr_media_id: media.id, tip_qr_url: media.url }),
            }
          : current,
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось загрузить фото",
      );
    } finally {
      setUploading(false);
    }
  };
  const moderationLabel: Record<TipProfile["moderation_status"], string> = {
    draft: "Черновик",
    pending_review: "На модерации",
    approved: "Опубликован",
    hidden: "Скрыт администратором",
  };
  return (
    <Page title="Мой профиль" eyebrow="Публичная карточка и чаевые">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {form && (
        <Panel>
          <div className="profile-heading">
            <Avatar
              name={form.display_name}
              src={form.photo_url}
              size="large"
            />
            <div>
              <h2>{form.display_name}</h2>
              <Badge
                tone={
                  form.moderation_status === "approved" ? "success" : "warning"
                }
              >
                {moderationLabel[form.moderation_status]}
              </Badge>
            </div>
          </div>
          {saved && (
            <div className="inline-success" role="status">
              Изменения отправлены на модерацию. Опубликованная версия останется
              видимой до одобрения.
            </div>
          )}
          <form className="form" onSubmit={(event) => void save(event)}>
            <Field
              label="Аватар"
              hint="Лучше всего 800×800 px (1:1). JPG, PNG или WebP, до 5 МБ"
            >
              <input
                type="file"
                accept={MEDIA_FILE_ACCEPT}
                disabled={uploading}
                onChange={(event) => {
                  const input = event.currentTarget;
                  const file = input.files?.[0];
                  input.value = "";
                  if (file) void upload(file, "staff_profile");
                }}
              />
            </Field>
            <Field label="Имя">
              <input
                value={form.display_name}
                onChange={(event) => update("display_name", event.target.value)}
                required
              />
            </Field>
            <Field label="Должность">
              <input
                value={form.position}
                onChange={(event) => update("position", event.target.value)}
                required
              />
            </Field>
            <Field label="О себе">
              <textarea
                rows={3}
                value={form.bio}
                onChange={(event) => update("bio", event.target.value)}
                maxLength={300}
              />
            </Field>
            <Field
              label="Ссылка для чаевых"
              hint="Перевод выполняется через сторонний сервис"
            >
              <input
                type="url"
                value={form.tip_url}
                onChange={(event) => update("tip_url", event.target.value)}
                placeholder="https://"
              />
            </Field>
            <Field
              label="QR для чаевых"
              hint="Лучше всего 1000×1000 px (1:1), с белым полем и без обрезки. JPG, PNG или WebP, до 5 МБ"
            >
              <input
                type="file"
                accept={MEDIA_FILE_ACCEPT}
                disabled={uploading}
                onChange={(event) => {
                  const input = event.currentTarget;
                  const file = input.files?.[0];
                  input.value = "";
                  if (file) void upload(file, "tip_qr");
                }}
              />
            </Field>
            {error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
            <div className="action-row">
              <Button type="submit" disabled={saving || uploading}>
                {saving ? "Сохраняем…" : "Сохранить изменения"}
              </Button>
              {form.moderation_status === "pending_review" && (
                <Button
                  type="button"
                  variant="secondary"
                  disabled={saving}
                  onClick={() => {
                    setSaving(true);
                    setError(null);
                    void coffeeApi
                      .cancelTipProfileReview()
                      .then(setForm)
                      .catch((reason: unknown) =>
                        setError(
                          reason instanceof Error
                            ? reason.message
                            : "Не удалось отменить модерацию",
                        ),
                      )
                      .finally(() => setSaving(false));
                  }}
                >
                  Отменить модерацию
                </Button>
              )}
            </div>
          </form>
        </Panel>
      )}
    </Page>
  );
}

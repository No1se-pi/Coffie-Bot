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
import { coffeeApi } from "../api/client";
import type {
  AccrualPreview,
  OperationResult,
  StaffClient,
  TipProfile,
} from "../api/types";
import { useResource } from "../hooks/useResource";
import { closeTelegramScanner, scanQrWithTelegram } from "../telegram";
import { formatDateTime, formatMoney, rublesToMinor } from "../utils/format";
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
}

const StaffWorkspaceContext = createContext<StaffWorkspaceValue | null>(null);

export function StaffWorkspaceProvider({ children }: { children: ReactNode }) {
  const [client, setClient] = useState<StaffClient | null>(null);
  return (
    <StaffWorkspaceContext.Provider value={{ client, setClient }}>
      {children}
    </StaffWorkspaceContext.Provider>
  );
}

function useStaffWorkspace() {
  const value = useContext(StaffWorkspaceContext);
  if (!value) throw new Error("Staff pages require StaffWorkspaceProvider");
  return value;
}

export function StaffHomePage() {
  const resource = useResource(coffeeApi.getRecentOperations);
  return (
    <Page title="Рабочий экран" eyebrow="Быстрая операция">
      <Panel className="scanner-callout">
        <div className="scanner-callout__icon" aria-hidden="true">
          ▦
        </div>
        <div>
          <h2>Найдите карту клиента</h2>
          <p>Сканирование безопасно: само по себе оно не меняет баланс.</p>
        </div>
        <Link className="button button--primary" to="/staff/scan">
          Сканировать или ввести код
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
  const { setClient } = useStaffWorkspace();
  const [shortCode, setShortCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [cameraMessage, setCameraMessage] = useState<string | null>(null);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => () => closeTelegramScanner(), []);

  const lookup = async (payload: {
    qr_token?: string;
    short_code?: string;
  }) => {
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
    const started = scanQrWithTelegram(
      (value) => void lookup({ qr_token: value }),
    );
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

  return (
    <Page title="Сканер карты" eyebrow="Поиск клиента">
      <Panel className="scanner-panel">
        <div className="scanner-frame" aria-hidden="true">
          <span />
          <span />
          <span />
          <span />
          <b>▦</b>
        </div>
        <h2>Наведите камеру на QR-код</h2>
        <p>
          После сканирования вы увидите карточку клиента и выберете действие.
        </p>
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
      {loading && <Loader label="Проверяем карту…" />}
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
  const { client } = useStaffWorkspace();
  if (!client)
    return (
      <Page title="Карточка клиента">
        <EmptyState
          title="Клиент не выбран"
          text="Сначала отсканируйте QR или найдите карту по короткому коду."
          action={
            <Link className="button button--primary" to="/staff/scan">
              Перейти к сканеру
            </Link>
          }
        />
      </Page>
    );
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
        <AccrualPanel client={client} />
      )}
      <div className="metrics-grid">
        <Metric value={client.visit_streak} label="визита подряд" />
        <Metric value={client.stamps} label="штампов" />
        <Metric
          value={client.available_rewards.length}
          label="наград"
          tone="accent"
        />
      </div>
      <Panel>
        <h2>Другие действия</h2>
        <div className="action-grid">
          <button type="button">
            <span>✓</span>Посещение
          </button>
          <button type="button">
            <span>●</span>Штамп
          </button>
          <button type="button">
            <span>−</span>Списать
          </button>
          <button type="button">
            <span>◇</span>Погасить награду
          </button>
        </div>
        <p className="muted">
          Действия будут доступны после подключения соответствующих confirm
          endpoints.
        </p>
      </Panel>
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

export function AccrualPanel({ client }: { client: StaffClient }) {
  const [amount, setAmount] = useState("");
  const [preview, setPreview] = useState<AccrualPreview | null>(null);
  const [result, setResult] = useState<OperationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const purchaseMinor = rublesToMinor(amount);
  const makePreview = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (purchaseMinor == null) {
      setError("Введите корректную сумму больше нуля");
      return;
    }
    setLoading(true);
    try {
      setPreview(
        await coffeeApi.previewAccrual({
          user_id: client.user_id,
          purchase_amount_minor: purchaseMinor,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось рассчитать начисление",
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
      const operation = await coffeeApi.confirmAccrual({
        user_id: client.user_id,
        purchase_amount_minor: preview.purchase_amount_minor,
      });
      setResult(operation);
      setPreview(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось выполнить начисление",
      );
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setAmount("");
    setPreview(null);
    setResult(null);
    setError(null);
  };

  return (
    <Panel className="operation-panel">
      <div className="section-heading">
        <h2>Начислить за покупку</h2>
        <Badge tone="accent">Backend расчёт</Badge>
      </div>
      {result ? (
        <div className="operation-success" role="status">
          <span aria-hidden="true">✓</span>
          <h3>
            {result.status === "pending"
              ? "Отправлено на подтверждение"
              : "Баллы начислены"}
          </h3>
          <strong>+{result.delta_points}</strong>
          <p>Новый баланс: {result.balance_after}</p>
          <Button variant="secondary" onClick={reset}>
            Новая операция
          </Button>
        </div>
      ) : preview ? (
        <div className="confirm-card" aria-label="Предпросмотр начисления">
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
              <dt>Начисление</dt>
              <dd className="positive">+{preview.points_to_accrue}</dd>
            </div>
            <div>
              <dt>Текущий баланс</dt>
              <dd>{preview.balance_before}</dd>
            </div>
            <div className="confirm-card__total">
              <dt>Новый баланс</dt>
              <dd>{preview.balance_after}</dd>
            </div>
          </dl>
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
              {loading ? "Подтверждаем…" : "Подтвердить начисление"}
            </Button>
          </div>
        </div>
      ) : (
        <form className="form" onSubmit={(event) => void makePreview(event)}>
          <Field
            label="Сумма покупки, ₽"
            hint="Количество баллов рассчитает backend"
            error={error ?? undefined}
          >
            <input
              type="text"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              placeholder="460"
              autoComplete="off"
            />
          </Field>
          <Button type="submit" disabled={loading}>
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
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Операций пока нет"
            text="Здесь появятся только доступные вашей роли операции."
          />
        ))}
    </Page>
  );
}

export function StaffProfilePage() {
  const resource = useResource(coffeeApi.getTipProfile);
  const [form, setForm] = useState<TipProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
  return (
    <Page title="Мой профиль" eyebrow="Публичная карточка и чаевые">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {form && (
        <Panel>
          <div className="profile-heading">
            <Avatar name={form.display_name} size="large" />
            <div>
              <h2>{form.display_name}</h2>
              <Badge
                tone={
                  form.moderation_status === "approved" ? "success" : "warning"
                }
              >
                {form.moderation_status === "approved"
                  ? "Опубликован"
                  : "На модерации"}
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
            {error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
            <Button type="submit" disabled={saving}>
              {saving ? "Сохраняем…" : "Сохранить изменения"}
            </Button>
          </form>
        </Panel>
      )}
    </Page>
  );
}

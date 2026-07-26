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
  RedemptionPreview,
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
  const { client, setClient } = useStaffWorkspace();
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
          onCompleted={() => void refreshClient()}
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
  onCompleted,
}: {
  client: StaffClient;
  onCompleted: (operation: OperationResult) => void;
}) {
  const [mode, setMode] = useState<
    "visit" | "stamp" | "redemption" | "rewards" | null
  >(null);
  const [amount, setAmount] = useState("");
  const [points, setPoints] = useState("");
  const [redemption, setRedemption] = useState<RedemptionPreview | null>(null);
  const [rewardId, setRewardId] = useState<string | null>(null);
  const [result, setResult] = useState<OperationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const complete = (operation: OperationResult) => {
    setResult(operation);
    onCompleted(operation);
  };
  const runSimple = async (kind: "visit" | "stamp") => {
    setLoading(true);
    setError(null);
    try {
      complete(
        kind === "visit"
          ? await coffeeApi.markVisit(client.user_id)
          : await coffeeApi.addStamp(client.user_id),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось выполнить операцию",
      );
    } finally {
      setLoading(false);
    }
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
    setLoading(true);
    setError(null);
    try {
      const preview = await coffeeApi.previewRedemption({
        user_id: client.user_id,
        purchase_amount_minor: purchaseAmount,
        requested_points: requestedPoints,
      });
      setRedemption({ ...preview, customer_name: client.display_name });
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
    setRewardId(null);
    setResult(null);
    setError(null);
  };

  return (
    <Panel className="operation-panel">
      <h2>Другие действия</h2>
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
          <button type="button" onClick={() => setMode("visit")}>
            <span aria-hidden="true">✓</span>Посещение
          </button>
          <button type="button" onClick={() => setMode("stamp")}>
            <span aria-hidden="true">●</span>Штамп
          </button>
          <button type="button" onClick={() => setMode("redemption")}>
            <span aria-hidden="true">−</span>Списать
          </button>
          <button type="button" onClick={() => setMode("rewards")}>
            <span aria-hidden="true">◇</span>Погасить награду
          </button>
        </div>
      ) : mode === "visit" || mode === "stamp" ? (
        <div className="confirm-card">
          <h3>
            {mode === "visit" ? "Отметить посещение?" : "Добавить один штамп?"}
          </h3>
          <p>Клиент: {client.display_name}. Действие будет записано в аудит.</p>
          <div className="action-row">
            <Button
              variant="secondary"
              onClick={() => setMode(null)}
              disabled={loading}
            >
              Отмена
            </Button>
            <Button onClick={() => void runSimple(mode)} disabled={loading}>
              {loading ? "Подтверждаем…" : "Подтвердить"}
            </Button>
          </div>
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
              <Button type="submit" disabled={loading}>
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
  onCompleted,
}: {
  client: StaffClient;
  onCompleted?: (operation: OperationResult) => void;
}) {
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
      const next = await coffeeApi.previewAccrual({
        user_id: client.user_id,
        purchase_amount_minor: purchaseMinor,
      });
      setPreview({ ...next, customer_name: client.display_name });
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
      onCompleted?.(operation);
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
          <p>Новый баланс: {result.balance_after ?? client.balance_points}</p>
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

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { coffeeApi } from "../api/client";
import type { AdjustmentPreview, LoyaltySettings } from "../api/types";
import { useResource } from "../hooks/useResource";
import { formatDateTime, formatMoney } from "../utils/format";
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

export function AdminOverviewPage() {
  const resource = useResource(coffeeApi.getAdminOverview);
  return (
    <Page title="Обзор" eyebrow="Состояние программы">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <div className="metrics-grid metrics-grid--admin">
            <Metric value={resource.data.users_total} label="клиентов" />
            <Metric
              value={resource.data.active_promotions}
              label="активных акций"
              tone="accent"
            />
            <Metric value={resource.data.blocked_users} label="блокировок" />
            <Metric
              value={resource.data.suspicious_events}
              label="требуют внимания"
              tone="warning"
            />
          </div>
          <div className="admin-shortcuts">
            <Link to="/admin/users">
              <span>○</span>
              <strong>Пользователи</strong>
              <small>Поиск и корректировки</small>
            </Link>
            <Link to="/admin/events">
              <span>↻</span>
              <strong>События</strong>
              <small>Аудит действий</small>
            </Link>
            <Link to="/admin/settings">
              <span>⚙</span>
              <strong>Программы</strong>
              <small>Правила лояльности</small>
            </Link>
            <Link to="/admin/menu">
              <span>☕</span>
              <strong>Контент</strong>
              <small>Меню и акции</small>
            </Link>
          </div>
          <Panel>
            <div className="section-heading">
              <h2>Последние события</h2>
              <Link to="/admin/events">Все события</Link>
            </div>
            {resource.data.recent_events.length ? (
              <div className="event-list">
                {resource.data.recent_events.map((event) => (
                  <article
                    key={event.id}
                    className={event.suspicious ? "is-suspicious" : ""}
                  >
                    <span
                      className={`event-dot event-dot--${event.severity}`}
                    />
                    <div>
                      <p>{event.message}</p>
                      <small>{formatDateTime(event.created_at)}</small>
                    </div>
                    {event.suspicious && (
                      <Badge tone="warning">Проверить</Badge>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted">Событий пока нет.</p>
            )}
          </Panel>
        </>
      )}
    </Page>
  );
}

export function AdminUsersPage() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const resource = useResource(
    () => coffeeApi.getAdminUsers(query, status),
    [query, status],
  );
  const search = (event: FormEvent) => {
    event.preventDefault();
    setQuery(input.trim());
  };
  return (
    <Page title="Пользователи" eyebrow="Поиск и управление">
      <Panel>
        <form className="search-form" onSubmit={search}>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Имя, username, Telegram ID или код"
            aria-label="Поиск пользователей"
          />
          <Button type="submit">Найти</Button>
        </form>
        <div className="chip-row">
          <button
            className={`chip ${status === "" ? "is-active" : ""}`}
            onClick={() => setStatus("")}
          >
            Все
          </button>
          <button
            className={`chip ${status === "active" ? "is-active" : ""}`}
            onClick={() => setStatus("active")}
          >
            Активные
          </button>
          <button
            className={`chip ${status === "blocked" ? "is-active" : ""}`}
            onClick={() => setStatus("blocked")}
          >
            Заблокированные
          </button>
        </div>
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="user-list">
            {resource.data.items.map((user) => (
              <article key={user.id}>
                <Avatar name={user.display_name} />
                <div className="user-list__identity">
                  <h2>{user.display_name}</h2>
                  <p>
                    {user.username
                      ? `@${user.username}`
                      : `Telegram ${user.telegram_id}`}
                  </p>
                  <small>Код {user.short_code}</small>
                </div>
                <div className="user-list__numbers">
                  <strong>{user.balance_points}</strong>
                  <small>баллов</small>
                  <Badge tone={user.status === "active" ? "success" : "danger"}>
                    {user.status === "active" ? "Активен" : "Заблокирован"}
                  </Badge>
                </div>
                <Link
                  className="button button--secondary"
                  to={`/admin/users/${encodeURIComponent(user.id)}/adjust`}
                >
                  Корректировать
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Никого не нашли"
            text="Проверьте запрос или измените фильтр статуса."
          />
        ))}
    </Page>
  );
}

export function AdminAdjustmentPage() {
  const { userId = "" } = useParams();
  const resource = useResource(() => coffeeApi.getAdminUser(userId), [userId]);
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<AdjustmentPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    balance_after: number;
    delta_points: number;
  } | null>(null);

  const makePreview = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    const value = Number(delta);
    if (!Number.isInteger(value) || value === 0) {
      setError("Введите целое количество баллов со знаком");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Укажите понятную причину корректировки");
      return;
    }
    if (!resource.data) return;
    const next = coffeeApi.previewAdjustment(
      resource.data,
      value,
      reason.trim(),
    );
    if (next.balance_after < 0) {
      setError("Итоговый баланс не может быть отрицательным");
      return;
    }
    setPreview(next);
  };

  const confirm = async () => {
    if (!preview) return;
    setLoading(true);
    setError(null);
    try {
      const operation = await coffeeApi.confirmAdjustment({
        user_id: preview.user_id,
        delta_points: preview.delta_points,
        reason: preview.reason,
      });
      setResult(operation);
      setPreview(null);
    } catch (reasonValue) {
      setError(
        reasonValue instanceof Error
          ? reasonValue.message
          : "Не удалось выполнить корректировку",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Page title="Корректировка баланса" eyebrow="Опасное действие">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <Panel className="client-summary">
            <Avatar name={resource.data.display_name} size="large" />
            <div>
              <h2>{resource.data.display_name}</h2>
              <p className="muted">Код {resource.data.short_code}</p>
            </div>
            <strong className="client-summary__balance">
              {result?.balance_after ?? resource.data.balance_points}
              <small>баллов</small>
            </strong>
          </Panel>
          <div className="inline-warning">
            Корректировка не изменяет исходные операции. Будет создана новая
            запись с вашей причиной.
          </div>
          <Panel className="operation-panel">
            {result ? (
              <div className="operation-success" role="status">
                <span>✓</span>
                <h2>Баланс скорректирован</h2>
                <strong>
                  {result.delta_points > 0 ? "+" : ""}
                  {result.delta_points}
                </strong>
                <p>Новый баланс: {result.balance_after}</p>
                <Link className="button button--secondary" to="/admin/users">
                  Вернуться к пользователям
                </Link>
              </div>
            ) : preview ? (
              <div
                className="confirm-card"
                aria-label="Предпросмотр корректировки"
              >
                <h2>Проверьте изменение</h2>
                <dl>
                  <div>
                    <dt>Клиент</dt>
                    <dd>{preview.customer_name}</dd>
                  </div>
                  <div>
                    <dt>Текущий баланс</dt>
                    <dd>{preview.balance_before}</dd>
                  </div>
                  <div>
                    <dt>Изменение</dt>
                    <dd
                      className={
                        preview.delta_points > 0 ? "positive" : "negative"
                      }
                    >
                      {preview.delta_points > 0 ? "+" : ""}
                      {preview.delta_points}
                    </dd>
                  </div>
                  <div className="confirm-card__total">
                    <dt>Итоговый баланс</dt>
                    <dd>{preview.balance_after}</dd>
                  </div>
                  <div>
                    <dt>Причина</dt>
                    <dd>{preview.reason}</dd>
                  </div>
                </dl>
                <div className="action-row">
                  <Button
                    variant="secondary"
                    onClick={() => setPreview(null)}
                    disabled={loading}
                  >
                    Изменить
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => void confirm()}
                    disabled={loading}
                  >
                    {loading ? "Подтверждаем…" : "Подтвердить корректировку"}
                  </Button>
                </div>
              </div>
            ) : (
              <form className="form" onSubmit={makePreview}>
                <Field label="Изменение баллов" hint="Например, 50 или -20">
                  <input
                    value={delta}
                    onChange={(event) => setDelta(event.target.value)}
                    inputMode="numeric"
                    placeholder="+50"
                  />
                </Field>
                <Field label="Причина" hint="Причина попадёт в журнал аудита">
                  <textarea
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    rows={3}
                    maxLength={500}
                    placeholder="Например: компенсация за ошибочное списание"
                  />
                </Field>
                {error && (
                  <div className="inline-error" role="alert">
                    {error}
                  </div>
                )}
                <Button type="submit">Показать итог</Button>
              </form>
            )}
            {preview && error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
          </Panel>
        </>
      )}
    </Page>
  );
}

export function AdminEventsPage() {
  const [severity, setSeverity] = useState("");
  const [suspicious, setSuspicious] = useState(false);
  const resource = useResource(
    () =>
      coffeeApi.getAdminEvents({
        severity: severity || undefined,
        suspicious: suspicious || undefined,
      }),
    [severity, suspicious],
  );
  return (
    <Page title="События" eyebrow="Неизменяемый аудит">
      <Panel>
        <div className="filter-grid">
          <Field label="Важность">
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option value="">Все</option>
              <option value="info">Информация</option>
              <option value="warning">Предупреждения</option>
              <option value="critical">Критические</option>
            </select>
          </Field>
          <label className="checkbox checkbox--standalone">
            <input
              type="checkbox"
              checked={suspicious}
              onChange={(event) => setSuspicious(event.target.checked)}
            />
            <span>Только подозрительные</span>
          </label>
        </div>
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="event-list event-list--cards">
            {resource.data.items.map((event) => (
              <article
                key={event.id}
                className={event.suspicious ? "is-suspicious" : ""}
              >
                <span className={`event-dot event-dot--${event.severity}`} />
                <div>
                  <div className="tag-row">
                    <Badge
                      tone={
                        event.severity === "critical"
                          ? "danger"
                          : event.severity === "warning"
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {event.type}
                    </Badge>
                    {event.suspicious && (
                      <Badge tone="warning">Подозрительное</Badge>
                    )}
                  </div>
                  <p>{event.message}</p>
                  <small>
                    {formatDateTime(event.created_at)}
                    {event.actor_name ? ` · ${event.actor_name}` : ""}
                  </small>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Событий нет"
            text="По выбранным фильтрам ничего не найдено."
          />
        ))}
    </Page>
  );
}

export function AdminSettingsPage() {
  const resource = useResource(coffeeApi.getSettings);
  const [form, setForm] = useState<LoyaltySettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (resource.data) setForm(resource.data);
  }, [resource.data]);
  const update = <K extends keyof LoyaltySettings>(
    key: K,
    value: LoyaltySettings[K],
  ) => setForm((current) => (current ? { ...current, [key]: value } : current));
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      setForm(await coffeeApi.saveSettings(form));
      setSaved(true);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить настройки",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Page title="Программы" eyebrow="Настройки лояльности">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {form && (
        <form className="settings-form" onSubmit={(event) => void save(event)}>
          {saved && (
            <div className="inline-success" role="status">
              Настройки сохранены
            </div>
          )}
          <Panel>
            <div className="toggle-heading">
              <div>
                <h2>Балльная программа</h2>
                <p>Расчёт всегда выполняется backend.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={form.points_enabled}
                  onChange={(event) =>
                    update("points_enabled", event.target.checked)
                  }
                />
                <span />
              </label>
            </div>
            <div className="form-grid">
              <Field label="Название валюты">
                <input
                  value={form.currency_name}
                  onChange={(event) =>
                    update("currency_name", event.target.value)
                  }
                />
              </Field>
              <Field label="Рублей за один балл">
                <input
                  type="number"
                  min="1"
                  value={form.rubles_per_point}
                  onChange={(event) =>
                    update("rubles_per_point", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Минимальная покупка, ₽">
                <input
                  type="number"
                  min="0"
                  value={form.minimum_purchase_minor / 100}
                  onChange={(event) =>
                    update(
                      "minimum_purchase_minor",
                      Number(event.target.value) * 100,
                    )
                  }
                />
              </Field>
              <Field label="Округление">
                <select
                  value={form.rounding}
                  onChange={(event) =>
                    update(
                      "rounding",
                      event.target.value as LoyaltySettings["rounding"],
                    )
                  }
                >
                  <option value="floor">Вниз</option>
                  <option value="half_up">До ближайшего (0,5 вверх)</option>
                  <option value="ceiling">Вверх</option>
                </select>
              </Field>
              <Field label="Максимум оплаты баллами, %">
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={form.max_redemption_percent}
                  onChange={(event) =>
                    update("max_redemption_percent", Number(event.target.value))
                  }
                />
              </Field>
            </div>
          </Panel>
          <Panel>
            <div className="toggle-heading">
              <div>
                <h2>Посещения</h2>
                <p>Бизнес-день рассчитывается в выбранном часовом поясе.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={form.visit_enabled}
                  onChange={(event) =>
                    update("visit_enabled", event.target.checked)
                  }
                />
                <span />
              </label>
            </div>
            <div className="form-grid">
              <Field label="Цель посещений">
                <input
                  type="number"
                  min="1"
                  value={form.visit_goal}
                  onChange={(event) =>
                    update("visit_goal", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Часовой пояс">
                <input
                  value={form.timezone}
                  onChange={(event) => update("timezone", event.target.value)}
                />
              </Field>
              <Field label="Смена бизнес-дня">
                <input
                  type="time"
                  value={form.business_day_boundary}
                  onChange={(event) =>
                    update("business_day_boundary", event.target.value)
                  }
                />
              </Field>
            </div>
          </Panel>
          <Panel>
            <div className="toggle-heading">
              <div>
                <h2>Штампы</h2>
                <p>Награда создаётся после достижения цели.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={form.stamps_enabled}
                  onChange={(event) =>
                    update("stamps_enabled", event.target.checked)
                  }
                />
                <span />
              </label>
            </div>
            <Field label="Штампов до награды">
              <input
                type="number"
                min="1"
                value={form.stamp_goal}
                onChange={(event) =>
                  update("stamp_goal", Number(event.target.value))
                }
              />
            </Field>
          </Panel>
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить настройки"}
          </Button>
        </form>
      )}
    </Page>
  );
}

export function AdminMenuPage() {
  const resource = useResource(coffeeApi.getAdminMenu);
  const data = resource.data;
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = async (itemId: string) => {
    const item = resource.data?.items.find(
      (candidate) => candidate.id === itemId,
    );
    if (!item) return;
    setBusyId(item.id);
    setError(null);
    try {
      await coffeeApi.toggleMenuItem(item);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось обновить позицию",
      );
    } finally {
      setBusyId(null);
    }
  };
  return (
    <Page
      title="Меню"
      eyebrow="Контент кофейни"
      action={
        <Link className="button button--secondary" to="/admin/promotions">
          Акции
        </Link>
      }
    >
      <div className="content-tabs">
        <Link className="is-active" to="/admin/menu">
          Позиции
        </Link>
        <Link to="/admin/promotions">Акции</Link>
      </div>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <div className="inline-error">{error}</div>}
      {data && (
        <div className="admin-menu">
          {data.categories.map((category) => (
            <section key={category.id}>
              <div className="section-heading">
                <div>
                  <h2>{category.name}</h2>
                  <p>{category.description}</p>
                </div>
                <Badge>
                  {
                    data.items.filter(
                      (item) => item.category_id === category.id,
                    ).length
                  }
                </Badge>
              </div>
              {data.items
                .filter((item) => item.category_id === category.id)
                .map((item) => (
                  <article key={item.id}>
                    <div className="admin-menu__image">☕</div>
                    <div>
                      <h3>{item.name}</h3>
                      <p>{item.description}</p>
                      <strong>{formatMoney(item.price_minor)}</strong>
                    </div>
                    <div>
                      <Badge tone={item.visible ? "success" : "neutral"}>
                        {item.visible ? "Виден" : "Скрыт"}
                      </Badge>
                      <Button
                        variant="ghost"
                        onClick={() => void toggle(item.id)}
                        disabled={busyId === item.id}
                      >
                        {busyId === item.id
                          ? "…"
                          : item.visible
                            ? "Скрыть"
                            : "Показать"}
                      </Button>
                    </div>
                  </article>
                ))}
            </section>
          ))}
        </div>
      )}
    </Page>
  );
}

export function AdminPromotionsPage() {
  const resource = useResource(coffeeApi.getAdminPromotions);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const publish = async (id: string) => {
    const promotion = resource.data?.items.find((item) => item.id === id);
    if (!promotion) return;
    setBusyId(id);
    setError(null);
    try {
      await coffeeApi.publishPromotion(promotion);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось опубликовать акцию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const sorted = useMemo(() => resource.data?.items ?? [], [resource.data]);
  return (
    <Page
      title="Акции"
      eyebrow="Публикации"
      action={
        <Link className="button button--secondary" to="/admin/menu">
          Меню
        </Link>
      }
    >
      <div className="content-tabs">
        <Link to="/admin/menu">Позиции</Link>
        <Link className="is-active" to="/admin/promotions">
          Акции
        </Link>
      </div>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <div className="inline-error">{error}</div>}
      {resource.data &&
        (sorted.length ? (
          <div className="card-list">
            {sorted.map((promotion) => (
              <Panel className="promotion-admin-card" key={promotion.id}>
                <div>
                  <Badge
                    tone={
                      promotion.status === "published"
                        ? "success"
                        : promotion.status === "draft"
                          ? "neutral"
                          : "warning"
                    }
                  >
                    {promotion.status}
                  </Badge>
                  <h2>{promotion.title}</h2>
                  <p>{promotion.text}</p>
                  {promotion.ends_at && (
                    <small>До {formatDateTime(promotion.ends_at)}</small>
                  )}
                </div>
                {promotion.status !== "published" && (
                  <Button
                    onClick={() => void publish(promotion.id)}
                    disabled={busyId === promotion.id}
                  >
                    {busyId === promotion.id ? "Публикуем…" : "Опубликовать"}
                  </Button>
                )}
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Акций пока нет"
            text="Создайте первую публикацию через API или будущую форму редактора."
          />
        ))}
    </Page>
  );
}

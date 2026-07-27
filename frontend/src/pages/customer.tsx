import { useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { coffeeApi } from "../api/client";
import type {
  HistoryType,
  MenuItem,
  PointsMenuPurchase,
  Reward,
} from "../api/types";
import { useResource } from "../hooks/useResource";
import { formatDate, formatDateTime, formatMoney } from "../utils/format";
import {
  Avatar,
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Page,
  Panel,
  Progress,
} from "../components/ui";

export function HomePage() {
  const resource = useResource(coffeeApi.getHome);
  return (
    <Page title="Добро пожаловать" eyebrow="Ваша кофейня">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <Panel className="hero-card">
            <div className="hero-card__copy">
              <span>Ваш баланс</span>
              <strong>{resource.data.card.balance_points}</strong>
              <small>{resource.data.card.currency_name}</small>
            </div>
            <Link
              className="qr-shortcut"
              to="/card"
              aria-label="Открыть карту с QR-кодом"
            >
              <QRCodeSVG
                value={resource.data.card.qr_payload}
                size={76}
                level="M"
                marginSize={1}
                title="QR-код карты"
              />
              <span>Показать QR</span>
            </Link>
          </Panel>

          <Panel>
            <div className="section-heading">
              <h2>До следующей награды</h2>
              <Link to="/rewards">Все награды</Link>
            </div>
            <Progress
              value={resource.data.card.visit_streak}
              max={resource.data.card.visit_goal}
              label="Посещения подряд"
            />
            <Progress
              value={resource.data.card.stamps}
              max={resource.data.card.stamp_goal}
              label="Штампы"
            />
          </Panel>

          <section>
            <div className="section-heading">
              <h2>Активные акции</h2>
              <Link to="/more">Смотреть все</Link>
            </div>
            {resource.data.promotions.length ? (
              <div className="horizontal-cards">
                {resource.data.promotions.map((promotion) => (
                  <article className="promo-card" key={promotion.id}>
                    {promotion.image_url && (
                      <img src={promotion.image_url} alt="" />
                    )}
                    <Badge tone="accent">Акция</Badge>
                    <h3>{promotion.title}</h3>
                    <p>{promotion.text}</p>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                title="Акций пока нет"
                text="Мы сообщим, когда появится что-то вкусное."
              />
            )}
          </section>

          {resource.data.active_rewards[0] && (
            <Panel className="reward-highlight">
              <div>
                <Badge tone="success">Можно использовать</Badge>
                <h2>{resource.data.active_rewards[0].title}</h2>
                <p>{resource.data.active_rewards[0].description}</p>
              </div>
              <Link className="text-link" to="/rewards">
                Открыть
              </Link>
            </Panel>
          )}
        </>
      )}
    </Page>
  );
}

export function CardPage() {
  const resource = useResource(coffeeApi.getCard);
  return (
    <Page
      title="Моя карта"
      eyebrow="Покажите бариста"
      action={
        <Button
          variant="ghost"
          onClick={() => void resource.reload()}
          disabled={resource.loading}
          aria-label="Обновить карту"
        >
          ↻
        </Button>
      }
    >
      {resource.loading && <Loader label="Готовим карту…" />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <Panel
            className={`loyalty-card ${resource.data.blocked ? "loyalty-card--blocked" : ""}`}
          >
            <div className="loyalty-card__top">
              <span>Персональная карта</span>
              <Badge tone={resource.data.blocked ? "danger" : "success"}>
                {resource.data.blocked ? "Заблокирована" : "Активна"}
              </Badge>
            </div>
            <div className="qr-frame" data-testid="customer-card-qr">
              <QRCodeSVG
                value={resource.data.qr_payload}
                size={210}
                level="M"
                marginSize={2}
                title="Персональный QR-код карты"
              />
            </div>
            <strong className="card-owner">{resource.data.display_name}</strong>
            <span
              className="short-code"
              aria-label={`Короткий код ${resource.data.short_code}`}
            >
              {resource.data.short_code}
            </span>
            <div className="loyalty-card__balance">
              <span>Баланс</span>
              <strong>{resource.data.balance_points}</strong>
              <small>{resource.data.currency_name}</small>
            </div>
          </Panel>
          <div className="notice">
            <span aria-hidden="true">i</span>
            <p>
              Не пересылайте QR-код другим людям. Сканирование только находит
              карту — операцию всегда подтверждает сотрудник.
            </p>
          </div>
          <p className="updated">
            Обновлено {formatDateTime(resource.data.updated_at)}
          </p>
        </>
      )}
    </Page>
  );
}

const historyFilters: Array<{ value: "" | HistoryType; label: string }> = [
  { value: "", label: "Все" },
  { value: "purchase_accrual", label: "Начисления" },
  { value: "points_redemption", label: "Списания" },
  { value: "visit_mark", label: "Посещения" },
  { value: "reward_created", label: "Награды" },
];

export function HistoryPage() {
  const [filter, setFilter] = useState<"" | HistoryType>("");
  const resource = useResource(
    () => coffeeApi.getHistory(filter || undefined),
    [filter],
  );
  return (
    <Page title="История" eyebrow="Все изменения карты">
      <div className="chip-row" role="group" aria-label="Фильтр истории">
        {historyFilters.map((item) => (
          <button
            key={item.value}
            className={`chip ${filter === item.value ? "is-active" : ""}`}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="timeline">
            {resource.data.items.map((item) => (
              <article className="timeline-item" key={item.id}>
                <span
                  className={`timeline-item__mark timeline-item__mark--${item.delta_points && item.delta_points < 0 ? "minus" : "plus"}`}
                  aria-hidden="true"
                >
                  {item.delta_points
                    ? item.delta_points > 0
                      ? "+"
                      : "−"
                    : "·"}
                </span>
                <div>
                  <h2>{item.description}</h2>
                  <p>{formatDateTime(item.created_at)}</p>
                  {item.status !== "completed" && (
                    <Badge tone="warning">
                      {item.status === "pending"
                        ? "На подтверждении"
                        : "Отменена"}
                    </Badge>
                  )}
                </div>
                {item.delta_points != null && (
                  <strong
                    className={item.delta_points >= 0 ? "positive" : "negative"}
                  >
                    {item.delta_points > 0 ? "+" : ""}
                    {item.delta_points}
                  </strong>
                )}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Здесь пока пусто"
            text="Операции выбранного типа появятся после визита."
          />
        ))}
    </Page>
  );
}

const rewardTabs: Array<{ value: Reward["status"]; label: string }> = [
  { value: "active", label: "Активные" },
  { value: "redeemed", label: "Использованные" },
  { value: "expired", label: "Истёкшие" },
];

export function RewardsPage() {
  const [status, setStatus] = useState<Reward["status"]>("active");
  const resource = useResource(() => coffeeApi.getRewards(status), [status]);
  return (
    <Page title="Награды" eyebrow="Ваши приятные бонусы">
      <div className="segmented" role="tablist" aria-label="Статус награды">
        {rewardTabs.map((tab) => (
          <button
            role="tab"
            aria-selected={status === tab.value}
            key={tab.value}
            className={status === tab.value ? "is-active" : ""}
            onClick={() => setStatus(tab.value)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="card-list">
            {resource.data.items.map((reward) => (
              <Panel
                key={reward.id}
                className={`reward-card reward-card--${reward.status}`}
              >
                <div className="reward-card__icon" aria-hidden="true">
                  ◇
                </div>
                <div>
                  <Badge
                    tone={reward.status === "active" ? "success" : "neutral"}
                  >
                    {reward.status === "active"
                      ? `До ${formatDate(reward.expires_at)}`
                      : reward.status === "redeemed"
                        ? "Использована"
                        : "Срок истёк"}
                  </Badge>
                  <h2>{reward.title}</h2>
                  <p>{reward.description}</p>
                  {reward.status === "active" && (
                    <>
                      {reward.qr_payload && (
                        <div className="qr-frame">
                          <QRCodeSVG
                            value={reward.qr_payload}
                            size={180}
                            level="M"
                            marginSize={2}
                            title={`QR-код награды ${reward.title}`}
                          />
                        </div>
                      )}
                      <small>
                        Покажите QR бариста. Награда погашается только после
                        вашего подтверждения.
                      </small>
                    </>
                  )}
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Наград пока нет"
            text="Продолжайте заглядывать к нам — прогресс уже сохраняется."
          />
        ))}
    </Page>
  );
}

export function MenuPage() {
  const resource = useResource(coffeeApi.getMenu);
  const [category, setCategory] = useState<string>("");
  const [buying, setBuying] = useState<MenuItem | null>(null);
  const [purchase, setPurchase] = useState<PointsMenuPurchase | null>(null);
  const [purchaseKey, setPurchaseKey] = useState("");
  const [purchaseError, setPurchaseError] = useState<string | null>(null);
  const [purchasing, setPurchasing] = useState(false);
  const visibleItems = useMemo(
    () =>
      resource.data?.items.filter(
        (item) =>
          item.visible &&
          item.available &&
          (!category || item.category_id === category),
      ) ?? [],
    [resource.data, category],
  );
  const confirmPointsPurchase = async () => {
    if (!buying) return;
    setPurchasing(true);
    setPurchaseError(null);
    try {
      setPurchase(
        await coffeeApi.purchaseMenuItemWithPoints(buying.id, purchaseKey),
      );
      setBuying(null);
    } catch (reason) {
      setPurchaseError(
        reason instanceof Error ? reason.message : "Не удалось купить награду",
      );
    } finally {
      setPurchasing(false);
    }
  };
  return (
    <Page title="Меню" eyebrow="Что приготовим сегодня">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          {purchase && (
            <Panel className="reward-highlight">
              <div>
                <Badge tone="success">Награда готова</Badge>
                <h2>{purchase.item_name}</h2>
                <p>
                  Списано {purchase.points_spent} баллов. Осталось:{" "}
                  {purchase.balance_after}.
                </p>
                <div className="qr-frame">
                  <QRCodeSVG
                    value={purchase.qr_payload}
                    size={190}
                    level="M"
                    marginSize={2}
                    title="QR-код награды"
                  />
                </div>
                <small>Покажите этот QR-код бариста.</small>
              </div>
              <Button variant="ghost" onClick={() => setPurchase(null)}>
                Закрыть
              </Button>
            </Panel>
          )}
          {buying && (
            <Panel>
              <h2>Подтвердите покупку</h2>
              <p>
                {buying.name} за <strong>{buying.points_price} баллов</strong>.
                Баллы спишутся сразу, а вы получите QR-код награды.
              </p>
              {purchaseError && (
                <div className="inline-error">{purchaseError}</div>
              )}
              <div className="action-row">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setBuying(null);
                    setPurchaseKey("");
                  }}
                >
                  Отмена
                </Button>
                <Button
                  onClick={() => void confirmPointsPurchase()}
                  disabled={purchasing}
                >
                  {purchasing ? "Покупаем…" : "Списать баллы"}
                </Button>
              </div>
            </Panel>
          )}
          <div className="chip-row" role="group" aria-label="Категории меню">
            <button
              className={`chip ${!category ? "is-active" : ""}`}
              onClick={() => setCategory("")}
            >
              Всё
            </button>
            {resource.data.categories
              .filter((item) => item.visible)
              .map((item) => (
                <button
                  key={item.id}
                  className={`chip ${category === item.id ? "is-active" : ""}`}
                  onClick={() => setCategory(item.id)}
                >
                  {item.icon_url && (
                    <img
                      className="avatar avatar--small"
                      src={item.icon_url}
                      alt=""
                    />
                  )}
                  {item.name}
                </button>
              ))}
          </div>
          {visibleItems.length ? (
            <div className="menu-grid">
              {visibleItems.map((item) => (
                <article className="menu-card" key={item.id}>
                  <div className="menu-card__image">
                    {item.image_url ? (
                      <img src={item.image_url} alt="" />
                    ) : (
                      <span aria-hidden="true">☕</span>
                    )}
                  </div>
                  <div className="menu-card__body">
                    <div className="menu-card__title">
                      <h2>{item.name}</h2>
                      <strong>{formatMoney(item.price_minor)}</strong>
                    </div>
                    <p>{item.description}</p>
                    <div className="tag-row">
                      {item.volume && <Badge>{item.volume}</Badge>}
                      {item.labels?.map((label) => (
                        <Badge key={label} tone="accent">
                          {label}
                        </Badge>
                      ))}
                    </div>
                    {item.points_price && (
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setPurchaseError(null);
                          setBuying(item);
                          setPurchaseKey(
                            globalThis.crypto?.randomUUID?.() ??
                              `${Date.now()}-${Math.random()}`,
                          );
                        }}
                      >
                        Купить за {item.points_price} баллов
                      </Button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState
              title="Ничего не найдено"
              text="В этой категории сейчас нет доступных позиций."
            />
          )}
          <p className="muted centered">
            Обычный заказ и оплата выполняются в кофейне. Позиции с ценой в
            баллах можно купить в приложении.
          </p>
        </>
      )}
    </Page>
  );
}

export function PostPurchasePage() {
  const { operationId = "" } = useParams();
  const resource = useResource(
    () => coffeeApi.getPostPurchase(operationId),
    [operationId],
  );
  const [rating, setRating] = useState(5);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (message.trim().length < 3) {
      setError("Напишите хотя бы несколько слов");
      return;
    }
    setSending(true);
    setError(null);
    try {
      await coffeeApi.submitFeedback({
        rating,
        category: "service",
        message: message.trim(),
        may_contact: true,
      });
      setSent(true);
      setMessage("");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось отправить отзыв",
      );
    } finally {
      setSending(false);
    }
  };
  return (
    <Page title="Спасибо за визит" eyebrow="Как всё прошло">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <Panel>
            <div className="profile-heading">
              <Avatar
                name={resource.data.barista_name}
                src={resource.data.photo_url}
                size="large"
              />
              <div>
                <Badge tone="accent">Ваш бариста</Badge>
                <h2>{resource.data.barista_name}</h2>
                <p>{resource.data.position}</p>
              </div>
            </div>
            {resource.data.tip_url && (
              <a
                className="button button--primary"
                href={resource.data.tip_url}
                target="_blank"
                rel="noreferrer"
              >
                Оставить чаевые
              </a>
            )}
            {resource.data.tip_qr_url && (
              <img
                className="qr-frame"
                src={resource.data.tip_qr_url}
                alt="QR для чаевых"
              />
            )}
          </Panel>
          <Panel>
            <h2>Оцените обслуживание</h2>
            {sent ? (
              <div className="inline-success">
                Спасибо! Отзыв передан команде.
              </div>
            ) : (
              <form className="form" onSubmit={(event) => void submit(event)}>
                <Field label="Оценка">
                  <select
                    value={rating}
                    onChange={(event) => setRating(Number(event.target.value))}
                  >
                    <option value={5}>5 — Отлично</option>
                    <option value={4}>4 — Хорошо</option>
                    <option value={3}>3 — Нормально</option>
                    <option value={2}>2 — Плохо</option>
                    <option value={1}>1 — Очень плохо</option>
                  </select>
                </Field>
                <Field label="Отзыв">
                  <textarea
                    rows={3}
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                  />
                </Field>
                {error && <div className="inline-error">{error}</div>}
                <Button type="submit" disabled={sending}>
                  {sending ? "Отправляем…" : "Отправить отзыв"}
                </Button>
              </form>
            )}
          </Panel>
        </>
      )}
    </Page>
  );
}

export function MorePage() {
  const resource = useResource(coffeeApi.getMore);
  const [rating, setRating] = useState(5);
  const [category, setCategory] = useState("service");
  const [message, setMessage] = useState("");
  const [mayContact, setMayContact] = useState(true);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const sendFeedback = async (event: FormEvent) => {
    event.preventDefault();
    if (message.trim().length < 3) {
      setFormError("Напишите хотя бы несколько слов");
      return;
    }
    setSending(true);
    setFormError(null);
    try {
      await coffeeApi.submitFeedback({
        rating,
        category,
        message: message.trim(),
        may_contact: mayContact,
      });
      setSent(true);
      setMessage("");
    } catch (reason) {
      setFormError(
        reason instanceof Error
          ? reason.message
          : "Не удалось отправить сообщение",
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <Page title="Ещё" eyebrow="Всё о кофейне">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <Panel>
            <h2>{resource.data.contacts.coffee_shop_name}</h2>
            <p>{resource.data.contacts.description}</p>
            {resource.data.contacts.locations.map((location) => (
              <div className="location" key={location.id}>
                <strong>{location.address}</strong>
                <span>{location.hours}</span>
                <div className="action-row">
                  {location.map_url && (
                    <a
                      className="button button--secondary"
                      href={location.map_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      На карте
                    </a>
                  )}
                  {location.phone && (
                    <a
                      className="button button--ghost"
                      href={`tel:${location.phone}`}
                    >
                      Позвонить
                    </a>
                  )}
                </div>
              </div>
            ))}
          </Panel>
          <section>
            <div className="section-heading">
              <h2>Наша команда</h2>
            </div>
            <div className="card-list">
              {resource.data.staff.map((staff) => (
                <Panel className="staff-public-card" key={staff.id}>
                  <Avatar
                    name={staff.display_name}
                    src={staff.photo_url}
                    size="large"
                  />
                  <div>
                    <h3>{staff.display_name}</h3>
                    <p className="muted">{staff.position}</p>
                    <p>{staff.bio}</p>
                    {staff.tip_url && (
                      <a
                        className="text-link"
                        href={staff.tip_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        Оставить чаевые ↗
                      </a>
                    )}
                    <small>Перевод проходит через сторонний сервис.</small>
                  </div>
                </Panel>
              ))}
            </div>
          </section>
          <Panel>
            <h2>Обратная связь</h2>
            {sent && (
              <div className="inline-success" role="status">
                Спасибо! Обращение отправлено.
              </div>
            )}
            <form
              className="form"
              onSubmit={(event) => void sendFeedback(event)}
            >
              <Field label="Оценка">
                <div className="rating" role="radiogroup" aria-label="Оценка">
                  {[1, 2, 3, 4, 5].map((value) => (
                    <button
                      type="button"
                      key={value}
                      className={value <= rating ? "is-active" : ""}
                      onClick={() => setRating(value)}
                      aria-label={`${value} из 5`}
                    >
                      ★
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Категория">
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  <option value="service">Обслуживание</option>
                  <option value="food">Напитки и еда</option>
                  <option value="application">Приложение</option>
                  <option value="loyalty">Программа лояльности</option>
                  <option value="other">Другое</option>
                </select>
              </Field>
              <Field label="Сообщение" error={formError ?? undefined}>
                <textarea
                  rows={4}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  maxLength={1000}
                  placeholder="Расскажите, что понравилось или что можно улучшить"
                />
              </Field>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={mayContact}
                  onChange={(event) => setMayContact(event.target.checked)}
                />
                <span>Можно связаться со мной по этому обращению</span>
              </label>
              <Button type="submit" disabled={sending}>
                {sending ? "Отправляем…" : "Отправить"}
              </Button>
            </form>
          </Panel>
          <Panel>
            <h2>Правила и приватность</h2>
            <details>
              <summary>Как работает программа</summary>
              <p>
                Баллы, посещения и штампы начисляет сотрудник после
                подтверждения покупки. Условия наград отображаются в разделе
                «Награды».
              </p>
            </details>
            <details>
              <summary>Политика конфиденциальности</summary>
              <p>{resource.data.contacts.privacy_policy}</p>
            </details>
            {resource.data.contacts.support_contact && (
              <p>
                Поддержка:{" "}
                <strong>{resource.data.contacts.support_contact}</strong>
              </p>
            )}
          </Panel>
        </>
      )}
    </Page>
  );
}

import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { QRCodeSVG } from "qrcode.react";
import { coffeeApi, createIdempotencyKey } from "../api/client";
import type {
  BulkBonusDraft,
  BulkBonusPreview,
  CustomerPass,
  PublicReview,
  PassTemplate,
  ReviewStatus,
} from "../api/types";
import { useResource } from "../hooks/useResource";
import { formatDateTime, formatMoney } from "../utils/format";
import {
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

const reviewStatus: Record<ReviewStatus, string> = {
  pending: "На модерации",
  approved: "Опубликован",
  rejected: "Отклонён",
  hidden: "Скрыт",
};

const passStatus: Record<CustomerPass["status"], string> = {
  active: "Активен",
  exhausted: "Использован",
  expired: "Истёк",
  cancelled: "Отменён",
};

function ReviewCard({
  value,
  admin = false,
}: {
  value: PublicReview;
  admin?: boolean;
}) {
  return (
    <Panel>
      <div className="row-between">
        <strong>{value.author_display_name}</strong>
        <Badge tone={value.status === "approved" ? "success" : "neutral"}>
          {admin
            ? reviewStatus[value.status]
            : `${"★".repeat(value.rating)} ${value.rating}/5`}
        </Badge>
      </div>
      <p>{value.text}</p>
      <small>
        {value.venue_name} · {formatDateTime(value.created_at)}
      </small>
      {admin && <p className="muted">Оценка: {value.rating}/5</p>}
      {admin && value.moderation_note && (
        <p>Заметка: {value.moderation_note}</p>
      )}
    </Panel>
  );
}

export function ReviewsPage() {
  const venues = useResource(coffeeApi.getVenues);
  const reviews = useResource(() => coffeeApi.getReviews());
  const mine = useResource(coffeeApi.getMyReviews);
  const [venueId, setVenueId] = useState("");
  const [rating, setRating] = useState(5);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await coffeeApi.createReview({
        venue_id: venueId,
        order_id: null,
        employee_staff_id: null,
        rating,
        text,
        author_display_name: null,
      });
      setText("");
      await mine.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось отправить отзыв"),
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page title="Отзывы" eyebrow="Публикация после модерации">
      <Panel>
        <h2>Оставить отзыв</h2>
        <form className="form" onSubmit={(event) => void submit(event)}>
          <Field label="Заведение">
            <select
              value={venueId}
              onChange={(event) => setVenueId(event.target.value)}
              required
            >
              <option value="">Выберите заведение</option>
              {(venues.data?.items ?? []).map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Оценка">
            <select
              value={rating}
              onChange={(event) => setRating(Number(event.target.value))}
            >
              {[5, 4, 3, 2, 1].map((value) => (
                <option key={value} value={value}>
                  {value} из 5
                </option>
              ))}
            </select>
          </Field>
          <Field label="Текст">
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              maxLength={4000}
              required
            />
          </Field>
          <Button type="submit" disabled={busy || !venueId}>
            {busy ? "Отправляем…" : "Отправить на модерацию"}
          </Button>
        </form>
        {error && <ErrorState error={error} compact />}
      </Panel>
      <h2>Опубликованные</h2>
      {reviews.loading && <Loader />}
      {reviews.error && (
        <ErrorState error={reviews.error} onRetry={reviews.reload} />
      )}
      <div className="card-list">
        {reviews.data?.items.map((value) => (
          <ReviewCard key={value.id} value={value} />
        ))}
      </div>
      <h2>Мои отзывы</h2>
      <div className="card-list">
        {mine.data?.items.map((value) => (
          <ReviewCard key={value.id} value={value} admin />
        ))}
      </div>
    </Page>
  );
}

export function MySubscriptionsPage() {
  return (
    <Page title="Абонементы" eyebrow="Оставшиеся использования">
      <MySubscriptionsSection />
    </Page>
  );
}

export function MySubscriptionsSection() {
  const resource = useResource(coffeeApi.getMyPasses);
  const purchases = useResource(coffeeApi.getMyPassPurchases);
  return (
    <section aria-labelledby="subscriptions-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Абонементы</p>
          <h2 id="subscriptions-heading">Оставшиеся использования</h2>
        </div>
      </div>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {(purchases.data?.items ?? [])
        .filter((purchase) => purchase.status === "pending")
        .map((purchase) => (
          <Panel key={purchase.id}>
            <div className="row-between">
              <h2>{purchase.name}</h2>
              <Badge tone="warning">Ожидает оплаты</Badge>
            </div>
            <p>
              Номер покупки: <strong>{purchase.number}</strong>
            </p>
            <p>{formatMoney(purchase.price_minor)} · оплата на точке</p>
          </Panel>
        ))}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="card-list">
            {resource.data.items.map((value) => (
              <PassCard key={value.id} value={value} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="Абонементов пока нет"
            text="Купленные или выданные администратором абонементы появятся здесь."
          />
        ))}
    </section>
  );
}

function PassCard({
  value,
  action,
}: {
  value: CustomerPass;
  action?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Panel className="pass-card">
        {value.image_url && (
          <img className="pass-card__image" src={value.image_url} alt="" />
        )}
        <div className="row-between">
          <h2>{value.name}</h2>
          <Badge tone={value.status === "active" ? "success" : "neutral"}>
            {passStatus[value.status]}
          </Badge>
        </div>
        <p>{value.description}</p>
        <Progress
          value={value.remaining_uses}
          max={value.total_uses}
          label="Осталось использований"
        />
        <small>Действует до {formatDateTime(value.expires_at)}</small>
        <div className="action-row">
          <Button variant="secondary" onClick={() => setOpen(true)}>
            {value.status === "active" ? "Открыть QR" : "Подробнее"}
          </Button>
          {action}
        </div>
      </Panel>
      {open && (
        <div
          className="purchase-sheet-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <Panel
            className="purchase-sheet purchase-sheet--success pass-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby={`pass-title-${value.id}`}
          >
            {value.image_url && (
              <img
                className="subscription-product__image"
                src={value.image_url}
                alt=""
              />
            )}
            <Badge tone={value.status === "active" ? "success" : "neutral"}>
              {passStatus[value.status]}
            </Badge>
            <h2 id={`pass-title-${value.id}`}>{value.name}</h2>
            <Progress
              value={value.remaining_uses}
              max={value.total_uses}
              label="Осталось использований"
            />
            {value.status === "active" && (
              <div className="qr-frame" data-testid="subscription-qr">
                <QRCodeSVG
                  value={value.qr_payload}
                  size={190}
                  level="M"
                  marginSize={2}
                  title={`QR-код абонемента ${value.name}`}
                />
              </div>
            )}
            <small>
              {value.status === "active"
                ? "Покажите QR сотруднику. Списание произойдёт только после подтверждения."
                : `Действует до ${formatDateTime(value.expires_at)}`}
            </small>
            <Button
              variant="secondary"
              onClick={() => setOpen(false)}
              autoFocus
            >
              Закрыть
            </Button>
          </Panel>
        </div>
      )}
    </>
  );
}

export function StaffPendingPassPurchases() {
  const purchases = useResource(coffeeApi.getPendingPassPurchases);
  const [busy, setBusy] = useState("");
  return (
    <Panel>
      <div className="row-between">
        <div>
          <p className="eyebrow">Абонементы</p>
          <h2>Ожидают подтверждения</h2>
        </div>
        {!!purchases.data?.items.length && (
          <Badge tone="warning">{purchases.data.items.length}</Badge>
        )}
      </div>
      {purchases.loading && <Loader />}
      {purchases.error && (
        <ErrorState
          error={purchases.error}
          onRetry={purchases.reload}
          compact
        />
      )}
      {(purchases.data?.items ?? []).map((purchase) => (
        <div className="order-line-snapshot" key={purchase.id}>
          <span>
            <strong>
              №{purchase.number} · {purchase.name}
            </strong>
            <small>{formatMoney(purchase.price_minor)}</small>
          </span>
          <Button
            disabled={busy === purchase.id}
            onClick={() => {
              setBusy(purchase.id);
              void coffeeApi
                .confirmPassPurchase(purchase.id)
                .then(purchases.reload)
                .finally(() => setBusy(""));
            }}
          >
            {busy === purchase.id ? "Подтверждаем…" : "Оплата получена"}
          </Button>
        </div>
      ))}
      {!purchases.loading && !purchases.data?.items.length && (
        <p className="muted">Покупок, ожидающих оплаты, нет.</p>
      )}
    </Panel>
  );
}

export function AdminReviewsPage() {
  const [status, setStatus] = useState<ReviewStatus | "">("pending");
  const resource = useResource(
    () => coffeeApi.getAdminReviews(status || undefined),
    [status],
  );
  const [busy, setBusy] = useState("");
  const moderate = async (
    review: PublicReview,
    target: Exclude<ReviewStatus, "pending">,
  ) => {
    const note =
      window.prompt("Заметка модератора (необязательно)")?.trim() || null;
    setBusy(review.id);
    try {
      await coffeeApi.moderateReview(review.id, target, note);
      await resource.reload();
    } finally {
      setBusy("");
    }
  };
  return (
    <Page title="Публичные отзывы" eyebrow="Очередь модерации">
      <Field label="Статус">
        <select
          value={status}
          onChange={(event) =>
            setStatus(event.target.value as ReviewStatus | "")
          }
        >
          <option value="">Все</option>
          {Object.entries(reviewStatus).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      <div className="card-list">
        {resource.data?.items.map((review) => (
          <div key={review.id}>
            <ReviewCard value={review} admin />
            <div className="action-row">
              <Button
                disabled={busy === review.id}
                onClick={() => void moderate(review, "approved")}
              >
                Одобрить
              </Button>
              <Button
                variant="secondary"
                disabled={busy === review.id}
                onClick={() => void moderate(review, "rejected")}
              >
                Отклонить
              </Button>
              <Button
                variant="danger"
                disabled={busy === review.id}
                onClick={() => void moderate(review, "hidden")}
              >
                Скрыть
              </Button>
            </div>
          </div>
        ))}
      </div>
    </Page>
  );
}

export function StaffPassPanel({
  userId,
  venueId,
}: {
  userId: string;
  venueId: string | null;
}) {
  const passes = useResource(
    () => coffeeApi.getCustomerPasses(userId),
    [userId],
  );
  const menu = useResource(coffeeApi.getMenu);
  const items = useMemo(
    () =>
      (menu.data?.items ?? []).filter(
        (item) => !venueId || item.venue_id === venueId,
      ),
    [menu.data, venueId],
  );
  const [itemId, setItemId] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const use = async (passId: string) => {
    if (!venueId || !itemId) return;
    setBusy(passId);
    setError(null);
    try {
      await coffeeApi.usePass(passId, venueId, itemId);
      await passes.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось использовать абонемент"),
      );
    } finally {
      setBusy("");
    }
  };
  return (
    <Panel>
      <h2>Абонементы клиента</h2>
      <Field label="Товар">
        <select
          value={itemId}
          onChange={(event) => setItemId(event.target.value)}
        >
          <option value="">Выберите товар</option>
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
            </option>
          ))}
        </select>
      </Field>
      {passes.loading && <Loader />}
      {passes.error && (
        <ErrorState error={passes.error} onRetry={passes.reload} compact />
      )}
      {error && <ErrorState error={error} compact />}
      {(passes.data?.items ?? [])
        .filter((value) => value.status === "active")
        .map((value) => (
          <PassCard
            key={value.id}
            value={value}
            action={
              <Button
                disabled={busy === value.id || !venueId || !itemId}
                onClick={() => void use(value.id)}
              >
                {busy === value.id ? "Используем…" : "Использовать один раз"}
              </Button>
            }
          />
        ))}
    </Panel>
  );
}

export function AdminSubscriptionsPage() {
  const templates = useResource(() => coffeeApi.getPassTemplates(false));
  const purchases = useResource(coffeeApi.getPendingPassPurchases);
  const venues = useResource(coffeeApi.getVenues);
  const menu = useResource(coffeeApi.getMenu);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [uses, setUses] = useState(20);
  const [days, setDays] = useState(90);
  const [priceMinor, setPriceMinor] = useState(0);
  const [purchaseEnabled, setPurchaseEnabled] = useState(true);
  const [imageMediaId, setImageMediaId] = useState<string | null>(null);
  const [venueIds, setVenueIds] = useState<string[]>([]);
  const [categoryIds, setCategoryIds] = useState<string[]>([]);
  const [itemIds, setItemIds] = useState<string[]>([]);
  const [userId, setUserId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const resetForm = () => {
    setEditingId(null);
    setName("");
    setDescription("");
    setUses(20);
    setDays(90);
    setPriceMinor(0);
    setPurchaseEnabled(true);
    setVenueIds([]);
    setCategoryIds([]);
    setItemIds([]);
    setImageMediaId(null);
  };
  const edit = (value: PassTemplate) => {
    setEditingId(value.id);
    setName(value.name);
    setDescription(value.description);
    setUses(value.total_uses);
    setDays(value.validity_days);
    setPriceMinor(value.price_minor);
    setPurchaseEnabled(value.purchase_enabled);
    setVenueIds(value.venue_ids);
    setCategoryIds(value.category_ids);
    setItemIds(value.item_ids);
    setImageMediaId(value.image_media_id);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const payload = {
        name,
        description,
        image_media_id: imageMediaId,
        total_uses: uses,
        validity_days: days,
        price_minor: priceMinor,
        purchase_enabled: purchaseEnabled,
        venue_ids: venueIds,
        category_ids: categoryIds,
        item_ids: itemIds,
      };
      if (editingId) await coffeeApi.updatePassTemplate(editingId, payload);
      else await coffeeApi.createPassTemplate(payload);
      resetForm();
      await templates.reload();
    } finally {
      setBusy(false);
    }
  };
  const issue = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const value = await coffeeApi.issuePass(userId.trim(), templateId);
      setMessage(`Абонемент ${value.name} выдан`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page title="Абонементы" eyebrow="Без банковской подписки">
      <Panel>
        <div className="section-heading">
          <h2>{editingId ? "Редактирование абонемента" : "Новый абонемент"}</h2>
          {editingId && (
            <Button type="button" variant="ghost" onClick={resetForm}>
              Отмена
            </Button>
          )}
        </div>
        <form className="form" onSubmit={(event) => void create(event)}>
          <Field label="Название">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </Field>
          <Field label="Описание">
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              required
            />
          </Field>
          <Field label="Использований">
            <input
              type="number"
              min={1}
              value={uses}
              onChange={(event) => setUses(Number(event.target.value))}
            />
          </Field>
          <Field label="Срок, дней">
            <input
              type="number"
              min={1}
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
            />
          </Field>
          <Field label="Цена, ₽">
            <input
              type="number"
              min={0}
              step="0.01"
              value={priceMinor / 100}
              onChange={(event) =>
                setPriceMinor(Math.round(Number(event.target.value) * 100))
              }
            />
          </Field>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={purchaseEnabled}
              onChange={(event) => setPurchaseEnabled(event.target.checked)}
            />
            <span>Показывать в меню и разрешить оформление</span>
          </label>
          <Field
            label="Обложка абонемента"
            hint="Рекомендуемый размер: 1200×800 px (3:2), JPG/PNG/WebP, до 5 МБ."
          >
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                void coffeeApi
                  .uploadAdminMedia(file, "pass_template")
                  .then((media) => setImageMediaId(media.id));
              }}
            />
            {imageMediaId && (
              <img
                className="admin-image-preview admin-image-preview--wide"
                src={`/api/v1/media/${imageMediaId}`}
                alt="Предпросмотр обложки"
              />
            )}
          </Field>
          <Field label="Заведения (пусто — все)">
            <select
              multiple
              value={venueIds}
              onChange={(event) =>
                setVenueIds(
                  Array.from(
                    event.currentTarget.selectedOptions,
                    (option) => option.value,
                  ),
                )
              }
            >
              {(venues.data?.items ?? []).map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Категории (пусто — все)">
            <select
              multiple
              value={categoryIds}
              onChange={(event) =>
                setCategoryIds(
                  Array.from(
                    event.currentTarget.selectedOptions,
                    (option) => option.value,
                  ),
                )
              }
            >
              {(menu.data?.categories ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Конкретные позиции (пусто — все)">
            <select
              multiple
              value={itemIds}
              onChange={(event) =>
                setItemIds(
                  Array.from(
                    event.currentTarget.selectedOptions,
                    (option) => option.value,
                  ),
                )
              }
            >
              {(menu.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Button type="submit" disabled={busy}>
            {editingId ? "Сохранить изменения" : "Создать абонемент"}
          </Button>
        </form>
      </Panel>
      <Panel>
        <h2>Ожидают оплаты на точке</h2>
        {purchases.loading && <Loader />}
        {purchases.error && (
          <ErrorState
            error={purchases.error}
            onRetry={purchases.reload}
            compact
          />
        )}
        {(purchases.data?.items ?? []).map((purchase) => (
          <div className="order-line-snapshot" key={purchase.id}>
            <span>
              <strong>
                №{purchase.number} · {purchase.name}
              </strong>
              <small>
                {formatMoney(purchase.price_minor)} · клиент {purchase.user_id}
              </small>
            </span>
            <Button
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void coffeeApi
                  .confirmPassPurchase(purchase.id)
                  .then(() => purchases.reload())
                  .finally(() => setBusy(false));
              }}
            >
              Оплата получена
            </Button>
          </div>
        ))}
        {!purchases.loading && !purchases.data?.items.length && (
          <p className="muted">Новых покупок нет.</p>
        )}
      </Panel>
      <Panel>
        <h2>Выдать клиенту</h2>
        <form className="form" onSubmit={(event) => void issue(event)}>
          <Field label="UUID клиента">
            <input
              value={userId}
              onChange={(event) => setUserId(event.target.value)}
              required
            />
          </Field>
          <Field label="Шаблон">
            <select
              value={templateId}
              onChange={(event) => setTemplateId(event.target.value)}
              required
            >
              <option value="">Выберите</option>
              {templates.data?.items
                .filter((value) => value.is_active)
                .map((value) => (
                  <option key={value.id} value={value.id}>
                    {value.name}
                  </option>
                ))}
            </select>
          </Field>
          <Button type="submit" disabled={busy}>
            Выдать
          </Button>
        </form>
        {message && <p className="notice">{message}</p>}
      </Panel>
      <div className="card-list">
        {templates.data?.items.map((value) => (
          <Panel key={value.id} className="pass-card">
            {value.image_url && (
              <img className="pass-card__image" src={value.image_url} alt="" />
            )}
            <div className="row-between">
              <h2>{value.name}</h2>
              <Badge tone={value.is_active ? "success" : "neutral"}>
                {value.is_active ? "Активен" : "Архив"}
              </Badge>
            </div>
            <p>{value.description}</p>
            <small>
              {value.total_uses} использований · {value.validity_days} дней
            </small>
            <strong>{formatMoney(value.price_minor)}</strong>
            <Badge tone={value.purchase_enabled ? "success" : "neutral"}>
              {value.purchase_enabled
                ? "Продаётся в меню"
                : "Только ручная выдача"}
            </Badge>
            <div className="action-row">
              <Button variant="secondary" onClick={() => edit(value)}>
                Редактировать
              </Button>
              {value.is_active ? (
                <Button
                  variant="secondary"
                  onClick={() =>
                    void coffeeApi
                      .archivePassTemplate(value.id)
                      .then(() => templates.reload())
                  }
                >
                  В архив
                </Button>
              ) : (
                <Button
                  onClick={() =>
                    void coffeeApi
                      .restorePassTemplate(value.id)
                      .then(() => templates.reload())
                  }
                >
                  Вернуть из архива
                </Button>
              )}
            </div>
          </Panel>
        ))}
      </div>
    </Page>
  );
}

export function AdminBulkBonusPage() {
  const venues = useResource(coffeeApi.getVenues);
  const [customers, setCustomers] = useState("");
  const [points, setPoints] = useState(100);
  const [reason, setReason] = useState("");
  const [venueId, setVenueId] = useState<string | null>(null);
  const [preview, setPreview] = useState<BulkBonusPreview | null>(null);
  const [key, setKey] = useState(createIdempotencyKey);
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const draft = (): BulkBonusDraft => ({
    customer_ids: customers
      .split(/[\s,;]+/)
      .map((value) => value.trim())
      .filter(Boolean),
    points_per_user: points,
    reason,
    venue_id: venueId,
  });
  const rotate = () => {
    setPreview(null);
    setKey(createIdempotencyKey());
  };
  const calculate = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      setPreview(await coffeeApi.previewBulkBonus(draft()));
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    if (!preview) return;
    setBusy(true);
    try {
      const value = await coffeeApi.confirmBulkBonus(
        { ...draft(), preview_hash: preview.preview_hash },
        key,
      );
      setResult(
        `Начислено ${value.total_points} баллов для ${value.recipient_count} клиентов`,
      );
      setPreview(null);
      setKey(createIdempotencyKey());
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page title="Массовый бонус" eyebrow="Preview → явное подтверждение">
      <Panel>
        <form className="form" onSubmit={(event) => void calculate(event)}>
          <Field
            label="UUID клиентов"
            hint="Через пробел или запятую; пусто — все eligible"
          >
            <textarea
              value={customers}
              onChange={(event) => {
                setCustomers(event.target.value);
                rotate();
              }}
            />
          </Field>
          <Field label="Баллов каждому">
            <input
              type="number"
              min={1}
              value={points}
              onChange={(event) => {
                setPoints(Number(event.target.value));
                rotate();
              }}
            />
          </Field>
          <Field label="Причина">
            <input
              value={reason}
              onChange={(event) => {
                setReason(event.target.value);
                rotate();
              }}
              required
            />
          </Field>
          <Field label="Заведение" hint="Обязательно при раздельных кошельках">
            <select
              value={venueId ?? ""}
              onChange={(event) => {
                setVenueId(event.target.value || null);
                rotate();
              }}
            >
              <option value="">Общий кошелёк</option>
              {venues.data?.items.map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
            </select>
          </Field>
          <Button type="submit" disabled={busy}>
            Рассчитать
          </Button>
        </form>
      </Panel>
      {preview && (
        <Panel>
          <h2>Подтверждение</h2>
          <p>
            Получателей: <strong>{preview.recipient_count}</strong>
          </p>
          <p>
            Всего баллов: <strong>{preview.total_points}</strong>
          </p>
          <Button disabled={busy} onClick={() => void confirm()}>
            Подтвердить начисление
          </Button>
        </Panel>
      )}
      {result && <p className="notice">{result}</p>}
    </Page>
  );
}

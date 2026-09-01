import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { coffeeApi, createIdempotencyKey } from "../api/client";
import type { CustomerOrder, FulfillmentMode, OrderStatus } from "../api/types";
import { useCart } from "../components/CartContext";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { formatDateTime, formatMoney } from "../utils/format";

const statusLabels: Record<OrderStatus, string> = {
  new: "Новый",
  confirmed: "Подтверждён",
  preparing: "Готовится",
  ready: "Готов",
  waiting_for_courier: "Ожидает курьера",
  courier_assigned: "Курьер назначен",
  picked_up: "Забран курьером",
  in_transit: "В пути",
  delivered: "Доставлен",
  cancelled: "Отменён",
};

const nextStaffStatus: Partial<Record<OrderStatus, OrderStatus>> = {
  new: "confirmed",
  confirmed: "preparing",
  preparing: "ready",
};

function getNextStaffStatusFor(
  status: OrderStatus,
  fulfillmentMode: FulfillmentMode,
): OrderStatus | undefined {
  if (status === "ready" && fulfillmentMode === "pickup") {
    return "delivered";
  }
  return nextStaffStatus[status];
}

function getNextStaffStatus(order: CustomerOrder): OrderStatus | undefined {
  return getNextStaffStatusFor(order.status, order.fulfillment_mode);
}

function statusTone(
  status: OrderStatus,
): "neutral" | "success" | "warning" | "danger" {
  if (status === "delivered" || status === "ready") return "success";
  if (status === "cancelled") return "danger";
  if (status === "new") return "warning";
  return "neutral";
}

function OrderSummary({
  order,
  embedded = false,
}: {
  order: CustomerOrder;
  embedded?: boolean;
}) {
  const content = (
    <>
      <div className="order-card__head">
        <div>
          <small>{formatDateTime(order.created_at)}</small>
          <h2>Заказ №{order.number}</h2>
        </div>
        <Badge tone={statusTone(order.status)}>
          {statusLabels[order.status]}
        </Badge>
      </div>
      <p>
        {order.fulfillment_mode === "pickup" ? "Самовывоз" : "Доставка"} ·{" "}
        {order.suborders.reduce((sum, value) => sum + value.lines.length, 0)}{" "}
        позиций
      </p>
      <strong>{formatMoney(order.total_minor)}</strong>
    </>
  );
  return embedded ? (
    <div className="order-summary">{content}</div>
  ) : (
    <Panel className="order-card">{content}</Panel>
  );
}

export function CartPage() {
  const cart = useCart();
  return (
    <Page
      title="Корзина"
      eyebrow={`${cart.count} позиций`}
      action={
        <Link className="button button--secondary" to="/menu">
          В меню
        </Link>
      }
    >
      {!cart.items.length ? (
        <EmptyState
          title="Корзина пуста"
          text="Добавьте напиток или блюдо из меню."
          action={
            <Link className="button button--primary" to="/menu">
              Открыть меню
            </Link>
          }
        />
      ) : (
        <>
          <div className="card-list">
            {cart.items.map((item) => (
              <Panel className="cart-line" key={item.line_id}>
                <div className="cart-line__image">
                  {item.image_url ? (
                    <img src={item.image_url} alt="" />
                  ) : (
                    <span aria-hidden="true">☕</span>
                  )}
                </div>
                <div className="cart-line__details">
                  <h2>{item.name}</h2>
                  {item.modifier_names.length > 0 && (
                    <p>{item.modifier_names.join(", ")}</p>
                  )}
                  <strong>
                    {formatMoney(item.unit_estimate_minor * item.quantity)}
                  </strong>
                </div>
                <div
                  className="quantity-control"
                  aria-label={`Количество ${item.name}`}
                >
                  <Button
                    variant="ghost"
                    onClick={() =>
                      cart.setQuantity(item.line_id, item.quantity - 1)
                    }
                    disabled={item.quantity <= 1}
                  >
                    −
                  </Button>
                  <span>{item.quantity}</span>
                  <Button
                    variant="ghost"
                    onClick={() =>
                      cart.setQuantity(item.line_id, item.quantity + 1)
                    }
                  >
                    +
                  </Button>
                </div>
                <Button
                  className="cart-line__remove"
                  variant="danger"
                  onClick={() => cart.remove(item.line_id)}
                >
                  Удалить
                </Button>
              </Panel>
            ))}
          </div>
          <Panel className="cart-total">
            <span>Предварительно</span>
            <strong>
              {formatMoney(
                cart.items.reduce(
                  (sum, item) => sum + item.unit_estimate_minor * item.quantity,
                  0,
                ),
              )}
            </strong>
            <small>Скидки и точная сумма будут рассчитаны сервером.</small>
          </Panel>
          <Link
            className="button button--primary order-wide-action"
            to="/checkout"
          >
            Перейти к оформлению
          </Link>
        </>
      )}
    </Page>
  );
}

export function CheckoutPage() {
  const cart = useCart();
  const navigate = useNavigate();
  const options = useResource(coffeeApi.getOrderOptions);
  const wallets = useResource(coffeeApi.getMyWallets);
  const [mode, setMode] = useState<FulfillmentMode>("pickup");
  const [phone, setPhone] = useState("");
  const [pickupId, setPickupId] = useState("");
  const [zoneId, setZoneId] = useState("");
  const [address, setAddress] = useState("");
  const [entrance, setEntrance] = useState("");
  const [apartment, setApartment] = useState("");
  const [floor, setFloor] = useState("");
  const [comment, setComment] = useState("");
  const [desiredAt, setDesiredAt] = useState("");
  const [paymentMethod, setPaymentMethod] = useState<
    "cash" | "card_on_receipt"
  >("card_on_receipt");
  const [pointRedemptions, setPointRedemptions] = useState<
    Record<string, number>
  >({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<Error | null>(null);
  const priceDependency = JSON.stringify(
    cart.items.map(({ line_id, quantity, modifiers }) => ({
      line_id,
      quantity,
      modifiers,
    })),
  );
  const price = useResource(
    () =>
      coffeeApi.priceCart({
        fulfillment_mode: mode,
        lines: cart.items.map(
          ({ line_id, menu_item_id, quantity, modifiers }) => ({
            line_id,
            menu_item_id,
            quantity,
            modifiers,
          }),
        ),
      }),
    [mode, priceDependency],
  );

  useEffect(() => {
    if (!options.data) return;
    setPickupId(
      (current) => current || options.data?.pickup_locations[0]?.id || "",
    );
    setZoneId(
      (current) => current || options.data?.delivery_zones[0]?.id || "",
    );
  }, [options.data]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!cart.items.length) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const order = await coffeeApi.createOrder(
        {
          fulfillment_mode: mode,
          lines: cart.items.map(
            ({ line_id, menu_item_id, quantity, modifiers }) => ({
              line_id,
              menu_item_id,
              quantity,
              modifiers,
            }),
          ),
          point_redemptions: Object.entries(pointRedemptions)
            .filter(([, points]) => points > 0)
            .map(([venue_id, points]) => ({ venue_id, points })),
          pickup_location_id: mode === "pickup" ? pickupId : null,
          delivery_zone_id: mode === "delivery" ? zoneId : null,
          contact_phone: phone,
          delivery_address: mode === "delivery" ? address : null,
          entrance: mode === "delivery" ? entrance || null : null,
          apartment: mode === "delivery" ? apartment || null : null,
          floor: mode === "delivery" ? floor || null : null,
          customer_comment: comment || null,
          desired_delivery_at:
            mode === "delivery" && desiredAt
              ? new Date(desiredAt).toISOString()
              : null,
          payment_method: paymentMethod,
        },
        createIdempotencyKey(),
      );
      cart.clear();
      navigate(`/orders/${order.id}`, { replace: true });
    } catch (reason) {
      setSubmitError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось оформить заказ"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (!cart.items.length)
    return (
      <Page title="Оформление">
        <EmptyState
          title="Корзина пуста"
          text="Сначала выберите позиции в меню."
        />
      </Page>
    );
  return (
    <Page title="Оформление" eyebrow="Сумму подтверждает сервер">
      {options.loading && <Loader />}
      {options.error && (
        <ErrorState error={options.error} onRetry={options.reload} />
      )}
      {options.data && (
        <form className="order-form" onSubmit={(event) => void submit(event)}>
          <div className="segmented" role="group" aria-label="Способ получения">
            <button
              type="button"
              className={mode === "pickup" ? "is-active" : ""}
              onClick={() => setMode("pickup")}
            >
              Самовывоз
            </button>
            <button
              type="button"
              className={mode === "delivery" ? "is-active" : ""}
              disabled={
                !options.data.delivery_enabled ||
                options.data.delivery_zones.length === 0
              }
              onClick={() => setMode("delivery")}
            >
              Доставка
            </button>
          </div>
          {(!options.data.delivery_enabled ||
            options.data.delivery_zones.length === 0) && (
            <div className="inline-warning" role="status">
              {!options.data.delivery_enabled
                ? "Доставка временно выключена заведением. Самовывоз доступен."
                : "Для доставки ещё не настроены активные зоны. Самовывоз доступен."}
            </div>
          )}
          <Field label="Телефон">
            <input
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              required
              minLength={8}
              placeholder="+7 999 000-00-00"
            />
          </Field>
          {mode === "pickup" ? (
            <fieldset className="location-choice">
              <legend>Точка получения</legend>
              {options.data.pickup_locations.map((location) => (
                <label
                  className={pickupId === location.id ? "is-active" : ""}
                  key={location.id}
                >
                  <input
                    type="radio"
                    name="pickup-location"
                    value={location.id}
                    checked={pickupId === location.id}
                    onChange={() => setPickupId(location.id)}
                    required
                  />
                  <span aria-hidden="true">⌖</span>
                  <span>
                    <strong>{location.name}</strong>
                    <small>{location.address}</small>
                  </span>
                  <b>{location.preparation_minutes} мин.</b>
                </label>
              ))}
              {!options.data.pickup_locations.length && (
                <div className="inline-warning">
                  Точки самовывоза пока не настроены.
                </div>
              )}
            </fieldset>
          ) : (
            <>
              <Field label="Зона доставки">
                <select
                  value={zoneId}
                  onChange={(event) => setZoneId(event.target.value)}
                  required
                >
                  {options.data.delivery_zones.map((zone) => (
                    <option key={zone.id} value={zone.id}>
                      {zone.name} · {formatMoney(zone.fee_minor)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Адрес">
                <input
                  value={address}
                  onChange={(event) => setAddress(event.target.value)}
                  required
                />
              </Field>
              <div className="order-form__row">
                <Field label="Подъезд">
                  <input
                    value={entrance}
                    onChange={(event) => setEntrance(event.target.value)}
                  />
                </Field>
                <Field label="Квартира">
                  <input
                    value={apartment}
                    onChange={(event) => setApartment(event.target.value)}
                  />
                </Field>
                <Field label="Этаж">
                  <input
                    value={floor}
                    onChange={(event) => setFloor(event.target.value)}
                  />
                </Field>
              </div>
              {options.data.scheduling_allowed && (
                <Field
                  label="Желаемое время"
                  hint={`Не раньше чем через ${options.data.earliest_preparation_minutes} мин.`}
                >
                  <input
                    type="datetime-local"
                    value={desiredAt}
                    onChange={(event) => setDesiredAt(event.target.value)}
                  />
                </Field>
              )}
            </>
          )}
          <Field label="Комментарий">
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={3}
            />
          </Field>
          <Field label="Оплата при получении">
            <select
              value={paymentMethod}
              onChange={(event) =>
                setPaymentMethod(
                  event.target.value as "cash" | "card_on_receipt",
                )
              }
            >
              <option value="card_on_receipt">Картой</option>
              <option value="cash">Наличными</option>
            </select>
          </Field>
          {price.data &&
            wallets.data &&
            wallets.data.total_balance_points > 0 && (
              <Panel>
                <h2>Оплата баллами</h2>
                <p className="muted">
                  Баланс: {wallets.data.total_balance_points}. Сервер повторно
                  проверит лимит для каждой части заказа.
                </p>
                {price.data.venues.map((venue) => {
                  const wallet =
                    wallets.data?.mode === "shared"
                      ? wallets.data.entries[0]
                      : wallets.data?.entries.find(
                          (entry) => entry.venue?.id === venue.venue_id,
                        );
                  const maximumByOrder = Math.floor(
                    (venue.total_minor * wallets.data!.max_redemption_percent) /
                      100 /
                      Math.max(wallets.data!.point_value_minor, 1),
                  );
                  const maximum = Math.min(
                    wallet?.balance_points ?? 0,
                    maximumByOrder,
                  );
                  return (
                    <Field
                      key={venue.venue_id}
                      label={`Баллы · ${venue.lines[0]?.item_name ?? "заведение"}`}
                      hint={`Доступно для этой части: до ${maximum}`}
                    >
                      <input
                        type="number"
                        min={0}
                        max={maximum}
                        value={pointRedemptions[venue.venue_id] ?? 0}
                        onChange={(event) =>
                          setPointRedemptions({
                            ...pointRedemptions,
                            [venue.venue_id]: Math.max(
                              0,
                              Math.min(maximum, Number(event.target.value)),
                            ),
                          })
                        }
                      />
                    </Field>
                  );
                })}
              </Panel>
            )}
          <Panel className="cart-total">
            <span>Товары после скидок</span>
            <strong>
              {price.data ? formatMoney(price.data.total_minor) : "Расчёт…"}
            </strong>
            {mode === "delivery" && (
              <small>
                Стоимость доставки будет добавлена по выбранной зоне.
              </small>
            )}
          </Panel>
          {price.error && (
            <ErrorState error={price.error} onRetry={price.reload} compact />
          )}
          {submitError && <ErrorState error={submitError} compact />}
          <Button type="submit" disabled={submitting || !price.data}>
            {submitting ? "Создаём заказ…" : "Оформить заказ"}
          </Button>
        </form>
      )}
    </Page>
  );
}

export function OrdersPage() {
  const resource = useResource(() => coffeeApi.getOrders());
  return (
    <Page
      title="Мои заказы"
      action={
        <Link className="button button--secondary" to="/menu">
          В меню
        </Link>
      }
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="card-list">
            {resource.data.items.map((order) => (
              <Link
                className="plain-link"
                key={order.id}
                to={`/orders/${order.id}`}
              >
                <OrderSummary order={order} />
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Заказов пока нет"
            text="Первый заказ можно собрать в меню."
          />
        ))}
    </Page>
  );
}

export function OrderDetailPage() {
  const { orderId = "" } = useParams();
  const resource = useResource(() => coffeeApi.getOrder(orderId), [orderId]);
  const [actionError, setActionError] = useState<Error | null>(null);
  const cancel = async () => {
    const reason = window.prompt("Почему отменяете заказ?");
    if (!reason) return;
    try {
      await coffeeApi.cancelOrder(orderId, reason);
      await resource.reload();
    } catch (value) {
      setActionError(
        value instanceof Error ? value : new Error("Не удалось отменить заказ"),
      );
    }
  };
  return (
    <Page
      title={resource.data ? `Заказ №${resource.data.number}` : "Заказ"}
      action={
        <Link className="button button--secondary" to="/orders">
          Все заказы
        </Link>
      }
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {actionError && <ErrorState error={actionError} compact />}
      {resource.data && (
        <div className="card-list">
          <OrderSummary order={resource.data} />
          {resource.data.suborders.map((suborder) => (
            <Panel key={suborder.id}>
              <div className="order-card__head">
                <h2>{suborder.venue_name}</h2>
                <Badge tone={statusTone(suborder.status)}>
                  {statusLabels[suborder.status]}
                </Badge>
              </div>
              {suborder.lines.map((line) => (
                <div className="order-line-snapshot" key={line.id}>
                  <span>
                    {line.quantity} × {line.name}
                    <small>
                      {line.modifiers
                        .map((modifier) => modifier.name)
                        .join(", ")}
                    </small>
                  </span>
                  <strong>{formatMoney(line.total_minor)}</strong>
                </div>
              ))}
            </Panel>
          ))}
          <Panel>
            <h2>История</h2>
            {resource.data.events.map((event) => (
              <div className="order-event" key={event.id}>
                <span>{statusLabels[event.to_status]}</span>
                <small>{formatDateTime(event.created_at)}</small>
              </div>
            ))}
          </Panel>
          {["new", "confirmed", "preparing"].includes(resource.data.status) && (
            <Button variant="danger" onClick={() => void cancel()}>
              Отменить заказ
            </Button>
          )}
        </div>
      )}
    </Page>
  );
}

export function StaffOrdersPage() {
  const resource = useResource(coffeeApi.getStaffOrders);
  const couriers = useResource(coffeeApi.getCourierOptions);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<OrderStatus | "">("");
  const [busy, setBusy] = useState("");
  const [actionError, setActionError] = useState<Error | null>(null);
  const [courierByOrder, setCourierByOrder] = useState<Record<string, string>>(
    {},
  );
  const advanceOrder = async (order: CustomerOrder) => {
    const target = getNextStaffStatus(order);
    if (!target) return;
    setBusy(order.id);
    setActionError(null);
    try {
      await coffeeApi.transitionOrder(order.id, target);
      await resource.reload();
    } catch (value) {
      setActionError(
        value instanceof Error ? value : new Error("Не удалось изменить заказ"),
      );
    } finally {
      setBusy("");
    }
  };
  const assignCourier = async (orderId: string) => {
    const courierId = courierByOrder[orderId];
    if (!courierId) return;
    setBusy(orderId);
    setActionError(null);
    try {
      await coffeeApi.assignCourier(orderId, courierId);
      await resource.reload();
    } catch (value) {
      setActionError(
        value instanceof Error
          ? value
          : new Error("Не удалось назначить курьера"),
      );
    } finally {
      setBusy("");
    }
  };
  const groups = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (resource.data?.items ?? []).filter((order) => {
      if (status && order.status !== status) return false;
      if (!normalized) return true;
      return [
        String(order.number),
        order.contact_phone,
        order.delivery_address,
        ...order.suborders.flatMap((suborder) => [
          suborder.venue_name,
          ...suborder.lines.map((line) => line.name),
        ]),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized));
    });
  }, [query, resource.data, status]);
  return (
    <Page title="Заказы" eyebrow="Очередь кухни и выдачи">
      <Panel>
        <div className="filter-grid">
          <Field label="Поиск">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Номер, телефон, адрес, заведение или товар"
            />
          </Field>
          <Field label="Статус">
            <select
              value={status}
              onChange={(event) =>
                setStatus(event.target.value as OrderStatus | "")
              }
            >
              <option value="">Все</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {actionError && <ErrorState error={actionError} compact />}
      {resource.data &&
        (groups.length ? (
          <div className="card-list">
            {groups.map((order) => (
              <Panel className="order-card" key={order.id}>
                <Link className="plain-link" to={`/staff/orders/${order.id}`}>
                  <OrderSummary order={order} embedded />
                </Link>
                {order.suborders.map((suborder) => (
                  <p key={suborder.id}>
                    {suborder.venue_name}: {statusLabels[suborder.status]}
                  </p>
                ))}
                {getNextStaffStatus(order) && (
                  <Button
                    disabled={busy === order.id}
                    onClick={() => void advanceOrder(order)}
                  >
                    Следующий этап: {statusLabels[getNextStaffStatus(order)!]}
                  </Button>
                )}
                {order.status === "waiting_for_courier" && (
                  <div className="form-grid">
                    <Field label="Назначить курьера">
                      <select
                        value={courierByOrder[order.id] ?? ""}
                        onChange={(event) =>
                          setCourierByOrder((value) => ({
                            ...value,
                            [order.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">Выберите курьера</option>
                        {(couriers.data?.items ?? []).map((courier) => (
                          <option key={courier.id} value={courier.id}>
                            {courier.display_name}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Button
                      disabled={busy === order.id || !courierByOrder[order.id]}
                      onClick={() => void assignCourier(order.id)}
                    >
                      Назначить
                    </Button>
                  </div>
                )}
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Очередь пуста"
            text="Новые заказы появятся здесь автоматически."
          />
        ))}
    </Page>
  );
}

export function StaffOrderDetailPage() {
  const { orderId = "" } = useParams();
  const resource = useResource(
    () => coffeeApi.getStaffOrder(orderId),
    [orderId],
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const transition = async (
    target: OrderStatus,
    suborderId?: string,
    reason: string | null = null,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const comment =
        window.prompt("Комментарий к изменению (необязательно)")?.trim() ||
        null;
      if (suborderId) {
        await coffeeApi.transitionSuborder(suborderId, target, reason, comment);
      } else {
        await coffeeApi.transitionOrder(orderId, target, reason, comment);
      }
      await resource.reload();
    } catch (value) {
      setError(
        value instanceof Error ? value : new Error("Не удалось изменить заказ"),
      );
    } finally {
      setBusy(false);
    }
  };
  const cancel = () => {
    const reason = window.prompt("Причина отмены заказа")?.trim();
    if (reason) void transition("cancelled", undefined, reason);
  };
  const order = resource.data;
  return (
    <Page
      title={order ? `Заказ №${order.number}` : "Заказ"}
      eyebrow="Состав, подзаказы и история"
      action={
        <Link className="button button--secondary" to="/staff/orders">
          К списку
        </Link>
      }
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <ErrorState error={error} compact />}
      {order && (
        <>
          <OrderSummary order={order} />
          <Panel>
            <h2>Клиент и получение</h2>
            <p>{order.contact_phone}</p>
            <p>
              {order.delivery_address ??
                order.pickup_address ??
                order.pickup_name}
            </p>
            {order.customer_comment && (
              <p className="muted">{order.customer_comment}</p>
            )}
          </Panel>
          {order.suborders.map((suborder) => {
            const next = getNextStaffStatusFor(
              suborder.status,
              order.fulfillment_mode,
            );
            return (
              <Panel key={suborder.id}>
                <div className="order-card__head">
                  <h2>{suborder.venue_name}</h2>
                  <Badge tone={statusTone(suborder.status)}>
                    {statusLabels[suborder.status]}
                  </Badge>
                </div>
                {suborder.lines.map((line) => (
                  <div className="order-line-snapshot" key={line.id}>
                    <span>
                      {line.quantity} × {line.name}
                      <small>
                        {line.modifiers.map((value) => value.name).join(", ")}
                      </small>
                    </span>
                    <strong>{formatMoney(line.total_minor)}</strong>
                  </div>
                ))}
                {next && (
                  <Button
                    disabled={busy}
                    onClick={() => void transition(next, suborder.id)}
                  >
                    Подзаказ: {statusLabels[next]}
                  </Button>
                )}
              </Panel>
            );
          })}
          <Panel>
            <h2>История статусов</h2>
            {order.events.map((event) => (
              <div className="order-event" key={event.id}>
                <span>
                  {statusLabels[event.to_status]}
                  {event.reason ? ` · ${event.reason}` : ""}
                  {event.comment ? ` · ${event.comment}` : ""}
                </span>
                <small>{formatDateTime(event.created_at)}</small>
              </div>
            ))}
          </Panel>
          {getNextStaffStatus(order) && (
            <Button
              disabled={busy}
              onClick={() => void transition(getNextStaffStatus(order)!)}
            >
              Весь заказ: {statusLabels[getNextStaffStatus(order)!]}
            </Button>
          )}
          {!["delivered", "cancelled"].includes(order.status) && (
            <Button variant="danger" disabled={busy} onClick={cancel}>
              Отменить заказ
            </Button>
          )}
        </>
      )}
    </Page>
  );
}

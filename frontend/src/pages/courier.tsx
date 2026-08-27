import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { coffeeApi } from "../api/client";
import type { CourierOrder, OrderStatus } from "../api/types";
import {
  Button,
  EmptyState,
  ErrorState,
  Loader,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { formatDateTime } from "../utils/format";

const labels: Record<OrderStatus, string> = {
  new: "Новый",
  confirmed: "Подтверждён",
  preparing: "Готовится",
  ready: "Готов",
  waiting_for_courier: "Ожидает курьера",
  courier_assigned: "Назначен",
  picked_up: "Получен",
  in_transit: "В пути",
  delivered: "Доставлен",
  cancelled: "Отменён",
};

function OrderCard({
  order,
  mine,
  busy,
  onClaim,
}: {
  order: CourierOrder;
  mine: boolean;
  busy: boolean;
  onClaim: () => void;
}) {
  return (
    <Panel className="order-card">
      <div className="row-between">
        <strong>Заказ №{order.number}</strong>
        <span>{labels[order.status]}</span>
      </div>
      <p>{order.venue_names.join(" · ") || "Точка выдачи"}</p>
      <small>
        {order.delivery_zone_name || "Зона не указана"} ·{" "}
        {formatDateTime(order.created_at)}
      </small>
      {mine ? (
        <Link
          className="button button--secondary"
          to={`/courier/orders/${order.id}`}
        >
          Открыть маршрут
        </Link>
      ) : (
        <Button disabled={busy} onClick={onClaim}>
          Принять заказ
        </Button>
      )}
    </Panel>
  );
}

function CourierList({ mine }: { mine: boolean }) {
  const resource = useResource(
    mine ? coffeeApi.getMyCourierOrders : coffeeApi.getAvailableCourierOrders,
    [mine],
  );
  const [busy, setBusy] = useState("");
  const claim = async (orderId: string) => {
    setBusy(orderId);
    try {
      await coffeeApi.claimCourierOrder(orderId);
      await resource.reload();
    } finally {
      setBusy("");
    }
  };
  return (
    <Page
      title={mine ? "Мои доставки" : "Доступные заказы"}
      eyebrow={mine ? "Назначенные вам" : "Без раскрытия данных клиента"}
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="card-list">
            {resource.data.items.map((order) => (
              <OrderCard
                key={order.id}
                order={order}
                mine={mine}
                busy={busy === order.id}
                onClaim={() => void claim(order.id)}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title={mine ? "Активных доставок нет" : "Свободных заказов нет"}
            text="Список обновится при следующем открытии страницы."
          />
        ))}
    </Page>
  );
}

export function CourierAvailablePage() {
  return <CourierList mine={false} />;
}

export function CourierMinePage() {
  return <CourierList mine />;
}

export function CourierOrderPage() {
  const { orderId = "" } = useParams();
  const resource = useResource(
    () => coffeeApi.getCourierOrder(orderId),
    [orderId],
  );
  const [busy, setBusy] = useState(false);
  const run = async (
    action: "claim" | "decline" | "pickup" | "in-transit" | "delivered",
  ) => {
    setBusy(true);
    try {
      if (action === "claim") await coffeeApi.claimCourierOrder(orderId);
      else if (action === "decline")
        await coffeeApi.declineCourierOrder(orderId);
      else await coffeeApi.transitionCourierOrder(orderId, action);
      await resource.reload();
    } finally {
      setBusy(false);
    }
  };
  const order = resource.data;
  return (
    <Page
      title={order ? `Заказ №${order.number}` : "Доставка"}
      eyebrow="Маршрут курьера"
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {order && (
        <div className="stack">
          <Panel>
            <h2>{labels[order.status]}</h2>
            <p>{order.venue_names.join(" · ")}</p>
            {order.delivery_address ? (
              <>
                <p>
                  <strong>{order.customer_name}</strong>
                </p>
                <p>{order.delivery_address}</p>
                <p>
                  {[
                    order.entrance && `подъезд ${order.entrance}`,
                    order.apartment && `кв. ${order.apartment}`,
                    order.floor && `этаж ${order.floor}`,
                  ]
                    .filter(Boolean)
                    .join(", ")}
                </p>
                <a href={`tel:${order.contact_phone}`}>{order.contact_phone}</a>
                {order.customer_comment && <p>{order.customer_comment}</p>}
              </>
            ) : (
              <p>Адрес и телефон станут доступны после принятия заказа.</p>
            )}
          </Panel>
          {order.status === "waiting_for_courier" && (
            <Button disabled={busy} onClick={() => void run("claim")}>
              Принять заказ
            </Button>
          )}
          {order.status === "courier_assigned" && (
            <>
              <Button disabled={busy} onClick={() => void run("pickup")}>
                Заказ получен
              </Button>
              <Button
                variant="danger"
                disabled={busy}
                onClick={() => void run("decline")}
              >
                Отказаться до получения
              </Button>
            </>
          )}
          {order.status === "picked_up" && (
            <Button disabled={busy} onClick={() => void run("in-transit")}>
              Выехал к клиенту
            </Button>
          )}
          {order.status === "in_transit" && (
            <Button disabled={busy} onClick={() => void run("delivered")}>
              Заказ доставлен
            </Button>
          )}
        </div>
      )}
    </Page>
  );
}

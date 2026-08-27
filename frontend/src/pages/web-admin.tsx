import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { coffeeApi } from "../api/client";
import type { NamedMetric } from "../api/types";
import {
  EmptyState,
  ErrorState,
  Loader,
  Metric,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { formatMoney } from "../utils/format";

function BarList({
  items,
  valueLabel = (item) => String(item.count),
}: {
  items: NamedMetric[];
  valueLabel?: (item: NamedMetric) => string;
}) {
  const maximum = Math.max(1, ...items.map((item) => item.count));
  if (!items.length)
    return (
      <EmptyState title="Пока нет данных" text="Выберите другой период." />
    );
  return (
    <div className="analytics-bars">
      {items.map((item) => (
        <div
          className="analytics-bars__row"
          key={`${item.id ?? "snapshot"}-${item.name}`}
        >
          <div>
            <strong>{item.name}</strong>
            <span>{valueLabel(item)}</span>
          </div>
          <div className="analytics-bars__track" aria-hidden="true">
            <span
              style={{ width: `${Math.max(3, (item.count / maximum) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function AdminAnalyticsPage() {
  const [days, setDays] = useState(30);
  const resource = useResource(() => coffeeApi.getAdminAnalytics(days), [days]);
  const maximumOrders = useMemo(
    () =>
      Math.max(
        1,
        ...(resource.data?.orders_by_day ?? []).map((item) => item.orders),
      ),
    [resource.data],
  );
  return (
    <Page title="Аналитика" eyebrow="Только агрегаты PostgreSQL">
      <Panel>
        <div className="section-heading">
          <h2>Период</h2>
          <div className="chip-row chip-row--compact">
            {[7, 30, 90].map((value) => (
              <button
                className={`chip ${days === value ? "is-active" : ""}`}
                key={value}
                onClick={() => setDays(value)}
              >
                {value} дней
              </button>
            ))}
          </div>
        </div>
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <div className="metrics-grid metrics-grid--admin">
            <Metric
              value={resource.data.customers.active_customers}
              label="активных клиентов"
            />
            <Metric
              value={resource.data.customers.repeat_customers}
              label="повторных клиентов"
            />
            <Metric
              value={`+${resource.data.loyalty.accrued_points}`}
              label="начислено баллов"
              tone="accent"
            />
            <Metric
              value={`−${resource.data.loyalty.redeemed_points}`}
              label="списано баллов"
            />
            <Metric
              value={resource.data.subscriptions.uses}
              label="использований абонементов"
            />
            <Metric
              value={resource.data.receipts.created}
              label="ручных чеков"
            />
            <Metric
              value={resource.data.delivery.completed}
              label="доставок завершено"
            />
            <Metric
              value={resource.data.receipts.suspicious}
              label="подозрительных чеков"
              tone="warning"
            />
          </div>
          <Panel>
            <h2>Заказы по дням</h2>
            <div
              className="daily-chart"
              aria-label="Количество заказов по дням"
            >
              {resource.data.orders_by_day.map((item) => (
                <div
                  className="daily-chart__column"
                  key={item.day}
                  title={`${item.day}: ${item.orders}`}
                >
                  <span
                    style={{
                      height: `${Math.max(3, (item.orders / maximumOrders) * 100)}%`,
                    }}
                    aria-hidden="true"
                  />
                  <small>{item.day.slice(5)}</small>
                </div>
              ))}
            </div>
          </Panel>
          <div className="analytics-grid">
            <Panel>
              <h2>По заведениям</h2>
              <BarList
                items={resource.data.orders_by_venue}
                valueLabel={(item) =>
                  `${item.count} · ${formatMoney(item.amount_minor)}`
                }
              />
            </Panel>
            <Panel>
              <h2>Популярные позиции</h2>
              <BarList items={resource.data.popular_items} />
            </Panel>
            <Panel>
              <h2>Использование акций</h2>
              <BarList
                items={resource.data.promotion_usage}
                valueLabel={(item) =>
                  `${item.count} · скидка ${formatMoney(item.amount_minor)}`
                }
              />
            </Panel>
            <Panel>
              <h2>Активность сотрудников</h2>
              <BarList
                items={resource.data.employee_activity}
                valueLabel={(item) => `${item.count} действий`}
              />
            </Panel>
          </div>
        </>
      )}
    </Page>
  );
}

const helpSections = [
  [
    "Добавить сотрудника",
    "Откройте «Сотрудники», создайте приглашение, выберите роль и только необходимые права.",
    "/admin/staff",
  ],
  [
    "Создать акцию",
    "В «Контенте» создайте акцию, затем настройте период, приоритет и правила расчёта в «Ценообразовании».",
    "/admin/menu",
  ],
  [
    "Добавить товар и modifiers",
    "Создайте категорию и товар в «Контенте», затем свяжите группы модификаторов с нужными позициями.",
    "/admin/menu",
  ],
  [
    "Найти клиента",
    "Ищите по имени, username, Telegram ID или короткому коду карты. В карточке доступны история и безопасные действия.",
    "/admin/users",
  ],
  [
    "Начислить бонус",
    "Для одного клиента используйте корректировку с preview. Для списка — «Массовые бонусы» с обязательным подтверждением.",
    "/admin/bulk-bonus",
  ],
  [
    "Обработать заказ",
    "В «Заказах» откройте заказ, проверьте состав и последовательно меняйте разрешённые статусы.",
    "/staff/orders",
  ],
  [
    "Назначить курьера",
    "В разделе «Доставка» выберите доступного курьера. Курьер увидит только разрешённые данные заказа.",
    "/admin/delivery",
  ],
  [
    "Создать абонемент",
    "Создайте шаблон, ограничьте его заведениями/категориями/товарами и выдайте клиенту.",
    "/admin/subscriptions",
  ],
  [
    "Проверить чек",
    "В «Чеках» видны фото, правки и риск-флаги. История ревизий не перезаписывается.",
    "/staff/receipts",
  ],
  [
    "Проверить suspicious event",
    "Откройте «События» и примените фильтр подозрительных действий. Записи аудита неизменяемы.",
    "/admin/events",
  ],
] as const;

export function AdminHelpPage() {
  return (
    <Page title="Помощь" eyebrow="Короткие рабочие инструкции">
      <Panel>
        <p className="muted">
          Все критические действия проверяются backend. Не передавайте
          сессионный токен, Telegram init data и доступ к аккаунту другим людям.
        </p>
      </Panel>
      <div className="help-grid">
        {helpSections.map(([title, text, to]) => (
          <Panel key={title}>
            <h2>{title}</h2>
            <p>{text}</p>
            <Link className="text-link" to={to}>
              Открыть раздел →
            </Link>
          </Panel>
        ))}
      </div>
    </Page>
  );
}

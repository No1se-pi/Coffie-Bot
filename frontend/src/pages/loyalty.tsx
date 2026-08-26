import { useMemo, useState, type FormEvent } from "react";
import { coffeeApi } from "../api/client";
import type { CustomerWalletEntry } from "../api/types";
import {
  BirthdayFields,
  birthdayDaysInMonth,
  formatBirthday,
} from "../components/BirthdayFields";
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Loader,
  Metric,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";
import { formatDate, formatMoney } from "../utils/format";

function walletName(entry: CustomerWalletEntry): string {
  return entry.venue?.name ?? "Общий кошелёк";
}

export function LoyaltyPage() {
  const wallets = useResource(coffeeApi.getMyWallets);
  const birthday = useResource(coffeeApi.getMyBirthday);
  const [month, setMonth] = useState("");
  const [day, setDay] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nearestExpiration = useMemo(() => {
    // API order is not a guarantee; this comparison is display-only and never
    // decides which immutable point lot the backend spends via FIFO.
    return (
      wallets.data?.entries
        .filter((entry) => entry.expiring_points > 0 && entry.expires_at)
        .sort(
          (left, right) =>
            new Date(left.expires_at ?? 0).getTime() -
            new Date(right.expires_at ?? 0).getTime(),
        )[0] ?? null
    );
  }, [wallets.data]);

  const changeMonth = (value: string) => {
    setMonth(value);
    if (Number(day) > birthdayDaysInMonth(Number(value))) setDay("");
    setError(null);
  };

  const saveBirthday = async (event: FormEvent) => {
    event.preventDefault();
    const value = { month: Number(month), day: Number(day) };
    if (
      value.month < 1 ||
      value.month > 12 ||
      value.day < 1 ||
      value.day > birthdayDaysInMonth(value.month)
    ) {
      setError("Выберите корректные день и месяц");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.setMyBirthday(value);
      await birthday.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить дату рождения",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Page title="Баллы и профиль" eyebrow="Программа лояльности">
      {wallets.loading && <Loader label="Загружаем кошельки…" />}
      {wallets.error && (
        <ErrorState error={wallets.error} onRetry={wallets.reload} />
      )}
      {wallets.data && (
        <>
          <Panel>
            <div className="section-heading">
              <div>
                <p className="eyebrow">Баланс</p>
                <h2>{wallets.data.total_balance_points} баллов</h2>
              </div>
              <Badge tone="accent">
                {wallets.data.mode === "shared"
                  ? "Общий кошелёк"
                  : "По заведениям"}
              </Badge>
            </div>
            <p>
              1 балл = {formatMoney(wallets.data.point_value_minor)} скидки.
              Баллами можно оплатить до {wallets.data.max_redemption_percent}%
              стоимости заказа.
            </p>
            {wallets.data.mode === "separate" && (
              <p className="muted">
                В смешанном заказе лимит и баланс считаются отдельно для каждого
                заведения.
              </p>
            )}
          </Panel>

          {nearestExpiration && (
            <div className="inline-warning" role="status">
              Ближайшее сгорание: {nearestExpiration.expiring_points} баллов из
              «{walletName(nearestExpiration)}» —{" "}
              {formatDate(nearestExpiration.expires_at)}.
            </div>
          )}

          {wallets.data.entries.length ? (
            <div className="card-list" aria-label="Кошельки">
              {wallets.data.entries.map((entry) => (
                <Panel key={entry.id}>
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">
                        {entry.venue ? "Заведение" : "Вся организация"}
                      </p>
                      <h2>{walletName(entry)}</h2>
                    </div>
                    <div className="tag-row">
                      {entry.venue?.available === false && (
                        <Badge>Заведение недоступно</Badge>
                      )}
                      <strong>{entry.balance_points} баллов</strong>
                    </div>
                  </div>
                  <p className="muted">
                    {entry.expiring_points > 0 && entry.expires_at
                      ? `${entry.expiring_points} баллов сгорят ${formatDate(entry.expires_at)}`
                      : "Ближайшего сгорания нет"}
                  </p>
                </Panel>
              ))}
            </div>
          ) : (
            <EmptyState
              title="Кошельков пока нет"
              text="Баланс появится после первого начисления."
            />
          )}
        </>
      )}

      {birthday.loading && <Loader label="Загружаем профиль…" />}
      {birthday.error && (
        <ErrorState error={birthday.error} onRetry={birthday.reload} />
      )}
      {birthday.data && (
        <Panel>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Профиль</p>
              <h2>День рождения</h2>
            </div>
            {birthday.data.birthday && birthday.data.locked && (
              <Badge tone="success">Дата зафиксирована</Badge>
            )}
          </div>
          {birthday.data.birthday ? (
            <>
              <Metric
                value={formatBirthday(birthday.data.birthday)}
                label="день и месяц"
                tone="accent"
              />
              <p className="muted">
                Изменить зафиксированную дату может только администратор.
              </p>
              {birthday.data.birthday.month === 2 &&
                birthday.data.birthday.day === 29 && (
                  <p className="muted">
                    В невисокосный год датой предложения станет 28 февраля.
                  </p>
                )}
              {birthday.data.offer?.enabled ? (
                <div className="inline-success">
                  <strong>
                    Предложение ко дню рождения: скидка{" "}
                    {birthday.data.offer.discount_percent}%.
                  </strong>
                  <p>
                    {birthday.data.offer.window_days} дн. ·{" "}
                    {birthday.data.offer.stackable
                      ? "складывается с другими скидками"
                      : "не складывается с другими скидками"}
                  </p>
                  <p>
                    Заведения:{" "}
                    {birthday.data.offer.eligible_venues.length
                      ? birthday.data.offer.eligible_venues
                          .map((venue) => venue.name)
                          .join(", ")
                      : "все активные заведения"}
                  </p>
                </div>
              ) : birthday.data.offer ? (
                <p className="muted">
                  Предложение ко дню рождения сейчас выключено.
                </p>
              ) : null}
            </>
          ) : (
            <>
              <p>
                Укажите только день и месяц — год рождения не нужен. После
                первого сохранения дата будет зафиксирована.
              </p>
              <form
                className="form"
                onSubmit={(event) => void saveBirthday(event)}
              >
                <BirthdayFields
                  month={month}
                  day={day}
                  disabled={saving}
                  onMonthChange={changeMonth}
                  onDayChange={(value) => {
                    setDay(value);
                    setError(null);
                  }}
                />
                {error && (
                  <div className="inline-error" role="alert">
                    {error}
                  </div>
                )}
                <Button type="submit" disabled={saving || !month || !day}>
                  {saving ? "Сохраняем…" : "Сохранить дату"}
                </Button>
              </form>
            </>
          )}
        </Panel>
      )}
    </Page>
  );
}

import { useContext, useMemo, useState, type FormEvent } from "react";
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
import { AuthContext } from "../auth/AuthContext";
import { requestTelegramContact } from "../telegram";

function walletName(entry: CustomerWalletEntry): string {
  return entry.venue?.name ?? "Общий кошелёк";
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

export function LoyaltyPage() {
  const actor = useContext(AuthContext)?.actor ?? null;
  const wallets = useResource(coffeeApi.getMyWallets);
  const birthday = useResource(coffeeApi.getMyBirthday);
  const identities = useResource(coffeeApi.getMyIdentities);
  const [month, setMonth] = useState("");
  const [day, setDay] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [phoneMessage, setPhoneMessage] = useState<string | null>(null);
  const [phoneError, setPhoneError] = useState<string | null>(null);
  const phoneIdentity = identities.data?.items.find(
    (identity) => identity.provider === "phone" && identity.verified,
  );

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

  const refreshPhone = async (): Promise<boolean> => {
    // Contact is delivered to the bot as a separate Telegram update. Polling
    // bridges that asynchronous hand-off without requesting contact twice.
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (attempt > 0) await wait(600);
      const current = await coffeeApi.getMyIdentities();
      if (
        current.items.some(
          (identity) => identity.provider === "phone" && identity.verified,
        )
      ) {
        await Promise.all([
          identities.reload(),
          wallets.reload(),
          birthday.reload(),
        ]);
        setPhoneMessage(
          "Телефон подключён. Баланс и история прежнего профиля объединены.",
        );
        return true;
      }
    }
    return false;
  };

  const connectPhone = async () => {
    setPhoneBusy(true);
    setPhoneError(null);
    setPhoneMessage(null);
    try {
      const result = await requestTelegramContact();
      if (result === "unsupported") {
        setPhoneError(
          "Откройте профиль внутри Telegram или отправьте боту команду /phone.",
        );
        return;
      }
      if (result === "cancelled") {
        setPhoneMessage("Отправка номера отменена.");
        return;
      }

      setPhoneMessage("Telegram подтвердил номер. Объединяем профиль…");
      if (!(await refreshPhone())) {
        setPhoneMessage(
          "Номер отправлен. Если он не появился, нажмите «Проверить ещё раз» через несколько секунд.",
        );
      }
    } catch (reason) {
      setPhoneError(
        reason instanceof Error
          ? reason.message
          : "Не удалось подключить телефон",
      );
    } finally {
      setPhoneBusy(false);
    }
  };

  const checkPhone = async () => {
    setPhoneBusy(true);
    setPhoneError(null);
    setPhoneMessage("Проверяем обработку номера…");
    try {
      if (!(await refreshPhone())) {
        setPhoneMessage(
          "Номер ещё обрабатывается. Можно повторить проверку через несколько секунд.",
        );
      }
    } catch (reason) {
      setPhoneError(
        reason instanceof Error
          ? reason.message
          : "Не удалось проверить подключение телефона",
      );
    } finally {
      setPhoneBusy(false);
    }
  };

  return (
    <Page title="Профиль" eyebrow="Личные данные и лояльность">
      <Panel className="profile-card">
        <div>
          <p className="eyebrow">Ваш аккаунт</p>
          <h2>{actor?.display_name}</h2>
          <p className="muted">
            Telegram: {actor?.username ? `@${actor.username}` : "подключён"}
          </p>
        </div>
        <div className="profile-identities">
          <Badge tone="success">Telegram подключён</Badge>
          {phoneIdentity ? (
            <Badge tone="success">Телефон {phoneIdentity.subject}</Badge>
          ) : (
            <Badge>Телефон не подключён</Badge>
          )}
          <Badge>MAX — пока недоступен</Badge>
        </div>
        {!phoneIdentity && !identities.loading && (
          <div className="action-row">
            <Button disabled={phoneBusy} onClick={() => void connectPhone()}>
              {phoneBusy ? "Проверяем…" : "Добавить номер из Telegram"}
            </Button>
            {phoneMessage?.startsWith("Номер отправлен") && (
              <Button
                variant="secondary"
                disabled={phoneBusy}
                onClick={() => void checkPhone()}
              >
                Проверить ещё раз
              </Button>
            )}
          </div>
        )}
        {identities.error && (
          <div className="inline-error" role="alert">
            Не удалось загрузить способы входа.
          </div>
        )}
        {phoneMessage && (
          <div className="inline-success" role="status">
            {phoneMessage}
          </div>
        )}
        {phoneError && (
          <div className="inline-error" role="alert">
            {phoneError}
          </div>
        )}
        <small className="muted">
          Номер подтверждает сам Telegram. Если бариста уже создал по нему
          карту, её баланс и история будут объединены автоматически. Интеграция
          MAX пока не включена.
        </small>
      </Panel>
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

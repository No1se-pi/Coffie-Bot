import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { coffeeApi, createIdempotencyKey } from "../api/client";
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

const riskLabels: Record<string, string> = {
  high_amount: "Необычно высокая сумма",
  staff_hour_volume: "Много чеков у сотрудника за час",
  repeated_amount: "Часто повторяется одинаковая сумма",
  customer_day_volume: "Много чеков у одного клиента",
  duplicate_receipt_number: "Повторяется номер чека",
  missing_photo: "Нет обязательной фотографии",
  frequent_staff_cancellations: "Частые отмены чеков сотрудником",
};

export function ReceiptQuickForm({
  userId,
  venueId,
}: {
  userId: string;
  venueId: string | null;
}) {
  const [amount, setAmount] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [key, setKey] = useState(createIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [createdNumber, setCreatedNumber] = useState<string | null>(null);
  const rotate = () => setKey(createIdempotencyKey());
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const amountMinor = Math.round(Number(amount.replace(",", ".")) * 100);
    if (
      !venueId ||
      !file ||
      !Number.isSafeInteger(amountMinor) ||
      amountMinor <= 0
    ) {
      setError(new Error("Выберите точку, укажите сумму и фотографию чека"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const media = await coffeeApi.uploadReceiptMedia(file);
      const receipt = await coffeeApi.createReceipt(
        {
          user_id: userId,
          venue_id: venueId,
          amount_minor: amountMinor,
          image_media_id: media.id,
          receipt_number: null,
          external_id: null,
          fiscal_data: {},
          note: null,
          source: "manual",
        },
        key,
      );
      setCreatedNumber(receipt.id.slice(0, 8));
      setAmount("");
      setFile(null);
      rotate();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось сохранить чек"),
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel>
      <h2>Ручной чек</h2>
      <p className="muted">Быстрый сценарий: сумма, фотография и сохранение.</p>
      <form className="form" onSubmit={(event) => void submit(event)}>
        <Field label="Сумма, ₽">
          <input
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value);
              rotate();
            }}
            inputMode="decimal"
            placeholder="450"
            required
          />
        </Field>
        <Field label="Фотография чека">
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              rotate();
            }}
            required
          />
        </Field>
        <Button type="submit" disabled={busy || !venueId}>
          {busy ? "Сохраняем…" : "Сохранить чек"}
        </Button>
      </form>
      {createdNumber && <p className="notice">Чек {createdNumber} сохранён.</p>}
      {error && <ErrorState error={error} compact />}
    </Panel>
  );
}

export function ReceiptsPage() {
  const resource = useResource(coffeeApi.getReceipts);
  return (
    <Page title="Ручные чеки" eyebrow="История и сигналы проверки">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="card-list">
            {resource.data.items.map((receipt) => (
              <Panel key={receipt.id} className="order-card">
                <div className="row-between">
                  <strong>{receipt.customer_name}</strong>
                  <Badge
                    tone={receipt.status === "active" ? "success" : "danger"}
                  >
                    {receipt.status === "active" ? "Активен" : "Отменён"}
                  </Badge>
                </div>
                <p>
                  {receipt.venue_name} · {formatMoney(receipt.amount_minor)}
                </p>
                <small>{formatDateTime(receipt.created_at)}</small>
                {receipt.risk_flags.length > 0 && (
                  <Badge tone="warning">
                    Сигналов: {receipt.risk_flags.length}
                  </Badge>
                )}
                <Link
                  className="button button--secondary"
                  to={`/staff/receipts/${receipt.id}`}
                >
                  Открыть
                </Link>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Чеков пока нет"
            text="Первый ручной чек появится после сохранения."
          />
        ))}
    </Page>
  );
}

export function ReceiptDetailPage() {
  const { receiptId = "" } = useParams();
  const resource = useResource(
    () => coffeeApi.getReceipt(receiptId),
    [receiptId],
  );
  const [number, setNumber] = useState("");
  const [externalId, setExternalId] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!resource.data) return;
    setNumber(resource.data.receipt_number ?? "");
    setExternalId(resource.data.external_id ?? "");
    setNote(resource.data.note ?? "");
  }, [resource.data]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!resource.data) return;
    setBusy(true);
    try {
      const mediaId = file
        ? (await coffeeApi.uploadReceiptMedia(file)).id
        : resource.data.image_media_id;
      await coffeeApi.editReceipt(receiptId, {
        image_media_id: mediaId,
        receipt_number: number.trim() || null,
        external_id: externalId.trim() || null,
        fiscal_data: resource.data.fiscal_data,
        note: note.trim() || null,
      });
      setFile(null);
      await resource.reload();
    } finally {
      setBusy(false);
    }
  };
  const cancel = async () => {
    setBusy(true);
    try {
      await coffeeApi.cancelReceipt(receiptId);
      await resource.reload();
    } finally {
      setBusy(false);
    }
  };
  const receipt = resource.data;
  return (
    <Page
      title="Карточка чека"
      eyebrow={
        receipt
          ? `${receipt.customer_name} · ${formatMoney(receipt.amount_minor)}`
          : undefined
      }
    >
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {receipt && (
        <div className="stack">
          {receipt.risk_flags.length > 0 && (
            <Panel>
              <h2>Сигналы проверки</h2>
              {receipt.risk_flags.map((flag) => (
                <p key={flag.code}>{riskLabels[flag.code] ?? flag.code}</p>
              ))}
            </Panel>
          )}
          <Panel>
            <h2>Метаданные</h2>
            <form className="form" onSubmit={(event) => void save(event)}>
              <Field label="Номер чека" hint="Можно добавить позже">
                <input
                  value={number}
                  onChange={(event) => setNumber(event.target.value)}
                />
              </Field>
              <Field
                label="External POS ID"
                hint="Для будущей кассовой интеграции"
              >
                <input
                  value={externalId}
                  onChange={(event) => setExternalId(event.target.value)}
                />
              </Field>
              <Field label="Примечание">
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
              </Field>
              <Field label="Заменить фото">
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </Field>
              <Button
                type="submit"
                disabled={busy || receipt.status === "cancelled"}
              >
                Сохранить новую ревизию
              </Button>
            </form>
          </Panel>
          <Panel>
            <h2>История изменений</h2>
            {receipt.revisions.map((revision) => (
              <div className="order-event" key={revision.revision}>
                <span>
                  Ревизия {revision.revision}:{" "}
                  {revision.changed_fields.join(", ")}
                </span>
                <small>{formatDateTime(revision.created_at)}</small>
              </div>
            ))}
          </Panel>
          {receipt.status === "active" && (
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => void cancel()}
            >
              Отменить чек
            </Button>
          )}
        </div>
      )}
    </Page>
  );
}

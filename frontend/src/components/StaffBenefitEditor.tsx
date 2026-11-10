import { useState, type FormEvent } from "react";
import { coffeeApi } from "../api/client";
import type { MenuItem, StaffBenefits } from "../api/types";
import { Button, Field } from "./ui";

export function StaffBenefitEditor({ staffId }: { staffId: string }) {
  const [data, setData] = useState<StaffBenefits | null>(null);
  const [items, setItems] = useState<MenuItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      const [benefits, menu] = await Promise.all([
        coffeeApi.getAdminStaffBenefits(staffId),
        coffeeApi.getMenu(),
      ]);
      setData(benefits);
      setItems(menu.items);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось загрузить бонусы",
      );
    } finally {
      setBusy(false);
    }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!data) return;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      setData(
        await coffeeApi.updateAdminStaffBenefits(staffId, {
          enabled: data.enabled,
          monthly_points: data.monthly_points,
          all_items: data.all_items,
          item_ids: data.item_ids,
        }),
      );
      setMessage("Настройки бонусов сохранены");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить бонусы",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <details
      onToggle={(event) => {
        if (event.currentTarget.open && !data && !busy) void load();
      }}
    >
      <summary>Бонусы сотрудника</summary>
      {error && <p className="inline-error">{error}</p>}
      {data && (
        <form className="form" onSubmit={(event) => void save(event)}>
          <p>
            Остаток: <strong>{data.balance_points}</strong> бонусов. 1 бонус = 1
            ₽. Остаток сгорает в конце месяца.
          </p>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={data.enabled}
              onChange={(e) => setData({ ...data, enabled: e.target.checked })}
            />
            Ежемесячные бонусы
          </label>
          <Field label="Бонусов в месяц">
            <input
              type="number"
              min="1"
              max="1000000"
              value={data.monthly_points}
              onChange={(e) =>
                setData({ ...data, monthly_points: Number(e.target.value) })
              }
            />
          </Field>
          <p className="muted">
            При первом включении начисление происходит сразу. Изменение суммы
            действует со следующего месяца и не повторяет начисление за текущий.
          </p>
          <div className="action-row">
            <Button
              type="button"
              variant={data.all_items ? "primary" : "secondary"}
              onClick={() =>
                setData({ ...data, all_items: true, item_ids: [] })
              }
            >
              Все позиции
            </Button>
            <Button
              type="button"
              variant={!data.all_items ? "primary" : "secondary"}
              onClick={() => setData({ ...data, all_items: false })}
            >
              Выбрать позиции
            </Button>
          </div>
          {!data.all_items &&
            items.map((item) => (
              <label className="checkbox" key={item.id}>
                <input
                  type="checkbox"
                  checked={data.item_ids.includes(item.id)}
                  onChange={(e) =>
                    setData({
                      ...data,
                      item_ids: e.target.checked
                        ? [...data.item_ids, item.id]
                        : data.item_ids.filter((id) => id !== item.id),
                    })
                  }
                />
                {item.name}
              </label>
            ))}
          <Button type="submit" disabled={busy}>
            {busy ? "Сохраняем…" : "Сохранить бонусы"}
          </Button>
          {message && <p role="status">{message}</p>}
        </form>
      )}
    </details>
  );
}

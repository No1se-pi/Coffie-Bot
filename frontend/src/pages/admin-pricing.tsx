import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { coffeeApi } from "../api/client";
import type {
  AdminModifierGroup,
  AdminModifierGroupDraft,
  Promotion,
  PromotionPricingRules,
  PromotionPricingRulesDraft,
} from "../api/types";
import {
  Button,
  ErrorState,
  Field,
  Loader,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";

const emptyOption = () => ({
  name: "",
  price_delta_minor: 0,
  allows_quantity: false,
  max_quantity: 1,
  enabled: true,
  sort_order: 0,
});

function ModifierEditor({
  group,
  venues,
  items,
  onCancel,
  onSaved,
}: {
  group: AdminModifierGroup | null;
  venues: Array<{ id: string; name: string }>;
  items: Array<{ id: string; venue_id?: string; name: string }>;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<AdminModifierGroupDraft>(() => ({
    venue_id: group?.venue_id ?? venues[0]?.id ?? "",
    name: group?.name ?? "",
    description: group?.description ?? "",
    min_selections: group?.min_selections ?? 0,
    max_selections: group?.max_selections ?? 1,
    required: group?.required ?? false,
    enabled: group?.enabled ?? true,
    sort_order: group?.sort_order ?? 0,
    item_ids: group?.item_ids ?? [],
    options: group?.options.map((option) => ({ ...option })) ?? [emptyOption()],
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const venueItems = items.filter((item) => item.venue_id === form.venue_id);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.venue_id || !form.name.trim()) {
      setError("Выберите заведение и укажите название группы");
      return;
    }
    if (form.options.some((option) => !option.name.trim())) {
      setError("У каждой опции должно быть название");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveAdminModifierGroup(group, {
        ...form,
        name: form.name.trim(),
        description: form.description?.trim() || null,
        options: form.options.map((option, index) => ({
          ...option,
          name: option.name.trim(),
          sort_order: index,
        })),
      });
      await onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить модификатор",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel>
      <form className="form" onSubmit={(event) => void save(event)}>
        <h2>{group ? "Редактирование модификатора" : "Новый модификатор"}</h2>
        <div className="form-grid">
          <Field label="Заведение">
            <select
              value={form.venue_id}
              disabled={Boolean(group)}
              onChange={(event) =>
                setForm({ ...form, venue_id: event.target.value, item_ids: [] })
              }
            >
              <option value="">Выберите заведение</option>
              {venues.map((venue) => (
                <option key={venue.id} value={venue.id}>
                  {venue.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Название группы">
            <input
              value={form.name}
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
              placeholder="Например, Молоко"
            />
          </Field>
          <Field label="Минимум выборов">
            <input
              type="number"
              min={0}
              value={form.min_selections}
              onChange={(event) =>
                setForm({ ...form, min_selections: Number(event.target.value) })
              }
            />
          </Field>
          <Field label="Максимум выборов">
            <input
              type="number"
              min={1}
              value={form.max_selections}
              onChange={(event) =>
                setForm({ ...form, max_selections: Number(event.target.value) })
              }
            />
          </Field>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.required}
            onChange={(event) =>
              setForm({
                ...form,
                required: event.target.checked,
                min_selections: event.target.checked
                  ? Math.max(1, form.min_selections)
                  : form.min_selections,
              })
            }
          />
          <span>Обязательный выбор</span>
        </label>
        <fieldset className="pricing-fieldset">
          <legend>Товары с этим модификатором</legend>
          <div className="pricing-check-grid">
            {venueItems.map((item) => (
              <label className="checkbox" key={item.id}>
                <input
                  type="checkbox"
                  checked={form.item_ids.includes(item.id)}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      item_ids: event.target.checked
                        ? [...form.item_ids, item.id]
                        : form.item_ids.filter((id) => id !== item.id),
                    })
                  }
                />
                <span>{item.name}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className="pricing-fieldset">
          <legend>Варианты</legend>
          {form.options.map((option, index) => (
            <div className="pricing-option-row" key={option.id ?? index}>
              <input
                aria-label={`Название варианта ${index + 1}`}
                value={option.name}
                placeholder="Название"
                onChange={(event) => {
                  const options = [...form.options];
                  options[index] = { ...option, name: event.target.value };
                  setForm({ ...form, options });
                }}
              />
              <input
                aria-label={`Доплата варианта ${index + 1}`}
                type="number"
                min={0}
                step="0.01"
                value={option.price_delta_minor / 100}
                onChange={(event) => {
                  const options = [...form.options];
                  options[index] = {
                    ...option,
                    price_delta_minor: Math.round(
                      Number(event.target.value) * 100,
                    ),
                  };
                  setForm({ ...form, options });
                }}
              />
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={option.allows_quantity}
                  onChange={(event) => {
                    const options = [...form.options];
                    options[index] = {
                      ...option,
                      allows_quantity: event.target.checked,
                    };
                    setForm({ ...form, options });
                  }}
                />
                <span>Количество</span>
              </label>
              <input
                aria-label={`Максимальное количество варианта ${index + 1}`}
                type="number"
                min={1}
                max={100}
                disabled={!option.allows_quantity}
                value={option.max_quantity}
                onChange={(event) => {
                  const options = [...form.options];
                  options[index] = {
                    ...option,
                    max_quantity: Math.max(1, Number(event.target.value)),
                  };
                  setForm({ ...form, options });
                }}
              />
              <Button
                type="button"
                variant="ghost"
                disabled={form.options.length === 1}
                onClick={() =>
                  setForm({
                    ...form,
                    options: form.options.filter(
                      (_, optionIndex) => optionIndex !== index,
                    ),
                  })
                }
              >
                Убрать
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="secondary"
            onClick={() =>
              setForm({ ...form, options: [...form.options, emptyOption()] })
            }
          >
            Добавить вариант
          </Button>
        </fieldset>
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
        <div className="action-row">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Отмена
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function defaultPromotionRules(): PromotionPricingRulesDraft {
  return {
    pricing_enabled: false,
    action_type: null,
    discount_value: null,
    priority: 0,
    stackable: false,
    active_from_date: null,
    active_to_date: null,
    active_weekdays: [],
    active_time_from: null,
    active_time_to: null,
    fulfillment_modes: [],
    customer_birthday_only: false,
    minimum_order_minor: 0,
    category_ids: [],
    menu_item_ids: [],
  };
}

function PromotionRuleEditor({
  promotion,
  rules,
  categories,
  items,
  onSaved,
}: {
  promotion: Promotion;
  rules: PromotionPricingRules;
  categories: Array<{ id: string; venue_id?: string; name: string }>;
  items: Array<{ id: string; venue_id?: string; name: string }>;
  onSaved: (value: PromotionPricingRules) => void;
}) {
  const [form, setForm] = useState<PromotionPricingRulesDraft>({
    ...defaultPromotionRules(),
    ...rules,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const percent = form.action_type === "percent_discount";
  const discountDisplay =
    form.discount_value == null ? "" : String(form.discount_value / 100);
  const toggleId = (
    key: "category_ids" | "menu_item_ids",
    id: string,
    checked: boolean,
  ) => {
    setForm({
      ...form,
      [key]: checked
        ? [...form[key], id]
        : form[key].filter((value) => value !== id),
    });
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const value = await coffeeApi.savePromotionPricingRules(
        promotion.id,
        form,
      );
      onSaved(value);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить правила акции",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Panel>
      <form className="form" onSubmit={(event) => void save(event)}>
        <h2>Расчёт скидки: {promotion.title}</h2>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.pricing_enabled}
            onChange={(event) =>
              setForm({ ...form, pricing_enabled: event.target.checked })
            }
          />
          <span>Участвует в расчёте корзины</span>
        </label>
        <div className="form-grid">
          <Field label="Тип скидки">
            <select
              value={form.action_type ?? ""}
              onChange={(event) =>
                setForm({
                  ...form,
                  action_type: (event.target.value ||
                    null) as PromotionPricingRulesDraft["action_type"],
                  discount_value: null,
                })
              }
            >
              <option value="">Информационная акция</option>
              <option value="percent_discount">Процент</option>
              <option value="fixed_discount">Сумма</option>
            </select>
          </Field>
          <Field label={percent ? "Скидка, %" : "Скидка, ₽"}>
            <input
              type="number"
              min={0}
              step="0.01"
              disabled={!form.action_type}
              value={discountDisplay}
              onChange={(event) =>
                setForm({
                  ...form,
                  discount_value:
                    Math.round(Number(event.target.value) * 100) || null,
                })
              }
            />
          </Field>
          <Field label="Приоритет">
            <input
              type="number"
              value={form.priority}
              onChange={(event) =>
                setForm({ ...form, priority: Number(event.target.value) })
              }
            />
          </Field>
          <Field label="Минимальная сумма, ₽">
            <input
              type="number"
              min={0}
              step="0.01"
              value={form.minimum_order_minor / 100}
              onChange={(event) =>
                setForm({
                  ...form,
                  minimum_order_minor: Math.round(
                    Number(event.target.value) * 100,
                  ),
                })
              }
            />
          </Field>
          <Field label="Время от">
            <input
              type="time"
              value={form.active_time_from?.slice(0, 5) ?? ""}
              onChange={(event) =>
                setForm({
                  ...form,
                  active_time_from: event.target.value || null,
                })
              }
            />
          </Field>
          <Field label="Время до">
            <input
              type="time"
              value={form.active_time_to?.slice(0, 5) ?? ""}
              onChange={(event) =>
                setForm({ ...form, active_time_to: event.target.value || null })
              }
            />
          </Field>
        </div>
        <div className="pricing-check-grid">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={form.stackable}
              onChange={(event) =>
                setForm({ ...form, stackable: event.target.checked })
              }
            />
            <span>Суммируется с другими</span>
          </label>
          {(["pickup", "delivery"] as const).map((mode) => (
            <label className="checkbox" key={mode}>
              <input
                type="checkbox"
                checked={form.fulfillment_modes.includes(mode)}
                onChange={(event) =>
                  setForm({
                    ...form,
                    fulfillment_modes: event.target.checked
                      ? [...form.fulfillment_modes, mode]
                      : form.fulfillment_modes.filter(
                          (value) => value !== mode,
                        ),
                  })
                }
              />
              <span>{mode === "pickup" ? "Самовывоз" : "Доставка"}</span>
            </label>
          ))}
        </div>
        <fieldset className="pricing-fieldset">
          <legend>Применять только к выбранным категориям или товарам</legend>
          <div className="pricing-check-grid">
            {categories
              .filter((value) => value.venue_id === rules.venue_id)
              .map((category) => (
                <label className="checkbox" key={category.id}>
                  <input
                    type="checkbox"
                    checked={form.category_ids.includes(category.id)}
                    onChange={(event) =>
                      toggleId(
                        "category_ids",
                        category.id,
                        event.target.checked,
                      )
                    }
                  />
                  <span>{category.name}</span>
                </label>
              ))}
            {items
              .filter((value) => value.venue_id === rules.venue_id)
              .map((item) => (
                <label className="checkbox" key={item.id}>
                  <input
                    type="checkbox"
                    checked={form.menu_item_ids.includes(item.id)}
                    onChange={(event) =>
                      toggleId("menu_item_ids", item.id, event.target.checked)
                    }
                  />
                  <span>{item.name}</span>
                </label>
              ))}
          </div>
        </fieldset>
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
        <Button type="submit" disabled={saving}>
          {saving ? "Сохраняем…" : "Сохранить правила"}
        </Button>
      </form>
    </Panel>
  );
}

export function AdminPricingPage() {
  const venues = useResource(coffeeApi.getVenues);
  const menu = useResource(() => coffeeApi.getAdminMenu(false));
  const promotions = useResource(() => coffeeApi.getAdminPromotions());
  const groups = useResource(() => coffeeApi.getAdminModifierGroups(true));
  const [section, setSection] = useState<"modifiers" | "promotions">(
    "modifiers",
  );
  const [editing, setEditing] = useState<AdminModifierGroup | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [promotionId, setPromotionId] = useState("");
  const [rules, setRules] = useState<PromotionPricingRules | null>(null);
  const [rulesError, setRulesError] = useState<Error | null>(null);
  const [rulesLoading, setRulesLoading] = useState(false);
  const categoryVenue = useMemo(
    () =>
      new Map(
        menu.data?.categories.map((category) => [
          category.id,
          category.venue_id,
        ]) ?? [],
      ),
    [menu.data],
  );
  const venueItems = (menu.data?.items ?? []).map((item) => ({
    ...item,
    venue_id: item.venue_id ?? categoryVenue.get(item.category_id),
  }));
  useEffect(() => {
    if (!promotionId) {
      setRules(null);
      return;
    }
    setRulesLoading(true);
    setRulesError(null);
    void coffeeApi
      .getPromotionPricingRules(promotionId)
      .then(setRules)
      .catch((reason: unknown) =>
        setRulesError(
          reason instanceof Error
            ? reason
            : new Error("Не удалось загрузить правила"),
        ),
      )
      .finally(() => setRulesLoading(false));
  }, [promotionId]);
  const firstError =
    venues.error ?? menu.error ?? promotions.error ?? groups.error;
  const reloadAll = async () => {
    await Promise.all([
      venues.reload(),
      menu.reload(),
      promotions.reload(),
      groups.reload(),
    ]);
  };
  const toggleArchive = async (group: AdminModifierGroup) => {
    if (group.archived_at) await coffeeApi.restoreAdminModifierGroup(group);
    else await coffeeApi.archiveAdminModifierGroup(group);
    await groups.reload();
  };
  return (
    <Page
      title="Цены и модификаторы"
      eyebrow="Меню и акции"
      action={
        <Link className="button button--secondary" to="/admin/menu">
          Меню
        </Link>
      }
    >
      <div className="content-tabs">
        <Link to="/admin/menu">Позиции</Link>
        <Link to="/admin/promotions">Акции</Link>
        <Link className="is-active" to="/admin/pricing">
          Цены и добавки
        </Link>
      </div>
      <div className="chip-row">
        <button
          className={`chip ${section === "modifiers" ? "is-active" : ""}`}
          onClick={() => setSection("modifiers")}
        >
          Модификаторы
        </button>
        <button
          className={`chip ${section === "promotions" ? "is-active" : ""}`}
          onClick={() => setSection("promotions")}
        >
          Правила акций
        </button>
      </div>
      {(venues.loading ||
        menu.loading ||
        promotions.loading ||
        groups.loading) && <Loader />}
      {firstError && (
        <ErrorState error={firstError} onRetry={() => void reloadAll()} />
      )}
      {!firstError && section === "modifiers" && (
        <>
          <Button
            onClick={() => {
              setEditing(null);
              setEditorOpen(true);
            }}
          >
            Создать модификатор
          </Button>
          {editorOpen && venues.data && menu.data && (
            <ModifierEditor
              key={editing?.id ?? "new"}
              group={editing}
              venues={venues.data.items}
              items={venueItems}
              onCancel={() => setEditorOpen(false)}
              onSaved={async () => {
                setEditorOpen(false);
                await groups.reload();
              }}
            />
          )}
          <div className="stack-list">
            {groups.data?.map((group) => (
              <Panel key={group.id}>
                <div className="row-between">
                  <div>
                    <h2>{group.name}</h2>
                    <p className="muted">
                      {group.options.length} вариантов · {group.item_ids.length}{" "}
                      товаров{group.archived_at ? " · в архиве" : ""}
                    </p>
                  </div>
                  <div className="action-row">
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setEditing(group);
                        setEditorOpen(true);
                      }}
                    >
                      Изменить
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => void toggleArchive(group)}
                    >
                      {group.archived_at ? "Восстановить" : "В архив"}
                    </Button>
                  </div>
                </div>
              </Panel>
            ))}
          </div>
        </>
      )}
      {!firstError && section === "promotions" && (
        <>
          <Panel>
            <Field label="Акция">
              <select
                value={promotionId}
                onChange={(event) => setPromotionId(event.target.value)}
              >
                <option value="">Выберите акцию</option>
                {promotions.data?.items.map((promotion) => (
                  <option key={promotion.id} value={promotion.id}>
                    {promotion.title}
                  </option>
                ))}
              </select>
            </Field>
          </Panel>
          {rulesLoading && <Loader />}
          {rulesError && <ErrorState error={rulesError} />}
          {rules && promotions.data && (
            <PromotionRuleEditor
              key={`${rules.promotion_id}:${rules.pricing_enabled}`}
              promotion={promotions.data.items.find(
                (promotion) => promotion.id === rules.promotion_id,
              )!}
              rules={rules}
              categories={menu.data?.categories ?? []}
              items={venueItems}
              onSaved={setRules}
            />
          )}
        </>
      )}
    </Page>
  );
}

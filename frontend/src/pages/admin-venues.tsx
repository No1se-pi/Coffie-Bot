import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { coffeeApi } from "../api/client";
import type { AdminVenue, AdminVenueDraft } from "../api/types";
import {
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Page,
  Panel,
} from "../components/ui";
import { useResource } from "../hooks/useResource";

const emptyVenue: AdminVenueDraft = {
  slug: "",
  name: "",
  description: null,
  phone: null,
  email: null,
  website: null,
  telegram: null,
  logo_media_id: null,
  active: true,
  sort_order: 0,
};

function venueDraft(value: AdminVenue): AdminVenueDraft {
  return {
    slug: value.slug,
    name: value.name,
    description: value.description,
    phone: value.phone,
    email: value.email,
    website: value.website,
    telegram: value.telegram,
    logo_media_id: value.logo_media_id,
    active: value.active,
    sort_order: value.sort_order,
  };
}

export function AdminVenuesPage() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const resource = useResource(
    () => coffeeApi.getAdminVenues(includeArchived),
    [includeArchived],
  );
  const [editing, setEditing] = useState<AdminVenue | null>(null);
  const [draft, setDraft] = useState<AdminVenueDraft>(emptyVenue);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (editing) setDraft(venueDraft(editing));
  }, [editing]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveAdminVenue(editing, draft);
      setEditing(null);
      setDraft(emptyVenue);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось сохранить заведение"),
      );
    } finally {
      setSaving(false);
    }
  };

  const lifecycle = async (value: AdminVenue) => {
    setSaving(true);
    setError(null);
    try {
      if (value.archived_at) await coffeeApi.restoreAdminVenue(value);
      else await coffeeApi.archiveAdminVenue(value);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Не удалось изменить статус"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Page
      title="Заведения и точки"
      eyebrow="Бренды организации и физические адреса"
    >
      <Panel className="inline-actions-panel">
        <div>
          <h2>Физические точки</h2>
          <p className="muted">
            Адрес, привязка к заведению, самовывоз и консолидация настраиваются
            отдельно.
          </p>
        </div>
        <Link
          className="button button--secondary"
          to="/admin/delivery#locations"
        >
          Настроить точки
        </Link>
      </Panel>
      <label className="toggle-row">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(event) => setIncludeArchived(event.target.checked)}
        />
        <span>Показывать архивные</span>
      </label>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <ErrorState error={error} compact />}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="venue-admin-grid">
            {resource.data.items.map((value) => (
              <Panel
                key={value.id}
                className={value.archived_at ? "is-muted" : ""}
              >
                <div className="section-heading">
                  <div>
                    <small className="eyebrow">{value.slug}</small>
                    <h2>{value.name}</h2>
                  </div>
                  {value.logo_url && (
                    <img
                      className="venue-admin-logo"
                      src={value.logo_url}
                      alt=""
                    />
                  )}
                </div>
                <p>{value.description || "Описание не заполнено"}</p>
                <div className="action-row">
                  {!value.archived_at && (
                    <Button
                      variant="secondary"
                      onClick={() => setEditing(value)}
                    >
                      Изменить
                    </Button>
                  )}
                  <Button
                    variant={value.archived_at ? "secondary" : "danger"}
                    disabled={saving}
                    onClick={() => void lifecycle(value)}
                  >
                    {value.archived_at ? "Восстановить" : "В архив"}
                  </Button>
                </div>
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Заведений пока нет"
            text="Создайте первый ресторан или бренд организации."
          />
        ))}

      <Panel>
        <h2>
          {editing ? `Редактирование: ${editing.name}` : "Новое заведение"}
        </h2>
        <form className="form" onSubmit={(event) => void save(event)}>
          <Field label="Название">
            <input
              required
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </Field>
          <Field label="Slug" hint="Латиница, цифры и дефисы">
            <input
              required
              pattern="[a-z0-9][a-z0-9-]*"
              value={draft.slug}
              onChange={(event) =>
                setDraft({ ...draft, slug: event.target.value.toLowerCase() })
              }
            />
          </Field>
          <Field label="Описание">
            <textarea
              value={draft.description ?? ""}
              onChange={(event) =>
                setDraft({ ...draft, description: event.target.value || null })
              }
            />
          </Field>
          <div className="form-grid">
            <Field label="Телефон">
              <input
                value={draft.phone ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, phone: event.target.value || null })
                }
              />
            </Field>
            <Field label="Email">
              <input
                type="email"
                value={draft.email ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, email: event.target.value || null })
                }
              />
            </Field>
            <Field label="Сайт">
              <input
                type="url"
                value={draft.website ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, website: event.target.value || null })
                }
              />
            </Field>
            <Field label="Telegram">
              <input
                value={draft.telegram ?? ""}
                onChange={(event) =>
                  setDraft({ ...draft, telegram: event.target.value || null })
                }
              />
            </Field>
          </div>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.active}
              onChange={(event) =>
                setDraft({ ...draft, active: event.target.checked })
              }
            />
            <span>Показывать клиентам</span>
          </label>
          <div className="action-row">
            <Button type="submit" disabled={saving}>
              {saving ? "Сохраняем…" : "Сохранить"}
            </Button>
            {editing && (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setEditing(null);
                  setDraft(emptyVenue);
                }}
              >
                Отмена
              </Button>
            )}
          </div>
        </form>
      </Panel>
    </Page>
  );
}

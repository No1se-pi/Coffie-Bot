import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { coffeeApi, MEDIA_FILE_ACCEPT } from "../api/client";
import type {
  AdminFeedback,
  AdminStaffMember,
  AdjustmentPreview,
  FeedbackStatus,
  LoyaltyRewardConfig,
  LoyaltySettings,
  MenuCategory,
  MenuItem,
  OperationalPermission,
  Promotion,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useResource } from "../hooks/useResource";
import { formatDateTime, formatMoney } from "../utils/format";
import {
  Avatar,
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Field,
  Loader,
  Metric,
  Page,
  Panel,
} from "../components/ui";

export function AdminOverviewPage() {
  const resource = useResource(coffeeApi.getAdminOverview);
  return (
    <Page title="Обзор" eyebrow="Состояние программы">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <div className="metrics-grid metrics-grid--admin">
            <Metric value={resource.data.users_total} label="клиентов" />
            <Metric
              value={resource.data.active_promotions}
              label="активных акций"
              tone="accent"
            />
            <Metric value={resource.data.blocked_users} label="блокировок" />
            <Metric
              value={resource.data.suspicious_events}
              label="требуют внимания"
              tone="warning"
            />
          </div>
          <div className="admin-shortcuts">
            <Link to="/admin/users">
              <span>○</span>
              <strong>Пользователи</strong>
              <small>Поиск и корректировки</small>
            </Link>
            <Link to="/admin/events">
              <span>↻</span>
              <strong>События</strong>
              <small>Аудит действий</small>
            </Link>
            <Link to="/admin/staff">
              <span>◇</span>
              <strong>Сотрудники</strong>
              <small>Роли, права и доступ</small>
            </Link>
            <Link to="/admin/settings">
              <span>⚙</span>
              <strong>Программы</strong>
              <small>Правила лояльности</small>
            </Link>
            <Link to="/admin/menu">
              <span>☕</span>
              <strong>Контент</strong>
              <small>Меню и акции</small>
            </Link>
            <Link to="/admin/feedback">
              <span>★</span>
              <strong>Отзывы</strong>
              <small>Обратная связь клиентов</small>
            </Link>
          </div>
          <Panel>
            <div className="section-heading">
              <h2>Последние события</h2>
              <Link to="/admin/events">Все события</Link>
            </div>
            {resource.data.recent_events.length ? (
              <div className="event-list">
                {resource.data.recent_events.map((event) => (
                  <article
                    key={event.id}
                    className={event.suspicious ? "is-suspicious" : ""}
                  >
                    <span
                      className={`event-dot event-dot--${event.severity}`}
                    />
                    <div>
                      <p>{event.message}</p>
                      <small>{formatDateTime(event.created_at)}</small>
                    </div>
                    {event.suspicious && (
                      <Badge tone="warning">Проверить</Badge>
                    )}
                  </article>
                ))}
              </div>
            ) : (
              <p className="muted">Событий пока нет.</p>
            )}
          </Panel>
        </>
      )}
    </Page>
  );
}

export function AdminUsersPage() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const resource = useResource(
    () => coffeeApi.getAdminUsers(query, status),
    [query, status],
  );
  const search = (event: FormEvent) => {
    event.preventDefault();
    setQuery(input.trim());
  };
  return (
    <Page title="Клиенты" eyebrow="Поиск и управление">
      <Panel>
        <form className="search-form" onSubmit={search}>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Имя, username, Telegram ID или код"
            aria-label="Поиск клиентов"
          />
          <Button type="submit">Найти</Button>
        </form>
        <div className="chip-row">
          <button
            className={`chip ${status === "" ? "is-active" : ""}`}
            onClick={() => setStatus("")}
          >
            Все
          </button>
          <button
            className={`chip ${status === "active" ? "is-active" : ""}`}
            onClick={() => setStatus("active")}
          >
            Активные
          </button>
          <button
            className={`chip ${status === "blocked" ? "is-active" : ""}`}
            onClick={() => setStatus("blocked")}
          >
            Заблокированные
          </button>
        </div>
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="user-list">
            {resource.data.items.map((user) => (
              <article key={user.id}>
                <Avatar name={user.display_name} />
                <div className="user-list__identity">
                  <h2>{user.display_name}</h2>
                  <p>
                    {user.username
                      ? `@${user.username}`
                      : `Telegram ${user.telegram_id}`}
                  </p>
                  <small>
                    {user.last_seen_at
                      ? `Был ${formatDateTime(user.last_seen_at)}`
                      : `С нами с ${formatDateTime(user.created_at)}`}
                  </small>
                </div>
                <div className="user-list__numbers">
                  <Badge tone={user.status === "active" ? "success" : "danger"}>
                    {user.status === "active" ? "Активен" : "Заблокирован"}
                  </Badge>
                </div>
                <Link
                  className="button button--secondary"
                  to={`/admin/users/${encodeURIComponent(user.id)}/adjust`}
                >
                  Открыть клиента
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Никого не нашли"
            text="Проверьте запрос или измените фильтр статуса."
          />
        ))}
    </Page>
  );
}

const staffPermissionLabels: Record<OperationalPermission, string> = {
  "card.lookup": "Поиск и сканирование карт",
  "points.accrue": "Начисление баллов",
  "points.redeem": "Списание баллов",
  "visits.mark": "Отметка посещений",
  "stamps.add": "Добавление штампов",
  "rewards.redeem": "Погашение наград",
  "operations.reverse_own": "Отмена собственных операций",
  "tip_profile.manage_own": "Редактирование профиля и чаевых",
};

const operationalPermissions = Object.keys(
  staffPermissionLabels,
) as OperationalPermission[];

function defaultStaffPermissions(): Record<OperationalPermission, boolean> {
  return Object.fromEntries(
    operationalPermissions.map((permission) => [permission, true]),
  ) as Record<OperationalPermission, boolean>;
}

function resolvedStaffPermissions(
  member: AdminStaffMember,
): Record<OperationalPermission, boolean> {
  const values = defaultStaffPermissions();
  member.permissions.forEach((override) => {
    values[override.permission] = override.allowed;
  });
  return values;
}

function StaffMemberEditor({
  member,
  canManageAdmins,
  currentUserId,
  onSaved,
}: {
  member: AdminStaffMember;
  canManageAdmins: boolean;
  currentUserId?: string;
  onSaved: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState(member.display_name);
  const [position, setPosition] = useState(member.position ?? "");
  const [bio, setBio] = useState(member.bio ?? "");
  const [role, setRole] = useState<AdminStaffMember["role"]>(member.role);
  const [canEditTipProfile, setCanEditTipProfile] = useState(
    member.can_edit_tip_profile,
  );
  const [permissions, setPermissions] = useState(() =>
    resolvedStaffPermissions(member),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const manageable =
    member.user_id !== currentUserId &&
    (member.role === "staff" ||
      (canManageAdmins &&
        (member.role === "admin" || member.role === "owner")));

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (role !== member.role) {
        await coffeeApi.changeAdminStaffRole(member.id, role);
      }
      await coffeeApi.updateAdminStaff(member.id, {
        display_name: displayName.trim() || null,
        position: position.trim() || null,
        bio: bio.trim() || null,
        can_edit_tip_profile: canEditTipProfile,
        permissions: role === "staff" ? permissions : undefined,
      });
      await onSaved();
      setEditing(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось обновить сотрудника",
      );
    } finally {
      setBusy(false);
    }
  };

  const toggleAccess = async () => {
    const nextActive = !member.is_active;
    if (
      !nextActive &&
      !window.confirm(
        "Отключить сотрудника? Все его активные сеансы будут завершены.",
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await coffeeApi.updateAdminStaff(member.id, { is_active: nextActive });
      await onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось изменить доступ сотрудника",
      );
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (
      !window.confirm(
        "Удалить сотрудника из списка? Доступ будет отключён, а история операций сохранится.",
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await coffeeApi.deleteAdminStaff(member.id);
      await onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось удалить сотрудника",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel className="staff-admin-card">
      <div className="section-heading">
        <div>
          <div className="tag-row">
            <Badge tone={member.is_active ? "success" : "danger"}>
              {member.is_active ? "Активен" : "Отключён"}
            </Badge>
            <Badge>
              {member.role === "owner"
                ? "Владелец"
                : member.role === "admin"
                  ? "Администратор"
                  : "Сотрудник"}
            </Badge>
          </div>
          <h2>{member.display_name}</h2>
          <small>
            {member.username
              ? `@${member.username}`
              : `Telegram ${member.telegram_id}`}
          </small>
        </div>
        {manageable && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => setEditing((value) => !value)}
          >
            {editing ? "Закрыть настройки" : "Настройки"}
          </Button>
        )}
      </div>
      {editing && manageable && (
        <form className="form" onSubmit={(event) => void save(event)}>
          <div className="form-grid">
            <Field label="Отображаемое имя">
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                disabled={!manageable}
              />
            </Field>
            <Field label="Должность">
              <input
                value={position}
                onChange={(event) => setPosition(event.target.value)}
                disabled={!manageable}
                placeholder="Бариста"
              />
            </Field>
            <Field label="Роль">
              <select
                value={role}
                onChange={(event) =>
                  setRole(event.target.value as AdminStaffMember["role"])
                }
                disabled={!manageable}
              >
                <option value="staff">Сотрудник</option>
                {canManageAdmins && (
                  <option value="admin">Администратор</option>
                )}
                {member.role === "owner" && (
                  <option value="owner">Владелец</option>
                )}
              </select>
            </Field>
          </div>
          <Field label="Описание">
            <textarea
              rows={2}
              value={bio}
              onChange={(event) => setBio(event.target.value)}
              disabled={!manageable}
            />
          </Field>
          {role === "staff" && (
            <div className="permission-grid">
              {operationalPermissions.map((permission) => (
                <label className="checkbox" key={permission}>
                  <input
                    type="checkbox"
                    checked={permissions[permission]}
                    disabled={!manageable}
                    onChange={(event) =>
                      setPermissions((current) => ({
                        ...current,
                        [permission]: event.target.checked,
                      }))
                    }
                  />
                  <span>{staffPermissionLabels[permission]}</span>
                </label>
              ))}
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={canEditTipProfile}
                  disabled={!manageable}
                  onChange={(event) =>
                    setCanEditTipProfile(event.target.checked)
                  }
                />
                <span>Разрешить профиль и реквизиты чаевых</span>
              </label>
            </div>
          )}
          {error && <div className="inline-error">{error}</div>}
          <div className="action-row">
            <Button type="submit" disabled={busy}>
              {busy ? "Сохраняем…" : "Сохранить"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void toggleAccess()}
              disabled={busy}
            >
              {member.is_active ? "Отключить" : "Включить"}
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={() => void remove()}
              disabled={busy}
            >
              Удалить
            </Button>
          </div>
        </form>
      )}
    </Panel>
  );
}

export function AdminStaffPage() {
  const { actor } = useAuth();
  const canManageAdmins = actor?.role === "owner";
  const staffResource = useResource(coffeeApi.getAdminStaff);
  const customersResource = useResource(() =>
    coffeeApi.getAdminUsers(undefined, "active"),
  );
  const tipProfilesResource = useResource(coffeeApi.getPendingTipProfiles);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState<"all" | "active" | "inactive">("active");
  const [showCreate, setShowCreate] = useState(false);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<"staff" | "admin">("staff");
  const [displayName, setDisplayName] = useState("");
  const [position, setPosition] = useState("");
  const [permissions, setPermissions] = useState(defaultStaffPermissions);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [moderatingId, setModeratingId] = useState<string | null>(null);

  const moderateTipProfile = async (id: string, approve: boolean) => {
    setModeratingId(id);
    setError(null);
    try {
      if (approve) await coffeeApi.approveTipProfile(id);
      else await coffeeApi.hideTipProfile(id, "Нужна корректировка профиля");
      await tipProfilesResource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось обработать профиль",
      );
    } finally {
      setModeratingId(null);
    }
  };

  const existingUserIds = useMemo(
    () => new Set(staffResource.data?.items.map((item) => item.user_id) ?? []),
    [staffResource.data],
  );
  const availableCustomers = useMemo(
    () =>
      customersResource.data?.items.filter(
        (user) => !existingUserIds.has(user.id),
      ) ?? [],
    [customersResource.data, existingUserIds],
  );
  const visibleStaff = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (staffResource.data?.items ?? []).filter((member) => {
      const matchesQuery =
        !normalized ||
        [
          member.display_name,
          member.username,
          member.position,
          member.telegram_id,
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(normalized));
      const matchesActive =
        active === "all" || member.is_active === (active === "active");
      return matchesQuery && matchesActive;
    });
  }, [active, query, staffResource.data]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!userId) {
      setError("Выберите зарегистрированного клиента");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      await coffeeApi.createAdminStaff({
        user_id: userId,
        role,
        display_name: displayName.trim() || null,
        position: position.trim() || null,
        bio: null,
        can_edit_tip_profile: true,
        permissions: role === "staff" ? permissions : {},
      });
      setUserId("");
      setDisplayName("");
      setPosition("");
      setPermissions(defaultStaffPermissions());
      setShowCreate(false);
      await staffResource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось добавить сотрудника",
      );
    } finally {
      setCreating(false);
    }
  };

  return (
    <Page
      title="Сотрудники"
      eyebrow="Роли и доступ"
      action={
        <Button onClick={() => setShowCreate((value) => !value)}>
          {showCreate ? "Закрыть" : "Добавить сотрудника"}
        </Button>
      }
    >
      {showCreate && (
        <Panel>
          <form className="form" onSubmit={(event) => void create(event)}>
            <h2>Новый сотрудник</h2>
            <p className="muted">
              Человек должен хотя бы один раз открыть бота, после чего появится
              в списке клиентов.
            </p>
            <div className="form-grid">
              <Field label="Клиент">
                <select
                  value={userId}
                  onChange={(event) => setUserId(event.target.value)}
                >
                  <option value="">Выберите клиента</option>
                  {availableCustomers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.display_name} · {user.telegram_id}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Роль">
                <select
                  value={role}
                  onChange={(event) =>
                    setRole(event.target.value as "staff" | "admin")
                  }
                >
                  <option value="staff">Сотрудник</option>
                  {canManageAdmins && (
                    <option value="admin">Администратор</option>
                  )}
                </select>
              </Field>
              <Field label="Отображаемое имя">
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="Можно оставить пустым"
                />
              </Field>
              <Field label="Должность">
                <input
                  value={position}
                  onChange={(event) => setPosition(event.target.value)}
                  placeholder="Бариста"
                />
              </Field>
            </div>
            {role === "staff" && (
              <div className="permission-grid">
                {operationalPermissions.map((permission) => (
                  <label className="checkbox" key={permission}>
                    <input
                      type="checkbox"
                      checked={permissions[permission]}
                      onChange={(event) =>
                        setPermissions((current) => ({
                          ...current,
                          [permission]: event.target.checked,
                        }))
                      }
                    />
                    <span>{staffPermissionLabels[permission]}</span>
                  </label>
                ))}
              </div>
            )}
            {error && <div className="inline-error">{error}</div>}
            <Button type="submit" disabled={creating}>
              {creating ? "Добавляем…" : "Добавить"}
            </Button>
          </form>
        </Panel>
      )}
      {tipProfilesResource.data?.items.length ? (
        <Panel>
          <div className="section-heading">
            <div>
              <h2>Профили на модерации</h2>
              <p className="muted">Аватар, описание и ссылка на чаевые.</p>
            </div>
            <Badge tone="warning">{tipProfilesResource.data.total}</Badge>
          </div>
          <div className="compact-list">
            {tipProfilesResource.data.items.map((profile) => (
              <article key={profile.id}>
                <div>
                  <strong>
                    {profile.pending_name || profile.staff_display_name}
                  </strong>
                  <small>{profile.position || "Сотрудник"}</small>
                  {profile.pending_bio && <p>{profile.pending_bio}</p>}
                  {profile.pending_tip_url && (
                    <small>{profile.pending_tip_url}</small>
                  )}
                </div>
                <div className="action-row">
                  <Button
                    variant="secondary"
                    disabled={moderatingId === profile.id}
                    onClick={() => void moderateTipProfile(profile.id, false)}
                  >
                    Отклонить
                  </Button>
                  <Button
                    disabled={moderatingId === profile.id}
                    onClick={() => void moderateTipProfile(profile.id, true)}
                  >
                    Одобрить
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </Panel>
      ) : null}
      {tipProfilesResource.error && (
        <ErrorState
          error={tipProfilesResource.error}
          onRetry={tipProfilesResource.reload}
          compact
        />
      )}
      <Panel>
        <div className="form-grid">
          <Field label="Поиск">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Имя, username, должность или Telegram ID"
            />
          </Field>
          <Field label="Доступ">
            <select
              value={active}
              onChange={(event) =>
                setActive(event.target.value as typeof active)
              }
            >
              <option value="all">Все</option>
              <option value="active">Активные</option>
              <option value="inactive">Отключённые</option>
            </select>
          </Field>
        </div>
      </Panel>
      {(staffResource.loading || customersResource.loading) && <Loader />}
      {staffResource.error && (
        <ErrorState
          error={staffResource.error}
          onRetry={staffResource.reload}
        />
      )}
      {customersResource.error && (
        <ErrorState
          error={customersResource.error}
          onRetry={customersResource.reload}
        />
      )}
      {staffResource.data &&
        (visibleStaff.length ? (
          <div className="card-list">
            {visibleStaff.map((member) => (
              <StaffMemberEditor
                key={`${member.id}:${member.updated_at}:${member.is_active}`}
                member={member}
                canManageAdmins={canManageAdmins}
                currentUserId={actor?.id}
                onSaved={staffResource.reload}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title="Сотрудников не нашли"
            text="Измените фильтр или добавьте нового сотрудника."
          />
        ))}
    </Page>
  );
}

const feedbackStatusLabels: Record<FeedbackStatus, string> = {
  new: "Новый",
  in_progress: "В работе",
  resolved: "Решён",
  archived: "В архиве",
};

const feedbackCategoryLabels: Record<AdminFeedback["category"], string> = {
  service: "Обслуживание",
  food_and_drinks: "Еда и напитки",
  application: "Приложение",
  loyalty: "Лояльность",
  other: "Другое",
};

function FeedbackCard({
  item,
  onChanged,
  onDeleted,
}: {
  item: AdminFeedback;
  onChanged: () => Promise<void>;
  onDeleted: () => Promise<void>;
}) {
  const [status, setStatus] = useState<FeedbackStatus>(item.status);
  const [note, setNote] = useState(item.internal_note ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.updateAdminFeedback(item.id, {
        status,
        internal_note: note.trim() || null,
        assigned_to_staff_id: item.assigned_to_staff_id ?? null,
      });
      await onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось сохранить отзыв",
      );
    } finally {
      setSaving(false);
    }
  };

  const archive = async () => {
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.updateAdminFeedback(item.id, {
        status: "archived",
        internal_note: note.trim() || null,
        assigned_to_staff_id: item.assigned_to_staff_id ?? null,
      });
      await onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось скрыть отзыв",
      );
    } finally {
      setSaving(false);
    }
  };

  const restore = async () => {
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.updateAdminFeedback(item.id, {
        status: "new",
        internal_note: note.trim() || null,
        assigned_to_staff_id: item.assigned_to_staff_id ?? null,
      });
      await onChanged();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось восстановить отзыв",
      );
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (
      !window.confirm(
        "Удалить отзыв без возможности восстановления? Запись аудита сохранится.",
      )
    )
      return;
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.deleteAdminFeedback(item.id);
      await onDeleted();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось удалить отзыв",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel className="feedback-card">
      <div className="feedback-card__heading">
        <div>
          <div className="tag-row">
            <Badge tone={item.rating <= 2 ? "danger" : "neutral"}>
              {"★".repeat(item.rating)}
              {"☆".repeat(5 - item.rating)}
            </Badge>
            <Badge>{feedbackCategoryLabels[item.category]}</Badge>
          </div>
          <h2>{item.user_display_name || "Клиент"}</h2>
          <small>{formatDateTime(item.created_at)}</small>
        </div>
        {!item.may_contact && <Badge tone="warning">Не связываться</Badge>}
      </div>
      <p className="feedback-card__message">{item.message}</p>
      <div className="feedback-card__controls">
        <Field label="Статус">
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as FeedbackStatus)
            }
          >
            {Object.entries(feedbackStatusLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Внутренняя заметка">
          <textarea
            rows={3}
            maxLength={4000}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Видна только команде кофейни"
          />
        </Field>
      </div>
      {error && <div className="inline-error">{error}</div>}
      <div className="action-row">
        <Button onClick={() => void save()} disabled={saving}>
          {saving ? "Сохраняем…" : "Сохранить"}
        </Button>
        {item.status === "archived" ? (
          <>
            <Button
              variant="secondary"
              onClick={() => void restore()}
              disabled={saving}
            >
              Восстановить
            </Button>
            <Button
              variant="ghost"
              onClick={() => void remove()}
              disabled={saving}
            >
              Удалить навсегда
            </Button>
          </>
        ) : (
          <Button
            variant="ghost"
            onClick={() => void archive()}
            disabled={saving}
          >
            Спрятать в архив
          </Button>
        )}
      </div>
    </Panel>
  );
}

export function AdminFeedbackPage() {
  const [view, setView] = useState<"active" | "archive">("active");
  const [status, setStatus] = useState("");
  const resource = useResource(
    () =>
      coffeeApi.getAdminFeedback(
        view === "archive" ? "archived" : status || undefined,
      ),
    [status, view],
  );

  return (
    <Page title="Отзывы" eyebrow="Обратная связь клиентов">
      <Panel>
        <div className="chip-row">
          <button
            className={`chip ${view === "active" ? "is-active" : ""}`}
            onClick={() => setView("active")}
          >
            Текущие
          </button>
          <button
            className={`chip ${view === "archive" ? "is-active" : ""}`}
            onClick={() => setView("archive")}
          >
            Архив
          </button>
        </div>
        {view === "active" && (
          <Field label="Статус">
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
            >
              <option value="">Все текущие</option>
              {Object.entries(feedbackStatusLabels)
                .filter(([value]) => value !== "archived")
                .map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
            </select>
          </Field>
        )}
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="feedback-list">
            {resource.data.items.map((item) => (
              <FeedbackCard
                key={`${item.id}:${item.status}:${item.internal_note ?? ""}`}
                item={item}
                onChanged={resource.reload}
                onDeleted={resource.reload}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title="Отзывов нет"
            text="По выбранному статусу обратной связи пока нет."
          />
        ))}
    </Page>
  );
}

export function AdminAdjustmentPage() {
  const { userId = "" } = useParams();
  const resource = useResource(() => coffeeApi.getAdminUser(userId), [userId]);
  const [direction, setDirection] = useState<"credit" | "debit">("credit");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<AdjustmentPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    balance_after: number;
    delta_points: number;
  } | null>(null);

  const makePreview = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setResult(null);
    const unsignedValue = Number(amount);
    if (!Number.isInteger(unsignedValue) || unsignedValue <= 0) {
      setError("Введите целое положительное количество баллов");
      return;
    }
    const value = direction === "credit" ? unsignedValue : -unsignedValue;
    if (reason.trim().length < 3) {
      setError("Укажите понятную причину корректировки");
      return;
    }
    if (!resource.data) return;
    const next = coffeeApi.previewAdjustment(
      resource.data,
      value,
      reason.trim(),
    );
    if (next.balance_after < 0) {
      setError("Итоговый баланс не может быть отрицательным");
      return;
    }
    setPreview(next);
  };

  const confirm = async () => {
    if (!preview) return;
    setLoading(true);
    setError(null);
    try {
      const operation = await coffeeApi.confirmAdjustment({
        user_id: preview.user_id,
        delta_points: preview.delta_points,
        reason: preview.reason,
      });
      setResult({
        balance_after: operation.balance_after ?? preview.balance_after,
        delta_points: operation.delta_points,
      });
      setPreview(null);
    } catch (reasonValue) {
      setError(
        reasonValue instanceof Error
          ? reasonValue.message
          : "Не удалось выполнить корректировку",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Page title="Корректировка баланса" eyebrow="Опасное действие">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data && (
        <>
          <Panel className="client-summary">
            <Avatar name={resource.data.display_name} size="large" />
            <div>
              <h2>{resource.data.display_name}</h2>
              <p className="muted">Код {resource.data.short_code}</p>
            </div>
            <strong className="client-summary__balance">
              {result?.balance_after ?? resource.data.balance_points}
              <small>баллов</small>
            </strong>
          </Panel>
          <div className="inline-warning">
            Корректировка не изменяет исходные операции. Будет создана новая
            запись с вашей причиной.
          </div>
          <Panel className="operation-panel">
            {result ? (
              <div className="operation-success" role="status">
                <span>✓</span>
                <h2>Баланс скорректирован</h2>
                <strong>
                  {result.delta_points > 0 ? "+" : ""}
                  {result.delta_points}
                </strong>
                <p>Новый баланс: {result.balance_after}</p>
                <Link className="button button--secondary" to="/admin/users">
                  Вернуться к пользователям
                </Link>
              </div>
            ) : preview ? (
              <div
                className="confirm-card"
                aria-label="Предпросмотр корректировки"
              >
                <h2>Проверьте изменение</h2>
                <dl>
                  <div>
                    <dt>Клиент</dt>
                    <dd>{preview.customer_name}</dd>
                  </div>
                  <div>
                    <dt>Текущий баланс</dt>
                    <dd>{preview.balance_before}</dd>
                  </div>
                  <div>
                    <dt>Изменение</dt>
                    <dd
                      className={
                        preview.delta_points > 0 ? "positive" : "negative"
                      }
                    >
                      {preview.delta_points > 0 ? "+" : ""}
                      {preview.delta_points}
                    </dd>
                  </div>
                  <div className="confirm-card__total">
                    <dt>Итоговый баланс</dt>
                    <dd>{preview.balance_after}</dd>
                  </div>
                  <div>
                    <dt>Причина</dt>
                    <dd>{preview.reason}</dd>
                  </div>
                </dl>
                <div className="action-row">
                  <Button
                    variant="secondary"
                    onClick={() => setPreview(null)}
                    disabled={loading}
                  >
                    Изменить
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() => void confirm()}
                    disabled={loading}
                  >
                    {loading ? "Подтверждаем…" : "Подтвердить корректировку"}
                  </Button>
                </div>
              </div>
            ) : (
              <form className="form" onSubmit={makePreview}>
                <div className="field">
                  <span className="field__label">Действие с балансом</span>
                  <div
                    className="action-row"
                    role="group"
                    aria-label="Действие с балансом"
                  >
                    <Button
                      type="button"
                      variant={direction === "credit" ? "primary" : "secondary"}
                      aria-pressed={direction === "credit"}
                      onClick={() => {
                        setDirection("credit");
                        setError(null);
                      }}
                    >
                      Начислить
                    </Button>
                    <Button
                      type="button"
                      variant={direction === "debit" ? "danger" : "secondary"}
                      aria-pressed={direction === "debit"}
                      onClick={() => {
                        setDirection("debit");
                        setError(null);
                      }}
                    >
                      Списать
                    </Button>
                  </div>
                </div>
                <Field
                  label="Количество баллов"
                  hint="Введите целое число без знака"
                >
                  <input
                    type="number"
                    value={amount}
                    onChange={(event) => {
                      setAmount(event.target.value);
                      setError(null);
                    }}
                    inputMode="numeric"
                    min={1}
                    step={1}
                    placeholder="50"
                  />
                </Field>
                <Field label="Причина" hint="Причина попадёт в журнал аудита">
                  <textarea
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    rows={3}
                    maxLength={500}
                    placeholder="Например: компенсация за ошибочное списание"
                  />
                </Field>
                {error && (
                  <div className="inline-error" role="alert">
                    {error}
                  </div>
                )}
                <Button type="submit">Показать итог</Button>
              </form>
            )}
            {preview && error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
          </Panel>
        </>
      )}
    </Page>
  );
}

export function AdminEventsPage() {
  const [severity, setSeverity] = useState("");
  const [suspicious, setSuspicious] = useState(false);
  const resource = useResource(
    () =>
      coffeeApi.getAdminEvents({
        severity: severity || undefined,
        suspicious: suspicious || undefined,
      }),
    [severity, suspicious],
  );
  return (
    <Page title="События" eyebrow="Неизменяемый аудит">
      <Panel>
        <div className="filter-grid">
          <Field label="Важность">
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value)}
            >
              <option value="">Все</option>
              <option value="info">Информация</option>
              <option value="warning">Предупреждения</option>
              <option value="critical">Критические</option>
            </select>
          </Field>
          <label className="checkbox checkbox--standalone">
            <input
              type="checkbox"
              checked={suspicious}
              onChange={(event) => setSuspicious(event.target.checked)}
            />
            <span>Только подозрительные</span>
          </label>
        </div>
      </Panel>
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {resource.data &&
        (resource.data.items.length ? (
          <div className="event-list event-list--cards">
            {resource.data.items.map((event) => (
              <article
                key={event.id}
                className={event.suspicious ? "is-suspicious" : ""}
              >
                <span className={`event-dot event-dot--${event.severity}`} />
                <div>
                  <div className="tag-row">
                    <Badge
                      tone={
                        event.severity === "critical"
                          ? "danger"
                          : event.severity === "warning"
                            ? "warning"
                            : "neutral"
                      }
                    >
                      {event.type}
                    </Badge>
                    {event.suspicious && (
                      <Badge tone="warning">Подозрительное</Badge>
                    )}
                  </div>
                  <p>{event.message}</p>
                  <small>
                    {formatDateTime(event.created_at)}
                    {event.actor_name ? ` · ${event.actor_name}` : ""}
                  </small>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Событий нет"
            text="По выбранным фильтрам ничего не найдено."
          />
        ))}
    </Page>
  );
}

function LoyaltyRewardEditor({
  label,
  value,
  menuItems,
  categories,
  menuError,
  menuLoading,
  onChange,
}: {
  label: string;
  value: LoyaltyRewardConfig | null;
  menuItems: MenuItem[];
  categories: MenuCategory[];
  menuError?: Error | null;
  menuLoading?: boolean;
  onChange: (value: LoyaltyRewardConfig) => void;
}) {
  const categoryNames = new Map(
    categories.map((category) => [category.id, category.name]),
  );
  const selectKind = (kind: LoyaltyRewardConfig["kind"]) => {
    if (kind === "menu_item") {
      onChange({
        kind,
        menu_item_id:
          value?.kind === "menu_item"
            ? value.menu_item_id
            : (menuItems[0]?.id ?? ""),
      });
      return;
    }
    if (kind === "points") {
      onChange({
        kind,
        points: value?.kind === "points" ? value.points : 50,
      });
      return;
    }
    onChange({
      kind,
      name: value?.kind === "custom" ? value.name : "Награда от кофейни",
      description:
        value?.kind === "custom" ? value.description : "Покажите QR бариста.",
    });
  };

  return (
    <div>
      <h3>{label}</h3>
      <div className="form-grid">
        <Field
          label="Что получит клиент"
          hint={
            menuLoading
              ? "Загружаем позиции меню…"
              : menuError
                ? "Позиции меню сейчас не загрузились — доступны своя награда и баллы."
                : !menuItems.length
                  ? "В меню пока нет активных позиций."
                  : undefined
          }
        >
          <select
            required
            value={value?.kind ?? ""}
            onChange={(event) =>
              selectKind(event.target.value as LoyaltyRewardConfig["kind"])
            }
          >
            <option value="" disabled>
              Выберите награду
            </option>
            <option value="menu_item" disabled={!menuItems.length}>
              Позицию из меню
            </option>
            <option value="custom">Свою награду</option>
            <option value="points">Баллы</option>
          </select>
        </Field>
        {value?.kind === "menu_item" && (
          <Field label="Позиция меню">
            <select
              required
              value={value.menu_item_id}
              onChange={(event) =>
                onChange({
                  kind: "menu_item",
                  menu_item_id: event.target.value,
                })
              }
            >
              {menuItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {categoryNames.get(item.category_id)
                    ? `${categoryNames.get(item.category_id)} · `
                    : ""}
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        {value?.kind === "custom" && (
          <>
            <Field label="Название награды">
              <input
                required
                maxLength={200}
                value={value.name}
                onChange={(event) =>
                  onChange({ ...value, name: event.target.value })
                }
              />
            </Field>
            <Field label="Короткое описание" hint="Необязательно">
              <input
                maxLength={8000}
                value={value.description ?? ""}
                onChange={(event) =>
                  onChange({
                    ...value,
                    description: event.target.value || null,
                  })
                }
              />
            </Field>
          </>
        )}
        {value?.kind === "points" && (
          <Field label="Сколько баллов">
            <input
              required
              type="number"
              min="1"
              max="1000000000"
              value={value.points}
              onChange={(event) =>
                onChange({ kind: "points", points: Number(event.target.value) })
              }
            />
          </Field>
        )}
      </div>
    </div>
  );
}

export function AdminSettingsPage() {
  const resource = useResource(coffeeApi.getSettings);
  const menuResource = useResource(() => coffeeApi.getAdminMenu(false));
  const [form, setForm] = useState<LoyaltySettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (resource.data) setForm(resource.data);
  }, [resource.data]);
  const update = <K extends keyof LoyaltySettings>(
    key: K,
    value: LoyaltySettings[K],
  ) => setForm((current) => (current ? { ...current, [key]: value } : current));
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!form) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      setForm(await coffeeApi.saveSettings(form));
      setSaved(true);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить настройки",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Page title="Программы" eyebrow="Настройки лояльности">
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {form && (
        <form className="settings-form" onSubmit={(event) => void save(event)}>
          {saved && (
            <div className="inline-success" role="status">
              Настройки сохранены
            </div>
          )}
          <Panel>
            <div className="toggle-heading">
              <div>
                <h2>Балльная программа</h2>
                <p>Расчёт всегда выполняется backend.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={form.points_enabled}
                  onChange={(event) =>
                    update("points_enabled", event.target.checked)
                  }
                />
                <span />
              </label>
            </div>
            <div className="form-grid">
              <Field label="Название валюты">
                <input
                  value={form.currency_name}
                  onChange={(event) =>
                    update("currency_name", event.target.value)
                  }
                />
              </Field>
              <Field label="Рублей за один балл">
                <input
                  type="number"
                  min="1"
                  value={form.rubles_per_point}
                  onChange={(event) =>
                    update("rubles_per_point", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Скидка за один списанный балл, ₽">
                <input
                  type="number"
                  min="1"
                  value={form.redemption_rubles_per_point}
                  onChange={(event) =>
                    update(
                      "redemption_rubles_per_point",
                      Number(event.target.value),
                    )
                  }
                />
              </Field>
              <Field label="Минимальная покупка, ₽">
                <input
                  type="number"
                  min="0"
                  value={form.minimum_purchase_minor / 100}
                  onChange={(event) =>
                    update(
                      "minimum_purchase_minor",
                      Number(event.target.value) * 100,
                    )
                  }
                />
              </Field>
              <Field label="Максимальная покупка, ₽">
                <input
                  type="number"
                  min="1"
                  value={form.maximum_purchase_minor / 100}
                  onChange={(event) =>
                    update(
                      "maximum_purchase_minor",
                      Number(event.target.value) * 100,
                    )
                  }
                />
              </Field>
              <Field label="Округление">
                <select
                  value={form.rounding}
                  onChange={(event) =>
                    update(
                      "rounding",
                      event.target.value as LoyaltySettings["rounding"],
                    )
                  }
                >
                  <option value="floor">Вниз</option>
                  <option value="half_up">До ближайшего (0,5 вверх)</option>
                  <option value="ceiling">Вверх</option>
                </select>
              </Field>
              <Field label="Максимум оплаты баллами, %">
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={form.max_redemption_percent}
                  onChange={(event) =>
                    update("max_redemption_percent", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Минимум баллов для списания">
                <input
                  type="number"
                  min="0"
                  value={form.minimum_redemption_points}
                  onChange={(event) =>
                    update(
                      "minimum_redemption_points",
                      Number(event.target.value),
                    )
                  }
                />
              </Field>
              <Field label="Приветственный бонус">
                <input
                  type="number"
                  min="0"
                  value={form.welcome_bonus_points}
                  onChange={(event) =>
                    update("welcome_bonus_points", Number(event.target.value))
                  }
                />
              </Field>
              <Field
                label="Срок действия баллов, дней"
                hint="Пусто — бессрочно"
              >
                <input
                  type="number"
                  min="1"
                  value={form.points_validity_days ?? ""}
                  onChange={(event) =>
                    update(
                      "points_validity_days",
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                />
              </Field>
              <Field label="Дневной лимит начисления" hint="Пусто — без лимита">
                <input
                  type="number"
                  min="1"
                  value={form.daily_accrual_limit_points ?? ""}
                  onChange={(event) =>
                    update(
                      "daily_accrual_limit_points",
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                />
              </Field>
              <Field label="Лимит одной операции" hint="Пусто — без лимита">
                <input
                  type="number"
                  min="1"
                  value={form.operation_accrual_limit_points ?? ""}
                  onChange={(event) =>
                    update(
                      "operation_accrual_limit_points",
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                />
              </Field>
              <Field label="Порог крупной покупки, ₽">
                <input
                  type="number"
                  min="1"
                  value={
                    form.large_operation_threshold_minor == null
                      ? ""
                      : form.large_operation_threshold_minor / 100
                  }
                  onChange={(event) =>
                    update(
                      "large_operation_threshold_minor",
                      event.target.value
                        ? Number(event.target.value) * 100
                        : null,
                    )
                  }
                />
              </Field>
            </div>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.large_operation_requires_approval}
                onChange={(event) => {
                  update(
                    "large_operation_requires_approval",
                    event.target.checked,
                  );
                  if (
                    event.target.checked &&
                    form.large_operation_threshold_minor == null
                  )
                    update("large_operation_threshold_minor", 100_000);
                }}
              />
              <span>
                Крупные начисления требуют подтверждения администратора
              </span>
            </label>
          </Panel>
          <Panel>
            <div className="toggle-heading">
              <div>
                <h2>Посещения</h2>
                <p>Бизнес-день рассчитывается в выбранном часовом поясе.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={form.visit_enabled}
                  onChange={(event) =>
                    update("visit_enabled", event.target.checked)
                  }
                />
                <span />
              </label>
            </div>
            <div className="form-grid">
              <Field label="Цель посещений">
                <input
                  type="number"
                  min="1"
                  value={form.visit_goal}
                  onChange={(event) =>
                    update("visit_goal", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Посещений в день">
                <input
                  type="number"
                  min="1"
                  value={form.visit_daily_limit}
                  onChange={(event) =>
                    update("visit_daily_limit", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Допустимых пропусков">
                <input
                  type="number"
                  min="0"
                  value={form.visit_allowed_misses}
                  onChange={(event) =>
                    update("visit_allowed_misses", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Срок награды, дней" hint="Пусто — бессрочно">
                <input
                  type="number"
                  min="1"
                  value={form.visit_reward_validity_days ?? ""}
                  onChange={(event) =>
                    update(
                      "visit_reward_validity_days",
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                />
              </Field>
              <Field label="Часовой пояс">
                <input
                  value={form.timezone}
                  onChange={(event) => update("timezone", event.target.value)}
                />
              </Field>
              <Field label="Смена бизнес-дня">
                <input
                  type="time"
                  value={form.business_day_boundary}
                  onChange={(event) =>
                    update("business_day_boundary", event.target.value)
                  }
                />
              </Field>
            </div>
            <LoyaltyRewardEditor
              label="Награда за серию"
              value={form.visit_reward}
              menuItems={menuResource.data?.items ?? []}
              categories={menuResource.data?.categories ?? []}
              menuError={menuResource.error}
              menuLoading={menuResource.loading}
              onChange={(value) => update("visit_reward", value)}
            />
            <div className="chip-row">
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={form.visits_must_be_consecutive}
                  onChange={(event) =>
                    update("visits_must_be_consecutive", event.target.checked)
                  }
                />
                <span>Посещения должны идти подряд</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={form.visit_reset_on_miss}
                  onChange={(event) =>
                    update("visit_reset_on_miss", event.target.checked)
                  }
                />
                <span>Сбрасывать серию после пропуска</span>
              </label>
              <label className="checkbox">
                <input
                  type="checkbox"
                  checked={form.visit_restart_cycle}
                  onChange={(event) =>
                    update("visit_restart_cycle", event.target.checked)
                  }
                />
                <span>Начинать новый цикл после награды</span>
              </label>
            </div>
          </Panel>
          <Panel>
            <div className="toggle-heading">
              <div>
                <h2>Штампы</h2>
                <p>Награда создаётся после достижения цели.</p>
              </div>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={form.stamps_enabled}
                  onChange={(event) =>
                    update("stamps_enabled", event.target.checked)
                  }
                />
                <span />
              </label>
            </div>
            <div className="form-grid">
              <Field label="Штампов до награды">
                <input
                  type="number"
                  min="1"
                  value={form.stamp_goal}
                  onChange={(event) =>
                    update("stamp_goal", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Штампов за покупку">
                <input
                  type="number"
                  min="1"
                  value={form.stamps_per_purchase}
                  onChange={(event) =>
                    update("stamps_per_purchase", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Лимит штампов за операцию">
                <input
                  type="number"
                  min="1"
                  value={form.stamp_operation_limit}
                  onChange={(event) =>
                    update("stamp_operation_limit", Number(event.target.value))
                  }
                />
              </Field>
              <Field label="Срок награды, дней" hint="Пусто — бессрочно">
                <input
                  type="number"
                  min="1"
                  value={form.stamp_reward_validity_days ?? ""}
                  onChange={(event) =>
                    update(
                      "stamp_reward_validity_days",
                      event.target.value ? Number(event.target.value) : null,
                    )
                  }
                />
              </Field>
            </div>
            <LoyaltyRewardEditor
              label="Награда за штампы"
              value={form.stamp_reward}
              menuItems={menuResource.data?.items ?? []}
              categories={menuResource.data?.categories ?? []}
              menuError={menuResource.error}
              menuLoading={menuResource.loading}
              onChange={(value) => update("stamp_reward", value)}
            />
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.reset_stamps_after_reward}
                onChange={(event) =>
                  update("reset_stamps_after_reward", event.target.checked)
                }
              />
              <span>Сбрасывать штампы после выдачи награды</span>
            </label>
          </Panel>
          {error && (
            <div className="inline-error" role="alert">
              {error}
            </div>
          )}
          <Button type="submit" disabled={saving}>
            {saving ? "Сохраняем…" : "Сохранить настройки"}
          </Button>
        </form>
      )}
    </Page>
  );
}

function MenuCategoryEditor({
  category,
  onCancel,
  onSaved,
}: {
  category: MenuCategory | null;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const [name, setName] = useState(category?.name ?? "");
  const [description, setDescription] = useState(category?.description ?? "");
  const [sortOrder, setSortOrder] = useState(category?.sort_order ?? 0);
  const [visible, setVisible] = useState(category?.visible ?? true);
  const [iconMediaId, setIconMediaId] = useState<string | null>(
    category?.icon_media_id ?? null,
  );
  const [iconUrl, setIconUrl] = useState(category?.icon_url ?? "");
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) {
      setError("Укажите название категории");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveMenuCategory(category, {
        name: name.trim(),
        description: description.trim() || null,
        icon_media_id: iconMediaId,
        sort_order: sortOrder,
        visible,
      });
      await onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить категорию",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Panel>
      <form className="form" onSubmit={(event) => void save(event)}>
        <h2>{category ? "Редактировать категорию" : "Новая категория"}</h2>
        <Field label="Название категории">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <Field label="Описание категории">
          <textarea
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Field
          label="Иконка категории"
          hint="Лучше всего 512×512 px (1:1). JPG, PNG или WebP, до 5 МБ"
        >
          <input
            type="file"
            accept={MEDIA_FILE_ACCEPT}
            disabled={uploading}
            onChange={(event) => {
              const input = event.currentTarget;
              const file = input.files?.[0];
              input.value = "";
              if (!file) return;
              setUploading(true);
              setError(null);
              void coffeeApi
                .uploadAdminMedia(file, "menu_category")
                .then((media) => {
                  setIconMediaId(media.id);
                  setIconUrl(media.url);
                })
                .catch((reason: unknown) =>
                  setError(
                    reason instanceof Error
                      ? reason.message
                      : "Не удалось загрузить иконку",
                  ),
                )
                .finally(() => setUploading(false));
            }}
          />
        </Field>
        {iconUrl && (
          <img
            className="avatar avatar--large"
            src={iconUrl}
            alt="Предпросмотр иконки"
          />
        )}
        <div className="form-grid">
          <Field label="Порядок">
            <input
              type="number"
              value={sortOrder}
              onChange={(event) => setSortOrder(Number(event.target.value))}
            />
          </Field>
          <label className="checkbox checkbox--standalone">
            <input
              type="checkbox"
              checked={visible}
              onChange={(event) => setVisible(event.target.checked)}
            />
            <span>Показывать клиентам</span>
          </label>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <div className="action-row">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Отмена
          </Button>
          <Button type="submit" disabled={saving || uploading}>
            {saving ? "Сохраняем…" : "Сохранить категорию"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function MenuItemEditor({
  item,
  categories,
  onCancel,
  onSaved,
}: {
  item: MenuItem | null;
  categories: MenuCategory[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const [categoryId, setCategoryId] = useState(
    item?.category_id ?? categories[0]?.id ?? "",
  );
  const [name, setName] = useState(item?.name ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [price, setPrice] = useState(
    item ? String(item.price_minor / 100) : "",
  );
  const [oldPrice, setOldPrice] = useState(
    item?.old_price_minor ? String(item.old_price_minor / 100) : "",
  );
  const [pointsPrice, setPointsPrice] = useState(
    item?.points_price ? String(item.points_price) : "",
  );
  const [imageMediaId, setImageMediaId] = useState<string | null>(
    item?.image_media_id ?? null,
  );
  const [imageUrl, setImageUrl] = useState(item?.image_url ?? "");
  const [uploading, setUploading] = useState(false);
  const [volume, setVolume] = useState(item?.volume ?? "");
  const [composition, setComposition] = useState(item?.composition ?? "");
  const [labels, setLabels] = useState(item?.labels?.join(", ") ?? "");
  const [available, setAvailable] = useState(item?.available ?? true);
  const [visible, setVisible] = useState(item?.visible ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const priceMinor = Math.round(Number(price) * 100);
    const oldPriceMinor = oldPrice ? Math.round(Number(oldPrice) * 100) : null;
    const pointsPriceValue = pointsPrice ? Number(pointsPrice) : null;
    if (
      !categoryId ||
      !name.trim() ||
      !Number.isInteger(priceMinor) ||
      priceMinor < 0
    ) {
      setError("Выберите категорию, укажите название и корректную цену");
      return;
    }
    if (oldPriceMinor !== null && oldPriceMinor <= priceMinor) {
      setError("Старая цена должна быть выше текущей");
      return;
    }
    if (
      pointsPriceValue !== null &&
      (!Number.isInteger(pointsPriceValue) || pointsPriceValue <= 0)
    ) {
      setError("Цена в баллах должна быть целым положительным числом");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.saveMenuItem(item, {
        category_id: categoryId,
        name: name.trim(),
        description: description.trim() || null,
        image_media_id: imageMediaId,
        price_minor: priceMinor,
        old_price_minor: oldPriceMinor,
        points_price: pointsPriceValue,
        composition: composition.trim() || null,
        volume: volume.trim() || null,
        labels: labels
          .split(",")
          .map((label) => label.trim())
          .filter(Boolean),
        available,
        visible,
        sort_order: item?.sort_order ?? 0,
      });
      await onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось сохранить позицию",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Panel>
      <form className="form" onSubmit={(event) => void save(event)}>
        <h2>{item ? "Редактировать позицию" : "Новая позиция"}</h2>
        <div className="form-grid">
          <Field label="Категория">
            <select
              value={categoryId}
              onChange={(event) => setCategoryId(event.target.value)}
            >
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Название позиции">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field label="Цена, ₽">
            <input
              type="number"
              min="0"
              step="0.01"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
            />
          </Field>
          <Field label="Старая цена, ₽">
            <input
              type="number"
              min="0"
              step="0.01"
              value={oldPrice}
              onChange={(event) => setOldPrice(event.target.value)}
            />
          </Field>
          <Field
            label="Цена в баллах"
            hint="Оставьте пустым, если позицию нельзя купить за баллы"
          >
            <input
              type="number"
              min="1"
              step="1"
              value={pointsPrice}
              onChange={(event) => setPointsPrice(event.target.value)}
            />
          </Field>
          <Field label="Объём">
            <input
              value={volume}
              onChange={(event) => setVolume(event.target.value)}
              placeholder="250 мл"
            />
          </Field>
          <Field label="Метки" hint="Через запятую">
            <input
              value={labels}
              onChange={(event) => setLabels(event.target.value)}
              placeholder="хит, сезонное"
            />
          </Field>
        </div>
        <Field
          label="Фото позиции"
          hint="Лучше всего 900×1200 px (3:4). JPG, PNG или WebP, до 5 МБ"
        >
          <input
            type="file"
            accept={MEDIA_FILE_ACCEPT}
            disabled={uploading}
            onChange={(event) => {
              const input = event.currentTarget;
              const file = input.files?.[0];
              input.value = "";
              if (!file) return;
              setUploading(true);
              setError(null);
              void coffeeApi
                .uploadAdminMedia(file, "menu_item")
                .then((media) => {
                  setImageMediaId(media.id);
                  setImageUrl(media.url);
                })
                .catch((reason: unknown) =>
                  setError(
                    reason instanceof Error
                      ? reason.message
                      : "Не удалось загрузить фото",
                  ),
                )
                .finally(() => setUploading(false));
            }}
          />
        </Field>
        {imageUrl && (
          <div className="profile-heading">
            <img
              className="avatar avatar--large"
              src={imageUrl}
              alt="Предпросмотр"
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setImageMediaId(null);
                setImageUrl("");
              }}
            >
              Убрать фото
            </Button>
          </div>
        )}
        <Field label="Описание">
          <textarea
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </Field>
        <Field label="Состав">
          <textarea
            rows={2}
            value={composition}
            onChange={(event) => setComposition(event.target.value)}
          />
        </Field>
        <div className="chip-row">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={available}
              onChange={(event) => setAvailable(event.target.checked)}
            />
            <span>В наличии</span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={visible}
              onChange={(event) => setVisible(event.target.checked)}
            />
            <span>Показывать</span>
          </label>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <div className="action-row">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Отмена
          </Button>
          <Button type="submit" disabled={saving || uploading}>
            {saving ? "Сохраняем…" : "Сохранить позицию"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

export function AdminMenuPage() {
  const [view, setView] = useState<"active" | "archive">("active");
  const resource = useResource(
    () => coffeeApi.getAdminMenu(view === "archive"),
    [view],
  );
  const data = resource.data;
  const shownItems =
    data?.items.filter((item) =>
      view === "archive" ? Boolean(item.archived_at) : !item.archived_at,
    ) ?? [];
  const shownCategories =
    data?.categories.filter((category) =>
      shownItems.some((item) => item.category_id === category.id),
    ) ?? [];
  const [categoryEditor, setCategoryEditor] = useState<MenuCategory | null>(
    null,
  );
  const [itemEditor, setItemEditor] = useState<MenuItem | null>(null);
  const [editor, setEditor] = useState<"category" | "item" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = async (itemId: string) => {
    const item = resource.data?.items.find(
      (candidate) => candidate.id === itemId,
    );
    if (!item) return;
    setBusyId(item.id);
    setError(null);
    try {
      await coffeeApi.toggleMenuItem(item);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось обновить позицию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const archive = async (item: MenuItem) => {
    setBusyId(item.id);
    setError(null);
    try {
      await coffeeApi.archiveMenuItem(item);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось перенести позицию в архив",
      );
    } finally {
      setBusyId(null);
    }
  };
  const restore = async (item: MenuItem) => {
    setBusyId(item.id);
    setError(null);
    try {
      await coffeeApi.restoreMenuItem(item);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось восстановить позицию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const remove = async (item: MenuItem) => {
    if (
      !window.confirm(
        `Удалить «${item.name}» навсегда? История покупок и операций сохранится.`,
      )
    )
      return;
    setBusyId(item.id);
    setError(null);
    try {
      await coffeeApi.deleteMenuItem(item);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось удалить позицию",
      );
    } finally {
      setBusyId(null);
    }
  };
  return (
    <Page
      title="Меню"
      eyebrow="Контент кофейни"
      action={
        <Link className="button button--secondary" to="/admin/promotions">
          Акции
        </Link>
      }
    >
      <div className="content-tabs">
        <Link className="is-active" to="/admin/menu">
          Позиции
        </Link>
        <Link to="/admin/promotions">Акции</Link>
      </div>
      <div className="chip-row" role="group" aria-label="Разделы позиций">
        <button
          className={`chip ${view === "active" ? "is-active" : ""}`}
          onClick={() => {
            setView("active");
            setEditor(null);
          }}
        >
          Текущие
        </button>
        <button
          className={`chip ${view === "archive" ? "is-active" : ""}`}
          onClick={() => {
            setView("archive");
            setEditor(null);
          }}
        >
          Архив
        </button>
      </div>
      {view === "active" && (
        <div className="action-row">
          <Button
            variant="secondary"
            onClick={() => {
              setCategoryEditor(null);
              setEditor("category");
            }}
          >
            Добавить категорию
          </Button>
          <Button
            disabled={!data?.categories.length}
            onClick={() => {
              setItemEditor(null);
              setEditor("item");
            }}
          >
            Добавить позицию
          </Button>
        </div>
      )}
      {view === "active" && editor === "category" && (
        <MenuCategoryEditor
          key={categoryEditor?.id ?? "new-category"}
          category={categoryEditor}
          onCancel={() => setEditor(null)}
          onSaved={async () => {
            await resource.reload();
            setEditor(null);
          }}
        />
      )}
      {view === "active" && editor === "item" && data && (
        <MenuItemEditor
          key={itemEditor?.id ?? "new-item"}
          item={itemEditor}
          categories={data.categories}
          onCancel={() => setEditor(null)}
          onSaved={async () => {
            await resource.reload();
            setEditor(null);
          }}
        />
      )}
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <div className="inline-error">{error}</div>}
      {data && shownItems.length > 0 && (
        <div className="admin-menu">
          {shownCategories.map((category) => (
            <section key={category.id}>
              <div className="section-heading">
                <div className="admin-menu__category-heading">
                  {category.icon_url && (
                    <img
                      className="admin-menu__category-icon"
                      src={category.icon_url}
                      alt=""
                    />
                  )}
                  <div>
                    <h2>{category.name}</h2>
                    <p>{category.description}</p>
                  </div>
                </div>
                <Badge>
                  {
                    shownItems.filter(
                      (item) => item.category_id === category.id,
                    ).length
                  }
                </Badge>
                {view === "active" && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setCategoryEditor(category);
                      setEditor("category");
                    }}
                  >
                    Изменить
                  </Button>
                )}
              </div>
              {shownItems
                .filter((item) => item.category_id === category.id)
                .map((item) => (
                  <article key={item.id}>
                    <div className="admin-menu__image">
                      {item.image_url ? (
                        <img src={item.image_url} alt={`Фото ${item.name}`} />
                      ) : (
                        <span aria-hidden="true">☕</span>
                      )}
                    </div>
                    <div>
                      <h3>{item.name}</h3>
                      <p>{item.description}</p>
                      <strong>{formatMoney(item.price_minor)}</strong>
                    </div>
                    <div>
                      {view === "archive" ? (
                        <>
                          <Badge>В архиве</Badge>
                          <Button
                            variant="secondary"
                            onClick={() => void restore(item)}
                            disabled={busyId === item.id}
                          >
                            Восстановить
                          </Button>
                          <Button
                            variant="danger"
                            onClick={() => void remove(item)}
                            disabled={busyId === item.id}
                          >
                            Удалить навсегда
                          </Button>
                        </>
                      ) : (
                        <>
                          <Badge tone={item.visible ? "success" : "neutral"}>
                            {item.visible ? "Виден" : "Скрыт"}
                          </Badge>
                          <Button
                            variant="ghost"
                            onClick={() => void toggle(item.id)}
                            disabled={busyId === item.id}
                          >
                            {busyId === item.id
                              ? "…"
                              : item.visible
                                ? "Скрыть"
                                : "Показать"}
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => {
                              setItemEditor(item);
                              setEditor("item");
                            }}
                          >
                            Изменить
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => void archive(item)}
                            disabled={busyId === item.id}
                          >
                            В архив
                          </Button>
                        </>
                      )}
                    </div>
                  </article>
                ))}
            </section>
          ))}
        </div>
      )}
      {data && shownItems.length === 0 && (
        <EmptyState
          title={view === "archive" ? "Архив пуст" : "Позиций пока нет"}
          text={
            view === "archive"
              ? "Удалённые из меню позиции появятся здесь."
              : "Добавьте первую позицию и настройте её видимость."
          }
        />
      )}
    </Page>
  );
}

function PromotionEditor({
  promotion,
  onCancel,
  onSaved,
}: {
  promotion: Promotion | null;
  onCancel: () => void;
  onSaved: () => Promise<void>;
}) {
  const [title, setTitle] = useState(promotion?.title ?? "");
  const [text, setText] = useState(promotion?.text ?? "");
  const [imageMediaId, setImageMediaId] = useState<string | null>(
    promotion?.image_media_id ?? null,
  );
  const [imageUrl, setImageUrl] = useState(promotion?.image_url ?? "");
  const [uploading, setUploading] = useState(false);
  const [startsAt, setStartsAt] = useState(
    promotion?.starts_at?.slice(0, 16) ?? "",
  );
  const [endsAt, setEndsAt] = useState(promotion?.ends_at?.slice(0, 16) ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !text.trim()) {
      setError("Укажите заголовок и текст акции");
      return;
    }
    const startIso = startsAt ? new Date(startsAt).toISOString() : null;
    const endIso = endsAt ? new Date(endsAt).toISOString() : null;
    if (startIso && endIso && endIso <= startIso) {
      setError("Окончание акции должно быть позже начала");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await coffeeApi.savePromotion(promotion, {
        title: title.trim(),
        text: text.trim(),
        image_media_id: imageMediaId,
        starts_at: startIso,
        ends_at: endIso,
      });
      await onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось сохранить акцию",
      );
    } finally {
      setSaving(false);
    }
  };
  return (
    <Panel>
      <form className="form" onSubmit={(event) => void save(event)}>
        <h2>{promotion ? "Редактировать акцию" : "Новая акция"}</h2>
        <Field label="Заголовок акции">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </Field>
        <Field label="Текст акции">
          <textarea
            rows={4}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </Field>
        <Field
          label="Обложка акции"
          hint="Лучше всего 1200×675 px (16:9). JPG, PNG или WebP, до 5 МБ"
        >
          <input
            type="file"
            accept={MEDIA_FILE_ACCEPT}
            disabled={uploading}
            onChange={(event) => {
              const input = event.currentTarget;
              const file = input.files?.[0];
              input.value = "";
              if (!file) return;
              setUploading(true);
              setError(null);
              void coffeeApi
                .uploadAdminMedia(file, "promotion")
                .then((media) => {
                  setImageMediaId(media.id);
                  setImageUrl(media.url);
                })
                .catch((reason: unknown) =>
                  setError(
                    reason instanceof Error
                      ? reason.message
                      : "Не удалось загрузить фото",
                  ),
                )
                .finally(() => setUploading(false));
            }}
          />
        </Field>
        {imageUrl && (
          <img
            className="promotion-cover-preview"
            src={imageUrl}
            alt="Предпросмотр обложки акции"
          />
        )}
        <div className="form-grid">
          <Field label="Начало">
            <input
              type="datetime-local"
              value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)}
            />
          </Field>
          <Field label="Окончание">
            <input
              type="datetime-local"
              value={endsAt}
              onChange={(event) => setEndsAt(event.target.value)}
            />
          </Field>
        </div>
        {error && <div className="inline-error">{error}</div>}
        <div className="action-row">
          <Button type="button" variant="secondary" onClick={onCancel}>
            Отмена
          </Button>
          <Button type="submit" disabled={saving || uploading}>
            {saving ? "Сохраняем…" : "Сохранить черновик"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}

export function AdminPromotionsPage() {
  const [view, setView] = useState<"active" | "archive">("active");
  const resource = useResource(
    () =>
      coffeeApi.getAdminPromotions(view === "archive" ? "archived" : undefined),
    [view],
  );
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Promotion | null>(null);
  const publish = async (id: string) => {
    const promotion = resource.data?.items.find((item) => item.id === id);
    if (!promotion) return;
    setBusyId(id);
    setError(null);
    try {
      await coffeeApi.publishPromotion(promotion);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось опубликовать акцию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const archive = async (promotion: Promotion) => {
    setBusyId(promotion.id);
    setError(null);
    try {
      await coffeeApi.archivePromotion(promotion);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось архивировать акцию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const restore = async (promotion: Promotion) => {
    setBusyId(promotion.id);
    setError(null);
    try {
      await coffeeApi.restorePromotion(promotion);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Не удалось восстановить акцию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const remove = async (promotion: Promotion) => {
    if (
      !window.confirm(
        "Удалить акцию без возможности восстановления? Запись аудита сохранится.",
      )
    )
      return;
    setBusyId(promotion.id);
    setError(null);
    try {
      await coffeeApi.deletePromotion(promotion);
      await resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Не удалось удалить акцию",
      );
    } finally {
      setBusyId(null);
    }
  };
  const sorted = useMemo(() => resource.data?.items ?? [], [resource.data]);
  return (
    <Page
      title="Акции"
      eyebrow="Публикации"
      action={
        <Link className="button button--secondary" to="/admin/menu">
          Меню
        </Link>
      }
    >
      <div className="content-tabs">
        <Link to="/admin/menu">Позиции</Link>
        <Link className="is-active" to="/admin/promotions">
          Акции
        </Link>
      </div>
      <Panel>
        <div className="chip-row">
          <button
            className={`chip ${view === "active" ? "is-active" : ""}`}
            onClick={() => {
              setView("active");
              setEditorOpen(false);
              setEditing(null);
            }}
          >
            Текущие
          </button>
          <button
            className={`chip ${view === "archive" ? "is-active" : ""}`}
            onClick={() => {
              setView("archive");
              setEditorOpen(false);
              setEditing(null);
            }}
          >
            Архив
          </button>
        </div>
      </Panel>
      {view === "active" && (
        <Button
          onClick={() => {
            setEditing(null);
            setEditorOpen(true);
          }}
        >
          Создать акцию
        </Button>
      )}
      {view === "active" && editorOpen && (
        <PromotionEditor
          key={editing?.id ?? "new-promotion"}
          promotion={editing}
          onCancel={() => setEditorOpen(false)}
          onSaved={async () => {
            await resource.reload();
            setEditorOpen(false);
          }}
        />
      )}
      {resource.loading && <Loader />}
      {resource.error && (
        <ErrorState error={resource.error} onRetry={resource.reload} />
      )}
      {error && <div className="inline-error">{error}</div>}
      {resource.data &&
        (sorted.length ? (
          <div className="card-list">
            {sorted.map((promotion) => (
              <Panel className="promotion-admin-card" key={promotion.id}>
                {promotion.image_url && (
                  <img
                    className="promotion-admin-card__cover"
                    src={promotion.image_url}
                    alt={`Обложка ${promotion.title}`}
                  />
                )}
                <div className="promotion-admin-card__body">
                  <Badge
                    tone={
                      promotion.status === "published"
                        ? "success"
                        : promotion.status === "draft"
                          ? "neutral"
                          : "warning"
                    }
                  >
                    {promotion.status}
                  </Badge>
                  <h2>{promotion.title}</h2>
                  <p>{promotion.text}</p>
                  {promotion.ends_at && (
                    <small>До {formatDateTime(promotion.ends_at)}</small>
                  )}
                </div>
                {promotion.status === "archived" ? (
                  <div className="action-row">
                    <Button
                      variant="secondary"
                      onClick={() => void restore(promotion)}
                      disabled={busyId === promotion.id}
                    >
                      Восстановить
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => void remove(promotion)}
                      disabled={busyId === promotion.id}
                    >
                      Удалить навсегда
                    </Button>
                  </div>
                ) : (
                  <div className="promotion-admin-card__actions">
                    {promotion.status !== "published" && (
                      <Button
                        onClick={() => void publish(promotion.id)}
                        disabled={busyId === promotion.id}
                      >
                        {busyId === promotion.id
                          ? "Публикуем…"
                          : "Опубликовать"}
                      </Button>
                    )}
                    <div className="action-row">
                      <Button
                        variant="secondary"
                        onClick={() => {
                          setEditing(promotion);
                          setEditorOpen(true);
                        }}
                      >
                        Изменить
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => void archive(promotion)}
                        disabled={busyId === promotion.id}
                      >
                        В архив
                      </Button>
                    </div>
                  </div>
                )}
              </Panel>
            ))}
          </div>
        ) : (
          <EmptyState
            title={view === "archive" ? "Архив пуст" : "Акций пока нет"}
            text={
              view === "archive"
                ? "Архивированные акции появятся здесь."
                : "Создайте первую акцию и опубликуйте её после проверки."
            }
          />
        ))}
    </Page>
  );
}

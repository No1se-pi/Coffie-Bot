import {
  NavLink,
  Navigate,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useState, type ReactNode } from "react";
import type { Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { brand } from "../config";
import { appThemes, applyTheme, readTheme, type AppTheme } from "../theme";
import { Avatar, Button, ErrorState, Loader } from "./ui";

const roleLabels: Record<Role, string> = {
  customer: "Гость",
  staff: "Сотрудник",
  admin: "Администратор",
  owner: "Владелец",
};

const roleHome: Record<Role, string> = {
  customer: "/",
  staff: "/staff",
  admin: "/admin",
  owner: "/admin",
};

const navItems: Record<
  "customer" | "staff" | "admin",
  Array<{ to: string; label: string; icon: string; end?: boolean }>
> = {
  customer: [
    { to: "/", label: "Главная", icon: "⌂", end: true },
    { to: "/card", label: "Карта", icon: "▦" },
    { to: "/rewards", label: "Награды", icon: "◇" },
    { to: "/history", label: "История", icon: "↻" },
    { to: "/menu", label: "Меню", icon: "☕" },
    { to: "/cart", label: "Корзина", icon: "▣" },
    { to: "/more", label: "Ещё", icon: "•••" },
  ],
  staff: [
    { to: "/staff", label: "Работа", icon: "▦", end: true },
    { to: "/staff/scan", label: "Сканер", icon: "◎" },
    { to: "/staff/recent", label: "Операции", icon: "↻" },
    { to: "/staff/orders", label: "Заказы", icon: "▣" },
    { to: "/staff/profile", label: "Профиль", icon: "○" },
  ],
  admin: [
    { to: "/admin", label: "Обзор", icon: "⌂", end: true },
    { to: "/admin/users", label: "Клиенты", icon: "○" },
    { to: "/admin/staff", label: "Сотрудники", icon: "◇" },
    { to: "/admin/events", label: "События", icon: "↻" },
    { to: "/admin/feedback", label: "Отзывы", icon: "★" },
    { to: "/admin/settings", label: "Настройки", icon: "⚙" },
    { to: "/admin/menu", label: "Контент", icon: "☕" },
    { to: "/admin/delivery", label: "Доставка", icon: "▣" },
  ],
};

function effectiveNavRole(role: Role): "customer" | "staff" | "admin" {
  if (role === "owner" || role === "admin") return "admin";
  return role;
}

export function AuthGate() {
  const auth = useAuth();
  if (auth.loading)
    return (
      <div className="bootstrap">
        <Loader label="Проверяем вход через Telegram…" />
      </div>
    );
  if (auth.error)
    return (
      <div className="bootstrap">
        <ErrorState error={auth.error} onRetry={auth.retry} />
      </div>
    );
  if (!auth.actor)
    return (
      <div className="bootstrap">
        <ErrorState
          error={new Error("Сессия не найдена")}
          onRetry={auth.retry}
        />
      </div>
    );
  return <AppShell />;
}

function AppShell() {
  const { actor, activeRole, availableRoles, setActiveRole, isDemo } =
    useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [theme, setTheme] = useState<AppTheme>(readTheme);
  const navRole = effectiveNavRole(activeRole);
  const changeRole = (value: Role) => {
    setActiveRole(value);
    navigate(roleHome[value]);
  };
  const cycleTheme = () => {
    const currentIndex = appThemes.findIndex((item) => item.id === theme);
    const next =
      appThemes[(currentIndex + 1) % appThemes.length] ?? appThemes[0];
    if (!next) return;
    setTheme(next.id);
    applyTheme(next.id);
  };
  const currentTheme =
    appThemes.find((item) => item.id === theme) ?? appThemes[0];

  return (
    <div className="app-shell">
      <header className="topbar">
        <button
          className="brand"
          onClick={() => navigate(roleHome[activeRole])}
          aria-label={`${brand.name}: на главную`}
        >
          {actor?.photo_url ? (
            <Avatar
              name={actor.display_name}
              src={actor.photo_url}
              size="small"
            />
          ) : (
            <span className="brand__mark">{brand.shortName}</span>
          )}
          <span>
            <strong>{brand.name}</strong>
            <small>{brand.greeting}</small>
          </span>
        </button>
        <div className="topbar-controls">
          <button
            className="theme-cycle"
            type="button"
            onClick={cycleTheme}
            aria-label={`Тема: ${currentTheme?.label}. Переключить тему`}
            title={`Тема: ${currentTheme?.label}`}
          >
            {currentTheme?.icon}
          </button>
          <label className="role-picker">
            <span className="sr-only">Режим приложения</span>
            <select
              value={activeRole}
              onChange={(event) => changeRole(event.target.value as Role)}
              aria-label="Режим приложения"
            >
              {availableRoles.map((role) => (
                <option key={role} value={role}>
                  {roleLabels[role]}
                </option>
              ))}
            </select>
          </label>
        </div>
      </header>
      {isDemo && (
        <div className="demo-banner" role="status">
          Демо-данные · API-пути готовы к подключению
        </div>
      )}
      <div className="content">
        <Outlet />
      </div>
      <nav className="bottom-nav" aria-label="Основная навигация">
        {navItems[navRole].map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              isActive || (!item.end && location.pathname.startsWith(item.to))
                ? "bottom-nav__item is-active"
                : "bottom-nav__item"
            }
          >
            <span aria-hidden="true">{item.icon}</span>
            <small>{item.label}</small>
          </NavLink>
        ))}
      </nav>
      <span className="sr-only">Пользователь: {actor?.display_name}</span>
    </div>
  );
}

export function RoleGuard({
  allow,
  children,
}: {
  allow: Role[];
  children: ReactNode;
}) {
  const { activeRole } = useAuth();
  if (!allow.includes(activeRole))
    return <Navigate to={roleHome[activeRole]} replace />;
  return <>{children}</>;
}

export function NotFoundPage() {
  const { activeRole } = useAuth();
  const navigate = useNavigate();
  return (
    <main className="bootstrap">
      <div className="state state--card">
        <span className="state__icon">404</span>
        <h1>Страница не найдена</h1>
        <p>Возможно, ссылка устарела.</p>
        <Button onClick={() => navigate(roleHome[activeRole])}>
          На главную
        </Button>
      </div>
    </main>
  );
}

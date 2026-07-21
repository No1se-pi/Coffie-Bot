import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { coffeeApi, setSessionToken } from "../api/client";
import type { Actor, AuthSession, Role } from "../api/types";
import { getTelegramInitData, initializeTelegram } from "../telegram";

interface AuthContextValue {
  actor: Actor | null;
  activeRole: Role;
  availableRoles: Role[];
  loading: boolean;
  error: Error | null;
  isDemo: boolean;
  setActiveRole: (role: Role) => void;
  retry: () => void;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

function preferredRole(session: AuthSession): Role {
  const stored = window.sessionStorage.getItem(
    "coffie.active-role",
  ) as Role | null;
  if (stored && session.actor.available_roles.includes(stored)) return stored;
  return session.actor.available_roles.includes("customer")
    ? "customer"
    : session.actor.role;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [actor, setActor] = useState<Actor | null>(null);
  const [activeRole, setActiveRoleState] = useState<Role>("customer");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    const cleanupTelegram = initializeTelegram();
    const initData = getTelegramInitData();

    if (!coffeeApi.isDemo && !initData) {
      setError(
        new Error("Откройте приложение из Telegram, чтобы подтвердить вход."),
      );
      setLoading(false);
      return () => {
        alive = false;
        cleanupTelegram();
      };
    }

    setLoading(true);
    setError(null);
    coffeeApi
      .bootstrapAuth(initData)
      .then((session) => {
        if (!alive) return;
        setSessionToken(session.access_token);
        setActor(session.actor);
        setActiveRoleState(preferredRole(session));
      })
      .catch((reason: unknown) => {
        if (alive)
          setError(
            reason instanceof Error ? reason : new Error("Не удалось войти"),
          );
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
      cleanupTelegram();
    };
  }, [attempt]);

  const availableRoles = useMemo<Role[]>(
    () => actor?.available_roles ?? ["customer"],
    [actor],
  );
  const setActiveRole = useCallback(
    (role: Role) => {
      if (!availableRoles.includes(role)) return;
      setActiveRoleState(role);
      window.sessionStorage.setItem("coffie.active-role", role);
    },
    [availableRoles],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      actor,
      activeRole,
      availableRoles,
      loading,
      error,
      isDemo: coffeeApi.isDemo,
      setActiveRole,
      retry: () => setAttempt((value) => value + 1),
      logout: async () => {
        await coffeeApi.logout();
        setActor(null);
      },
    }),
    [actor, activeRole, availableRoles, loading, error, setActiveRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

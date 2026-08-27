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
import type {
  Actor,
  AuthSession,
  Role,
  TelegramWebLoginData,
} from "../api/types";
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
  loginWithTelegram: (payload: TelegramWebLoginData) => Promise<void>;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

function operationalRoles(actor: Actor): Role[] {
  const roles = [...actor.available_roles];
  if (
    (actor.role === "admin" || actor.role === "owner") &&
    !roles.includes("staff")
  ) {
    const elevatedIndex = roles.indexOf(actor.role);
    roles.splice(elevatedIndex < 0 ? roles.length : elevatedIndex, 0, "staff");
  }
  return roles;
}

function preferredRole(session: AuthSession): Role {
  const roles = operationalRoles(session.actor);
  const stored = window.sessionStorage.getItem(
    "coffie.active-role",
  ) as Role | null;
  if (stored && roles.includes(stored)) return stored;
  return roles.includes("customer") ? "customer" : session.actor.role;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [actor, setActor] = useState<Actor | null>(null);
  const [activeRole, setActiveRoleState] = useState<Role>("customer");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [attempt, setAttempt] = useState(0);
  const acceptSession = useCallback((session: AuthSession) => {
    setSessionToken(session.access_token);
    setActor(session.actor);
    setActiveRoleState(preferredRole(session));
    setError(null);
  }, []);

  useEffect(() => {
    let alive = true;
    const cleanupTelegram = initializeTelegram();
    const initData = getTelegramInitData();

    setLoading(true);
    setError(null);
    // Authentication is a backend trust boundary: only the server may accept an
    // empty initData for explicitly enabled local DEV_AUTH. Production still
    // verifies configuration, Telegram signature and TTL before issuing a session.
    coffeeApi
      .bootstrapAuth(initData)
      .then((session) => {
        if (!alive) return;
        acceptSession(session);
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
  }, [acceptSession, attempt]);

  const availableRoles = useMemo<Role[]>(
    () => (actor ? operationalRoles(actor) : ["customer"]),
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
      loginWithTelegram: async (payload) => {
        setLoading(true);
        setError(null);
        try {
          acceptSession(await coffeeApi.telegramWebLogin(payload));
        } catch (reason: unknown) {
          setError(
            reason instanceof Error ? reason : new Error("Не удалось войти"),
          );
          throw reason;
        } finally {
          setLoading(false);
        }
      },
      logout: async () => {
        await coffeeApi.logout();
        setActor(null);
      },
    }),
    [
      actor,
      activeRole,
      availableRoles,
      loading,
      error,
      setActiveRole,
      acceptSession,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

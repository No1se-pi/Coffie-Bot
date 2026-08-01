export type AppTheme =
  "light" | "dark" | "coffee" | "comic" | "matcha" | "anime";

export const appThemes: Array<{
  id: AppTheme;
  label: string;
  icon: string;
}> = [
  { id: "light", label: "Светлая", icon: "☀" },
  { id: "dark", label: "Тёмная", icon: "◐" },
  { id: "coffee", label: "Кофейная", icon: "☕" },
  { id: "comic", label: "Комикс", icon: "★" },
  { id: "matcha", label: "Матча", icon: "●" },
  { id: "anime", label: "Аниме", icon: "✦" },
];

const STORAGE_KEY = "coffie.theme";

export function readTheme(): AppTheme {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (appThemes.some((theme) => theme.id === stored))
      return stored as AppTheme;
  } catch {
    // The selected theme still works for the current page when storage is blocked.
  }
  return "coffee";
}

export function applyTheme(theme: AppTheme): void {
  document.documentElement.dataset.appTheme = theme;
  document.documentElement.style.colorScheme =
    theme === "dark" ? "dark" : "light";
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Do not block the Mini App when local storage is unavailable.
  }
}

export function initializeStoredTheme(): AppTheme {
  const theme = readTheme();
  applyTheme(theme);
  return theme;
}

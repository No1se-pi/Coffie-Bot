import { useEffect, useRef, useState } from "react";
import type { TelegramWebLoginData } from "../api/types";
import { telegramBotUsername } from "../config";
import { ErrorState } from "./ui";

declare global {
  interface Window {
    __coffieTelegramAuth?: (payload: TelegramWebLoginData) => void;
  }
}

export function TelegramLogin({
  onLogin,
}: {
  onLogin: (payload: TelegramWebLoginData) => Promise<void>;
}) {
  const target = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<Error | null>(null);
  const [widgetReady, setWidgetReady] = useState(false);

  useEffect(() => {
    const container = target.current;
    if (!container || !telegramBotUsername) return;
    window.__coffieTelegramAuth = (payload) => {
      setError(null);
      void onLogin(payload).catch((reason: unknown) =>
        setError(
          reason instanceof Error ? reason : new Error("Не удалось войти"),
        ),
      );
    };
    const script = document.createElement("script");
    script.async = true;
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.dataset.telegramLogin = telegramBotUsername;
    script.dataset.size = "large";
    script.dataset.radius = "12";
    script.dataset.userpic = "false";
    script.dataset.onauth = "window.__coffieTelegramAuth(user)";
    script.addEventListener("load", () => setWidgetReady(true));
    script.addEventListener("error", () =>
      setError(
        new Error(
          "Telegram Login не загрузился. Откройте приложение через бота.",
        ),
      ),
    );
    container.append(script);
    // Browser extensions and network filters can silently block the Telegram
    // iframe without firing a script error. Do not leave an unexplained blank.
    const timeout = window.setTimeout(() => {
      if (!container.querySelector("iframe")) {
        setError(
          new Error("Telegram Login заблокирован браузером или расширением."),
        );
      }
    }, 5000);
    return () => {
      window.clearTimeout(timeout);
      delete window.__coffieTelegramAuth;
      script.remove();
    };
  }, [onLogin]);

  if (!telegramBotUsername)
    return (
      <p className="muted">
        Для входа из браузера настройте VITE_TELEGRAM_BOT_USERNAME и домен бота
        в BotFather.
      </p>
    );
  return (
    <>
      <div className="telegram-login" ref={target} />
      {!widgetReady && !error && (
        <p className="muted">Загружаем Telegram Login…</p>
      )}
      {error && <ErrorState error={error} compact />}
      <a
        className="button button--primary telegram-login__fallback"
        href={`https://t.me/${telegramBotUsername}?startapp=admin`}
      >
        Открыть админку в Telegram
      </a>
    </>
  );
}

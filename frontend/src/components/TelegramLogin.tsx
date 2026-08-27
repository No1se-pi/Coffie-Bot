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
    container.append(script);
    return () => {
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
      {error && <ErrorState error={error} compact />}
    </>
  );
}

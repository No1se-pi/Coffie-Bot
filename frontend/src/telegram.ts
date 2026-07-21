declare global {
  interface Window {
    Telegram?: {
      WebApp?: {
        initData?: string;
        colorScheme?: "light" | "dark";
        ready?: () => void;
        expand?: () => void;
        closeScanQrPopup?: () => void;
        showScanQrPopup?: (
          params: { text?: string },
          callback: (value: string) => boolean | void,
        ) => void;
        onEvent?: (name: string, callback: () => void) => void;
        offEvent?: (name: string, callback: () => void) => void;
      };
    };
  }
}

export function initializeTelegram(): () => void {
  const webApp = window.Telegram?.WebApp;
  const applyTheme = () => {
    document.documentElement.dataset.telegramTheme =
      webApp?.colorScheme ?? "light";
  };

  webApp?.ready?.();
  webApp?.expand?.();
  applyTheme();
  webApp?.onEvent?.("themeChanged", applyTheme);

  return () => webApp?.offEvent?.("themeChanged", applyTheme);
}

export function getTelegramInitData(): string {
  return window.Telegram?.WebApp?.initData ?? "";
}

export function scanQrWithTelegram(onResult: (value: string) => void): boolean {
  const webApp = window.Telegram?.WebApp;
  if (!webApp?.showScanQrPopup) return false;

  webApp.showScanQrPopup(
    { text: "Наведите камеру на QR-код карты" },
    (value) => {
      if (!value) return false;
      onResult(value);
      webApp.closeScanQrPopup?.();
      return true;
    },
  );
  return true;
}

export function closeTelegramScanner(): void {
  window.Telegram?.WebApp?.closeScanQrPopup?.();
}

export {};

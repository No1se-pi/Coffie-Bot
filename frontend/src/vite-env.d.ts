/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEV_API_PROXY?: string;
  readonly VITE_USE_DEMO_DATA?: "true" | "false";
  readonly VITE_BRAND_NAME?: string;
  readonly VITE_BRAND_SHORT_NAME?: string;
  readonly VITE_BRAND_GREETING?: string;
  readonly VITE_CURRENCY_NAME?: string;
  readonly VITE_TELEGRAM_BOT_USERNAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

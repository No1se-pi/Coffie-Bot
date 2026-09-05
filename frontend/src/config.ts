export const brand = {
  name: import.meta.env.VITE_BRAND_NAME ?? "Кофейня и Точка!",
  shortName: import.meta.env.VITE_BRAND_SHORT_NAME ?? "К",
  greeting: import.meta.env.VITE_BRAND_GREETING ?? "Программа лояльности",
  currencyName: import.meta.env.VITE_CURRENCY_NAME ?? "баллы",
};

export const telegramBotUsername = (
  import.meta.env.VITE_TELEGRAM_BOT_USERNAME ?? ""
).replace(/^@/, "");

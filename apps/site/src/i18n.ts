import { useCallback, useEffect, useMemo, useState } from "react";

export const LOCALE_STORAGE_KEY = "tg-manager-site-locale-v1";
export type Locale = "ru" | "en";

const ru = {
  "app.title": "Telegram Manager / Аккаунт",
  "login.title": "Личный кабинет",
  "login.subtitle": "Введите одноразовый ключ из бота, чтобы открыть статистику.",
  "login.tokenLabel": "Ключ доступа",
  "login.tokenPlaceholder": "Вставьте ключ из Telegram",
  "login.submit": "Вход",
  "login.loading": "Проверяем ключ…",
  "login.error": "Не удалось войти. Проверьте ключ и попробуйте снова.",
  "nav.overview": "Обзор",
  "nav.activity": "Активность",
  "nav.chats": "Мои чаты",
  "nav.plans": "Тарифы",
  "nav.profile": "Профиль",
  "nav.admin": "Администрирование",
  "common.loading": "Загрузка…",
  "common.retry": "Повторить",
  "common.logout": "Выйти",
  "common.allChats": "Все чаты",
  "common.messages": "Сообщения",
  "common.activeUsers": "Активные пользователи",
  "common.joins": "Новые участники",
  "common.leaves": "Ушли",
  "common.netGrowth": "Чистый прирост",
  "common.moderation": "Модерация",
  "common.period": "Период",
  "common.chat": "Чат",
  "common.noData": "За этот период данных пока нет.",
  "period.1": "Сегодня",
  "period.7": "7 дней",
  "period.30": "30 дней",
  "period.90": "90 дней",
  "metric.messages": "Сообщения",
  "metric.activeUsers": "Активные пользователи",
  "metric.joins": "Новые участники",
  "metric.leaves": "Ушли",
  "metric.netGrowth": "Чистый прирост",
  "metric.moderationActions": "Действия модерации",
  "chart.noData": "Нет данных для графика",
  "chart.tooltipDate": "Дата",
  "chart.tooltipValue": "Значение",
  "chat.select": "Выберите чат",
  "chat.analyticsUnavailable": "Аналитика недоступна для этого чата",
  "activity.title": "Активность",
  "activity.chart": "Динамика сообщений",
  "activity.point": "{date}: {value}",
  "scope.analytics": "Аналитика доступна для {count} чатов",
  "scope.chats": "Подключено чатов: {count}",
  "theme.light": "Светлая тема",
  "theme.dark": "Тёмная тема",
  "language.ru": "Русский",
  "language.en": "English",
} as const;

type Dictionary = typeof ru;
const en: Dictionary = {
  "app.title": "Telegram Manager / Account",
  "login.title": "Account dashboard",
  "login.subtitle": "Enter the one-time key from the bot to open your statistics.",
  "login.tokenLabel": "Access key",
  "login.tokenPlaceholder": "Paste the key from Telegram",
  "login.submit": "Sign in",
  "login.loading": "Checking key…",
  "login.error": "Could not sign in. Check the key and try again.",
  "nav.overview": "Overview",
  "nav.activity": "Activity",
  "nav.chats": "My chats",
  "nav.plans": "Plans",
  "nav.profile": "Profile",
  "nav.admin": "Administration",
  "common.loading": "Loading…",
  "common.retry": "Try again",
  "common.logout": "Sign out",
  "common.allChats": "All chats",
  "common.messages": "Messages",
  "common.activeUsers": "Active users",
  "common.joins": "New members",
  "common.leaves": "Left",
  "common.netGrowth": "Net growth",
  "common.moderation": "Moderation",
  "common.period": "Period",
  "common.chat": "Chat",
  "common.noData": "There is no data for this period yet.",
  "period.1": "Today",
  "period.7": "7 days",
  "period.30": "30 days",
  "period.90": "90 days",
  "metric.messages": "Messages",
  "metric.activeUsers": "Active users",
  "metric.joins": "New members",
  "metric.leaves": "Left",
  "metric.netGrowth": "Net growth",
  "metric.moderationActions": "Moderation actions",
  "chart.noData": "No chart data",
  "chart.tooltipDate": "Date",
  "chart.tooltipValue": "Value",
  "chat.select": "Select a chat",
  "chat.analyticsUnavailable": "Analytics are unavailable for this chat",
  "activity.title": "Activity",
  "activity.chart": "Message activity",
  "activity.point": "{date}: {value}",
  "scope.analytics": "Analytics available for {count} chats",
  "scope.chats": "Connected chats: {count}",
  "theme.light": "Light theme",
  "theme.dark": "Dark theme",
  "language.ru": "Русский",
  "language.en": "English",
};

export type TranslationKey = keyof Dictionary;
export type Translator = (key: TranslationKey, values?: Record<string, string | number>) => string;

export const dictionaries: Record<Locale, Dictionary> = { ru, en };

export function normalizeLocale(value: string | null | undefined): Locale | null {
  if (!value) return null;
  return value.toLowerCase().startsWith("ru") ? "ru" : value.toLowerCase().startsWith("en") ? "en" : null;
}

type LocaleSources = { persisted?: string | null; telegram?: string | null; browser?: string | null; fallback?: Locale };

export function resolveLocale({ persisted, telegram, browser, fallback = "en" }: LocaleSources = {}): Locale {
  return normalizeLocale(persisted) ?? normalizeLocale(telegram) ?? normalizeLocale(browser) ?? fallback;
}

function safeStorage(): Storage | null {
  try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; }
}

export function getStoredLocale(storage: Storage | null = safeStorage()): Locale | null {
  if (!storage) return null;
  try {
    const raw = storage.getItem(LOCALE_STORAGE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as { version?: unknown; locale?: unknown };
    return value.version === 1 && typeof value.locale === "string" ? normalizeLocale(value.locale) : null;
  } catch { return null; }
}

export function persistLocale(locale: Locale, storage: Storage | null = safeStorage()): void {
  try { storage?.setItem(LOCALE_STORAGE_KEY, JSON.stringify({ version: 1, locale })); } catch { /* private mode */ }
}

export function createTranslator(locale: Locale): Translator {
  const dictionary = dictionaries[locale];
  return (key, values = {}) => {
    let text = dictionary[key] ?? ru[key];
    for (const [name, value] of Object.entries(values)) text = text.replaceAll(`{${name}}`, String(value));
    return text;
  };
}

export function formatNumber(value: number, locale: Locale): string {
  return new Intl.NumberFormat(locale === "ru" ? "ru-RU" : "en-US", { maximumFractionDigits: 0 }).format(value);
}

export function formatDate(value: string | Date, locale: Locale): string {
  return new Intl.DateTimeFormat(locale === "ru" ? "ru-RU" : "en-US", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value));
}

export function useI18n(telegramLanguage?: string | null): { locale: Locale; setLocale: (next: Locale) => void; t: Translator } {
  const [locale, setLocaleState] = useState<Locale>(() => resolveLocale({ persisted: getStoredLocale(), telegram: telegramLanguage, browser: typeof navigator === "undefined" ? null : navigator.language }));
  const setLocale = useCallback((next: Locale) => { setLocaleState(next); persistLocale(next); }, []);
  const t = useMemo(() => createTranslator(locale), [locale]);
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = t("app.title");
  }, [locale, t]);
  return { locale, setLocale, t };
}

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
  "common.previous": "к прошлому",
  "common.new": "новое",
  "common.openChat": "Открыть чат",
  "common.daysShort": "д",
  "common.metric": "Метрика",
  "common.error": "ОШИБКА",
  "common.accountError": "Не удалось загрузить аккаунт",
  "common.accountUnavailable": "Аккаунт недоступен",
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
  "activity.eyebrow": "ИЗМЕРЕННАЯ АКТИВНОСТЬ",
  "activity.subtitle": "Сравнивайте движение в управляемых чатах, сохраняя контекст происходящего.",
  "activity.interventions": "Действия модерации",
  "activity.noModeration": "За этот период действий модерации нет.",
  "activity.behaviour": "ПОВЕДЕНИЕ",
  "activity.memberFlow": "Движение участников",
  "overview.context": "УПРАВЛЯЕМЫЕ ЧАТЫ: {count}",
  "overview.title": "Сигнал под контролем.",
  "overview.subtitle": "Активность, модерация и тарифы в одном спокойном рабочем пространстве.",
  "overview.openActivity": "Открыть активность",
  "overview.signal": "СИГНАЛ / {days} ДНЕЙ",
  "overview.fullReport": "Полный отчёт",
  "overview.focus": "ФОКУС",
  "overview.now": "Что важно сейчас",
  "overview.moderationDetail": "автоматически: {automated} · вами: {mine}",
  "overview.members": "Участники во всех чатах",
  "overview.paidPlans": "Платных тарифов: {count}",
  "overview.reviewChats": "Посмотреть чаты",
  "overview.space": "ВАШЕ ПРОСТРАНСТВО",
  "overview.seeAll": "Все чаты",
  "chats.eyebrow": "ПОДКЛЮЧЁННЫЕ ЧАТЫ",
  "chats.subtitle": "Каждый чат, где вы администратор, его тариф и текущий охват данных.",
  "chats.empty": "Подключённых чатов пока нет.",
  "plans.eyebrow": "КАРТА ВОЗМОЖНОСТЕЙ",
  "plans.subtitle": "Тариф закреплён за чатом, чтобы каждая команда получала нужный набор функций.",
  "plans.free": "Бесплатно",
  "plans.forever": "навсегда",
  "plans.showLess": "Свернуть",
  "plans.viewAll": "Все возможности",
  "plans.complete": "Полный список возможностей",
  "profile.managedChats": "Управляемые чаты",
  "profile.ownedChats": "Ваши чаты",
  "profile.paidPlans": "Платные тарифы",
  "profile.members": "Известные участники",
  "profile.identity": "ИДЕНТИЧНОСТЬ",
  "profile.details": "Данные аккаунта",
  "profile.firstSeen": "Впервые замечен",
  "profile.language": "Язык",
  "profile.planStatus": "Статус аккаунта",
  "profile.access": "ДОСТУП",
  "profile.security": "Безопасность",
  "profile.securityCopy": "Сайт использует короткоживущий ключ от бота. Telegram ID определяется на сервере, браузер не выбирает чужие данные.",
  "profile.encrypted": "Сессия защищена при передаче",
  "profile.oneTime": "Одноразовый ключ погашен",
  "scope.analytics": "Аналитика доступна для {count} чатов",
  "scope.chats": "Подключено чатов: {count}",
  "theme.light": "Светлая тема",
  "theme.dark": "Тёмная тема",
  "language.ru": "Русский",
  "language.en": "English",
} as const;

type Dictionary = { [Key in keyof typeof ru]: string };
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
  "common.previous": "vs previous",
  "common.new": "new",
  "common.openChat": "Open chat",
  "common.daysShort": "d",
  "common.metric": "Metric",
  "common.error": "ERROR",
  "common.accountError": "Could not load account",
  "common.accountUnavailable": "Account unavailable",
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
  "activity.eyebrow": "MEASURED ACTIVITY",
  "activity.subtitle": "Compare movement across managed chats without losing the shape of the story.",
  "activity.interventions": "Moderation actions",
  "activity.noModeration": "No moderation actions in this period.",
  "activity.behaviour": "BEHAVIOUR",
  "activity.memberFlow": "Member flow",
  "overview.context": "MANAGED CHATS: {count}",
  "overview.title": "Signal, composed.",
  "overview.subtitle": "Activity, moderation and plans in one calm command center.",
  "overview.openActivity": "Open activity",
  "overview.signal": "SIGNAL / {days} DAYS",
  "overview.fullReport": "Full report",
  "overview.focus": "FOCUS",
  "overview.now": "What matters now",
  "overview.moderationDetail": "automated: {automated} · yours: {mine}",
  "overview.members": "Members across chats",
  "overview.paidPlans": "Paid plans: {count}",
  "overview.reviewChats": "Review chats",
  "overview.space": "YOUR SPACE",
  "overview.seeAll": "See all",
  "chats.eyebrow": "CONNECTED CHATS",
  "chats.subtitle": "Every room you manage, its current plan and the data it contributes.",
  "chats.empty": "No connected chats yet.",
  "plans.eyebrow": "CAPABILITY MAP",
  "plans.subtitle": "Plans attach to chats, so each team gets the controls it needs.",
  "plans.free": "Free",
  "plans.forever": "forever",
  "plans.showLess": "Show less",
  "plans.viewAll": "View all capabilities",
  "plans.complete": "Complete capability list",
  "profile.managedChats": "Managed chats",
  "profile.ownedChats": "Owned chats",
  "profile.paidPlans": "Paid plans",
  "profile.members": "Known members",
  "profile.identity": "IDENTITY",
  "profile.details": "Account details",
  "profile.firstSeen": "First seen",
  "profile.language": "Language",
  "profile.planStatus": "Account status",
  "profile.access": "ACCESS",
  "profile.security": "Security",
  "profile.securityCopy": "This site uses a short-lived key issued by the bot. Telegram ID is resolved server-side; the browser cannot choose another account.",
  "profile.encrypted": "Session encrypted in transit",
  "profile.oneTime": "One-time key redeemed",
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

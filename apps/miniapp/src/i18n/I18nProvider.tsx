/**
 * The locale, as React sees it.
 *
 * DECISION: the chosen locale is persisted to `localStorage`, unlike the session
 * token. It is a preference, not a credential — and a user who switched the
 * panel to English because the Russian translation of a setting reads oddly
 * should not have to switch again on every launch.
 *
 * DECISION: changing the locale also sets it on the API client, which sends it
 * as `Accept-Language`. Problem titles come back localized by the server, so a
 * panel in Russian showing an English error would be the seam that gives away
 * that two systems are involved.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { setLocale as setClientLocale } from "../api/client";
import { telegramLanguage } from "../telegram/theme";
import { type Args, type Locale, LOCALES, resolveLocale, translate } from "./bundles";

const STORAGE_KEY = "tgm.locale";

export interface I18n {
  locale: Locale;
  t: (key: string, args?: Args) => string;
  setLocale: (locale: Locale) => void;
  available: readonly Locale[];
}

const I18nContext = createContext<I18n | null>(null);

/** Stored choice first, then Telegram's language, then English. */
function initialLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && (LOCALES as readonly string[]).includes(stored)) {
    return stored as Locale;
  }
  return resolveLocale(telegramLanguage());
}

export function I18nProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  useEffect(() => {
    setClientLocale(locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    localStorage.setItem(STORAGE_KEY, next);
    setLocaleState(next);
  }, []);

  const value = useMemo<I18n>(
    () => ({
      locale,
      t: (key: string, args?: Args) => translate(locale, key, args),
      setLocale,
      available: LOCALES,
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (value === null) {
    throw new Error("useI18n must be used inside <I18nProvider>");
  }
  return value;
}

/** The common case: just the translate function. */
export function useT(): (key: string, args?: Args) => string {
  return useI18n().t;
}

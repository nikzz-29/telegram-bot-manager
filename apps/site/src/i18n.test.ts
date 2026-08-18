import { beforeEach, describe, expect, it } from "vitest";

import {
  LOCALE_STORAGE_KEY,
  createTranslator,
  formatDate,
  formatNumber,
  getStoredLocale,
  persistLocale,
  resolveLocale,
  type Locale,
} from "./i18n";

describe("locale selection", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.lang = "en";
  });

  it("prefers a valid persisted locale over Telegram and browser values", () => {
    expect(resolveLocale({ persisted: "ru", telegram: "en", browser: "en-US" })).toBe("ru");
  });

  it("uses Telegram profile language before the browser language", () => {
    expect(resolveLocale({ telegram: "ru-RU", browser: "en-US" })).toBe("ru");
    expect(resolveLocale({ telegram: "de", browser: "ru-RU" })).toBe("ru");
  });

  it("normalizes and versions the persisted preference", () => {
    persistLocale("ru");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe(JSON.stringify({ version: 1, locale: "ru" }));
    expect(getStoredLocale()).toBe("ru");
    window.localStorage.setItem(LOCALE_STORAGE_KEY, JSON.stringify({ version: 0, locale: "en" }));
    expect(getStoredLocale()).toBeNull();
  });
});

describe("translations and formatting", () => {
  it.each([["ru", "Вход"], ["en", "Sign in"]] as const)("translates login label in %s", (locale: Locale, expected: string) => {
    expect(createTranslator(locale)("login.submit")).toBe(expected);
  });

  it("formats values using the selected locale", () => {
    expect(formatNumber(1234567, "ru")).toContain("1");
    expect(formatNumber(1234567, "en")).toContain("1");
    expect(formatDate("2026-08-18", "en")).toMatch(/2026/);
    expect(formatDate("2026-08-18", "ru")).toMatch(/2026/);
  });
});

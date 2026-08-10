/**
 * Telegram's theme, pushed into the CSS variables Tailwind reads.
 *
 * DECISION: the panel never asks "is it dark mode?". Telegram sends the actual
 * colours the user is looking at, including custom themes that are neither light
 * nor dark, so every colour is taken from `themeParams` and the only inference
 * left is the `color-scheme` hint below.
 *
 * DECISION: `themeParams` is subscribed to, not read once. The user can switch
 * themes while the Mini App is open, and a panel that sampled the palette at
 * startup would sit there in the old one until it is relaunched.
 *
 * DECISION: the SDK's own `bindCssVars` is not used. It emits one variable per
 * theme key under names we do not control, which would leave the stylesheet
 * depending on Telegram's naming; this maps the eight colours the panel actually
 * uses onto our own names, and supplies a fallback for each.
 */
import { retrieveLaunchParams, themeParams } from "@telegram-apps/sdk-react";

type ColorSignal = () => string | undefined;

/** CSS variable ← theme signal, with the fallback used when Telegram omits it. */
const MAPPING: ReadonlyArray<readonly [string, ColorSignal, string]> = [
  ["--tg-bg", themeParams.backgroundColor, "#ffffff"],
  ["--tg-surface", themeParams.secondaryBackgroundColor, "#f4f4f5"],
  ["--tg-text", themeParams.textColor, "#000000"],
  ["--tg-hint", themeParams.hintColor, "#707579"],
  ["--tg-link", themeParams.linkColor, "#3390ec"],
  ["--tg-accent", themeParams.buttonColor, "#3390ec"],
  ["--tg-accent-text", themeParams.buttonTextColor, "#ffffff"],
  ["--tg-destructive", themeParams.destructiveTextColor, "#e53935"],
];

function apply(): void {
  const root = document.documentElement;
  for (const [cssVar, signal, fallback] of MAPPING) {
    root.style.setProperty(cssVar, signal() ?? fallback);
  }
  // Telegram has no separator colour, so it is derived from the text colour —
  // the one value guaranteed to contrast with the background it sits on.
  root.style.setProperty("--tg-separator", `${themeParams.textColor() ?? "#000000"}14`);
  // `color-scheme` decides what the *browser* draws — scrollbars, form controls,
  // the flash behind an overscroll — none of which `themeParams` covers.
  root.style.setProperty("color-scheme", themeParams.isDark() ? "dark" : "light");
}

/** Start mirroring Telegram's theme. Returns an unsubscribe function. */
export function bindTheme(): () => void {
  if (!themeParams.mountSync.isAvailable()) {
    // Outside Telegram — the CSS defaults in `index.css` stand.
    return () => undefined;
  }
  themeParams.mountSync();
  apply();
  return themeParams.state.sub(apply);
}

/**
 * The user's Telegram language, when the panel is running inside a client.
 *
 * Read from the launch params rather than `navigator.language`: the browser
 * locale is the phone's, while this is the one the user chose for Telegram.
 */
export function telegramLanguage(): string | null {
  try {
    return retrieveLaunchParams(true).tgWebAppData?.user?.languageCode ?? null;
  } catch {
    // Not running inside Telegram — the dev server in a plain browser.
    return null;
  }
}

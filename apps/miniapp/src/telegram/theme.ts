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

/**
 * The low-alpha tints, as `[variable, source, fallback, alpha]`.
 *
 * DECISION: the alpha is baked in here rather than expressed as a Tailwind
 * `/15` modifier at the call site. Tailwind can only insert an alpha into a
 * colour whose channels it can see, and these all arrive as opaque values — so
 * `bg-hint/40` compiles to nothing at all, with no error. Deriving the tint
 * where the colour is set is also exactly how `--tg-separator` already works.
 *
 * The alpha is two hex digits appended to a `#rrggbb` string: Telegram's SDK
 * normalises every theme colour to that form, which is what makes it safe.
 */
const TINTS: ReadonlyArray<readonly [string, ColorSignal, string, string]> = [
  ["--tg-accent-tint", themeParams.buttonColor, "#3390ec", "1a"], // 10%
  ["--tg-hint-tint", themeParams.hintColor, "#707579", "33"], // 20% — skeletons, tiles
  ["--tg-hint-track", themeParams.hintColor, "#707579", "66"], // 40% — a switch, off
  ["--tg-destructive-tint", themeParams.destructiveTextColor, "#e53935", "1a"], // 10%
];

function apply(): void {
  const root = document.documentElement;
  for (const [cssVar, signal, fallback] of MAPPING) {
    root.style.setProperty(cssVar, signal() ?? fallback);
  }
  for (const [cssVar, signal, fallback, alpha] of TINTS) {
    root.style.setProperty(cssVar, `${signal() ?? fallback}${alpha}`);
  }
  // Telegram has no separator colour, so it is derived from the text colour —
  // the one value guaranteed to contrast with the background it sits on.
  root.style.setProperty("--tg-separator", `${themeParams.textColor() ?? "#000000"}14`);
  // The wash under a pressed row, derived the same way and for the same reason.
  // It is a shade of the text rather than of the accent: a press is feedback
  // that the row was hit, not a claim that anything is now selected.
  root.style.setProperty("--panel-press", `${themeParams.textColor() ?? "#000000"}0f`);
  // `color-scheme` decides what the *browser* draws — scrollbars, form controls,
  // the flash behind an overscroll — none of which `themeParams` covers.
  const isDark = themeParams.isDark();
  root.style.setProperty("color-scheme", isDark ? "dark" : "light");
  const background = themeParams.backgroundColor() ?? (isDark ? "#17212b" : "#ffffff");
  const surface =
    themeParams.secondaryBackgroundColor() ?? (isDark ? "#0f1822" : "#f4f4f5");
  const text = themeParams.textColor() ?? (isDark ? "#f5f7fa" : "#000000");
  const accent = themeParams.buttonColor() ?? "#3390ec";

  // Liquid-glass surfaces must remain theme-aware. Telegram gives opaque
  // colours, so the translucent layers and their highlights are derived here
  // instead of hard-coding a light or dark panel in CSS.
  root.style.setProperty("--glass-fill", `${background}${isDark ? "a8" : "b8"}`);
  root.style.setProperty("--glass-fill-strong", `${background}${isDark ? "d9" : "e8"}`);
  root.style.setProperty("--glass-fill-soft", `${surface}${isDark ? "7a" : "8f"}`);
  root.style.setProperty("--glass-edge", `${text}${isDark ? "20" : "14"}`);
  root.style.setProperty("--glass-highlight", `${isDark ? "#ffffff" : text}${isDark ? "18" : "0a"}`);
  root.style.setProperty("--glass-accent-wash", `${accent}${isDark ? "20" : "14"}`);
  /*
   * Elevation, dropped on a dark theme rather than restated for it.
   *
   * The card shadow is black at 4%, which is what lifts a white card off a grey
   * page. Over a dark ground it moves the colour by one value in 255 — it cannot
   * lift anything, and raising the alpha until it showed would put a halo under
   * every card that Telegram's own dark theme does not have. On dark the card is
   * the *lighter* surface, so the fill difference is already the lift, and the
   * hairline (derived from the text colour, so visible either way) draws the edge.
   *
   * Cleared rather than set to the light value, so `index.css` stays the one
   * place that says how deep the shadow is.
   */
  if (isDark) {
    root.style.setProperty("--panel-shadow-card", "none");
  } else {
    root.style.removeProperty("--panel-shadow-card");
  }
  // What Tailwind's `dark:` variant keys off. It follows Telegram's theme rather
  // than the phone's, which are free to disagree.
  root.classList.toggle("dark", isDark);
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

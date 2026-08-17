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

function apply(): void {
  const root = document.documentElement;
  const isDark = themeParams.isDark();
  const background = isDark ? "#0b0b0d" : "#f3f3f1";
  const card = isDark ? "#171719" : "#ffffff";
  const text = isDark ? "#f5f5f4" : "#111113";
  const hint = isDark ? "#a1a1aa" : "#6b6b72";
  const accent = isDark ? "#fafafa" : "#18181b";
  const accentText = isDark ? "#111113" : "#ffffff";
  const destructive = isDark ? "#d6d6d1" : "#555550";

  root.style.setProperty("--tg-bg", card);
  root.style.setProperty("--tg-surface", background);
  root.style.setProperty("--tg-text", text);
  root.style.setProperty("--tg-hint", hint);
  root.style.setProperty("--tg-link", accent);
  root.style.setProperty("--tg-accent", accent);
  root.style.setProperty("--tg-accent-text", accentText);
  root.style.setProperty("--tg-destructive", destructive);
  root.style.setProperty("--panel-ground", background);
  root.style.setProperty("--panel-card", card);
  root.style.setProperty("--tg-separator", `${text}16`);
  root.style.setProperty("--panel-card-border", `${text}16`);
  root.style.setProperty("--panel-press", `${text}0f`);
  root.style.setProperty("--tg-accent-tint", `${accent}${isDark ? "18" : "0d"}`);
  root.style.setProperty("--tg-hint-tint", `${hint}24`);
  root.style.setProperty("--tg-hint-track", `${hint}59`);
  root.style.setProperty("--tg-destructive-tint", `${destructive}18`);

  root.style.setProperty("color-scheme", isDark ? "dark" : "light");
  root.style.setProperty("--glass-fill", `${card}${isDark ? "d9" : "e6"}`);
  root.style.setProperty("--glass-fill-strong", `${card}${isDark ? "f2" : "f5"}`);
  root.style.setProperty("--glass-fill-soft", `${background}${isDark ? "cc" : "d9"}`);
  root.style.setProperty("--glass-edge", `${text}${isDark ? "20" : "14"}`);
  root.style.setProperty("--glass-highlight", `${isDark ? "#ffffff" : "#ffffff"}${isDark ? "12" : "8c"}`);
  root.style.setProperty("--glass-accent-wash", `${accent}${isDark ? "12" : "0a"}`);
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

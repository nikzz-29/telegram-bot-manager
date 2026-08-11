/**
 * Tailwind, wired to Telegram's palette rather than its own.
 *
 * DECISION: the colour tokens are CSS variables fed from `themeParams`, not
 * Tailwind's default palette. A Mini App that ships its own greys looks pasted
 * into Telegram; one that reads the client's theme follows the user into dark
 * mode, custom themes and whatever Telegram ships next, without a rebuild.
 *
 * DECISION: `ground` and `card` are the names screens are written against, not
 * `bg` and `surface`. The raw Telegram names say where a colour came from; these
 * say what it is for, and the mapping between them (grey ground, light cards) is
 * decided once in `index.css` instead of being re-derived per component.
 *
 * DECISION: the low-alpha tints are their own tokens (`accent-tint`) rather than
 * Tailwind opacity modifiers (`accent/10`). Tailwind can only apply an alpha
 * modifier to a colour whose channels it can see, and every colour here is an
 * opaque `var()` — so `bg-hint/40` is not merely unsupported, it is dropped from
 * the output with no error at all. That silent failure is what left the toggle
 * track, the icon tiles and the destructive button with no fill at all.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  /*
   * DECISION: dark mode keys off a class that `theme.ts` sets from
   * `themeParams.isDark()`, not off `prefers-color-scheme`. Telegram's theme is
   * the user's choice inside Telegram and can be dark while the phone is light;
   * the media query would answer for the phone and get it backwards.
   */
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Semantic — what screens should reach for.
        ground: "var(--panel-ground)",
        card: "var(--panel-card)",
        "card-border": "var(--panel-card-border)",
        // Raw Telegram values, for the few places that genuinely mean "the
        // client's own background" rather than "the panel's ground".
        bg: "var(--tg-bg)",
        surface: "var(--tg-surface)",
        text: "var(--tg-text)",
        hint: "var(--tg-hint)",
        link: "var(--tg-link)",
        accent: "var(--tg-accent)",
        "accent-text": "var(--tg-accent-text)",
        destructive: "var(--tg-destructive)",
        separator: "var(--tg-separator)",
        // The same colours at low alpha — tile fills, skeletons, badge grounds.
        "accent-tint": "var(--tg-accent-tint)",
        "hint-tint": "var(--tg-hint-tint)",
        "hint-track": "var(--tg-hint-track)",
        "destructive-tint": "var(--tg-destructive-tint)",
      },
      borderRadius: {
        card: "12px",
        control: "10px",
      },
      boxShadow: {
        card: "var(--panel-shadow-card)",
      },
      transitionTimingFunction: {
        panel: "var(--panel-ease)",
      },
      fontSize: {
        // The panel's whole type scale — Telegram's own sizes, named by role, so
        // a screen asks for `text-row` instead of remembering `text-[15px]`.
        caption: ["12px", { lineHeight: "16px" }],
        label: ["13px", { lineHeight: "18px" }],
        row: ["15px", { lineHeight: "20px" }],
        title: ["17px", { lineHeight: "22px" }],
        display: ["22px", { lineHeight: "28px", letterSpacing: "-0.01em" }],
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
      },
      spacing: {
        // The bottom inset on a notched phone, so a screen's last row never sits
        // under the home indicator. `viewport-fit=cover` is what makes it real.
        safe: "env(safe-area-inset-bottom, 0px)",
      },
    },
  },
  plugins: [],
};

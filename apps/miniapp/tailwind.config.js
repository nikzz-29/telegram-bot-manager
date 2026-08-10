/**
 * Tailwind, wired to Telegram's palette rather than its own.
 *
 * DECISION: the colour tokens are CSS variables fed from `themeParams`, not
 * Tailwind's default palette. A Mini App that ships its own greys looks pasted
 * into Telegram; one that reads the client's theme follows the user into dark
 * mode, custom themes and whatever Telegram ships next, without a rebuild.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--tg-bg)",
        surface: "var(--tg-surface)",
        text: "var(--tg-text)",
        hint: "var(--tg-hint)",
        link: "var(--tg-link)",
        accent: "var(--tg-accent)",
        "accent-text": "var(--tg-accent-text)",
        destructive: "var(--tg-destructive)",
        separator: "var(--tg-separator)",
      },
      borderRadius: {
        card: "12px",
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
    },
  },
  plugins: [],
};

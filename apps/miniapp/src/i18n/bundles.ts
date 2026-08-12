/**
 * Fluent, over the same `.ftl` files the bot reads.
 *
 * DECISION: the locale bundles are compiled into the app rather than fetched.
 * There are two of them, they total a few kilobytes, and a Mini App is judged on
 * the gap between tapping the button and seeing a panel — a round-trip for UI
 * copy is the one request most worth not making.
 *
 * DECISION: a missing key renders as the key itself, never as an empty string or
 * a crash. A blank row in a settings screen is a bug you find in production; a
 * literal `section-moderation` in the UI is one you find while writing it.
 *
 * DECISION: the `main.ftl` the bot uses is imported alongside a panel-only
 * `panel.ftl`. Keys the bot already has — plan names, module titles, error
 * messages the API returns by key — are reused verbatim rather than translated a
 * second time, which is what keeps the panel and the chat saying the same words.
 * `dm.ftl` and `guide.ftl` come along for the same reason: they are the bot's
 * other two catalogues, and `i18n.runtime.BOT_CATALOGUES` is the list this must
 * mirror. A key defined in two of them resolves to whichever loads first here.
 */
import { FluentBundle, FluentResource } from "@fluent/bundle";
import { negotiateLanguages } from "@fluent/langneg";
import enDm from "@locales/en/dm.ftl?raw";
import enGuide from "@locales/en/guide.ftl?raw";
import enMain from "@locales/en/main.ftl?raw";
import enPanel from "@locales/en/panel.ftl?raw";
import ruDm from "@locales/ru/dm.ftl?raw";
import ruGuide from "@locales/ru/guide.ftl?raw";
import ruMain from "@locales/ru/main.ftl?raw";
import ruPanel from "@locales/ru/panel.ftl?raw";

export const LOCALES = ["ru", "en"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

const SOURCES: Record<Locale, readonly string[]> = {
  en: [enMain, enDm, enGuide, enPanel],
  ru: [ruMain, ruDm, ruGuide, ruPanel],
};

/** Values a Fluent message can be given. `Date` is formatted by the bundle. */
export type Args = Record<string, string | number | Date>;

const bundles = new Map<Locale, FluentBundle>();

function bundleFor(locale: Locale): FluentBundle {
  const existing = bundles.get(locale);
  if (existing) {
    return existing;
  }
  // `useIsolating` off: Fluent otherwise wraps every placeable in U+2068/U+2069
  // directional isolates, which are invisible in a browser but show up the moment
  // a value is compared, copied out, or put in a test assertion.
  const bundle = new FluentBundle(locale, { useIsolating: false });
  for (const source of SOURCES[locale]) {
    // Parse errors are per-message: a broken entry is dropped and the rest of the
    // file still loads, which is the same thing the Python side does.
    bundle.addResource(new FluentResource(source));
  }
  bundles.set(locale, bundle);
  return bundle;
}

/**
 * Pick the best locale we ship for a Telegram language code.
 *
 * Telegram sends things like `ru`, `en-GB` and `pt-br`; `negotiateLanguages`
 * matches those against what we have without us hand-rolling a prefix check.
 */
export function resolveLocale(requested: string | null | undefined): Locale {
  if (!requested) {
    return DEFAULT_LOCALE;
  }
  const [best] = negotiateLanguages([requested], [...LOCALES], {
    defaultLocale: DEFAULT_LOCALE,
    strategy: "lookup",
  });
  return (best as Locale | undefined) ?? DEFAULT_LOCALE;
}

/**
 * Translate one key, falling back to English and then to the key itself.
 *
 * The English fallback matters for a partially translated build: a Russian panel
 * missing one new key should show that row in English, not break the screen.
 */
export function translate(locale: Locale, key: string, args?: Args): string {
  for (const candidate of locale === DEFAULT_LOCALE ? [locale] : [locale, DEFAULT_LOCALE]) {
    const bundle = bundleFor(candidate);
    const message = bundle.getMessage(key);
    if (message?.value) {
      return bundle.formatPattern(message.value, args);
    }
  }
  return key;
}

/** Whether a key exists at all — used to decide between a label and a raw name. */
export function hasMessage(locale: Locale, key: string): boolean {
  return (
    bundleFor(locale).hasMessage(key) ||
    (locale !== DEFAULT_LOCALE && bundleFor(DEFAULT_LOCALE).hasMessage(key))
  );
}

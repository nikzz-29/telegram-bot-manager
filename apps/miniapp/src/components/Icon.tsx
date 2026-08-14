/**
 * The panel's icons.
 *
 * DECISION: hand-written inline SVG, not an icon package. The whole set is the
 * seven names `core.registry` already assigns to module sections plus a handful
 * of affordances; pulling in a library to draw eleven glyphs would cost more
 * bundle than the glyphs, and a Mini App is loaded over a phone connection every
 * time it is opened.
 *
 * DECISION: every icon is stroked, never filled, and inherits `currentColor` at
 * 1.6px. That is Telegram's own drawing style, and inheriting the colour means
 * an icon is themed by whatever row it sits in — hint in a subtitle, destructive
 * in a delete row — without any icon knowing about the palette.
 *
 * DECISION: the registry's icon name is the lookup key, and an unknown name
 * falls back to `settings` rather than rendering nothing. A module added
 * server-side with an icon this build has never heard of should look plain, not
 * broken — the panel ships separately from the API and will lag it.
 */
import React from "react";

export type IconName =
  | "shield"
  | "door"
  | "chart"
  | "spark"
  | "clock"
  | "sparkles"
  | "globe"
  | "settings"
  | "chevron"
  | "check"
  | "chat"
  | "star"
  | "plus"
  | "trash"
  | "refresh"
  | "alert"
  | "user"
  | "home";

/** The `d` of each glyph, drawn on a 24×24 grid. */
const PATHS: Record<IconName, readonly string[]> = {
  // --- the seven the registry names -----------------------------------------
  shield: ["M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6l7-3z"],
  door: ["M14 3H6v18h8", "M14 3l4 2v14l-4 2z", "M11 12h.01"],
  chart: ["M4 20V10", "M10 20V4", "M16 20v-7", "M22 20H2"],
  spark: ["M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2L12 3z"],
  clock: ["M12 21a9 9 0 100-18 9 9 0 000 18z", "M12 7v5l3.5 2"],
  sparkles: [
    "M11 3l1.7 4.3L17 9l-4.3 1.7L11 15l-1.7-4.3L5 9l4.3-1.7L11 3z",
    "M18 14l.9 2.1L21 17l-2.1.9L18 20l-.9-2.1L15 17l2.1-.9L18 14z",
  ],
  globe: ["M12 21a9 9 0 100-18 9 9 0 000 18z", "M3 12h18", "M12 3c2.5 2.5 3.8 5.6 3.8 9S14.5 18.5 12 21c-2.5-2.5-3.8-5.6-3.8-9S9.5 5.5 12 3z"],

  // --- affordances -----------------------------------------------------------
  settings: [
    "M12 15a3 3 0 100-6 3 3 0 000 6z",
    "M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5v.2a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1A1.7 1.7 0 004.6 9a1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1h.2a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z",
  ],
  chevron: ["M9 6l6 6-6 6"],
  check: ["M4 12.5l5 5L20 6.5"],
  chat: ["M21 11.5a8.4 8.4 0 01-9 8.4 8.9 8.9 0 01-4-.9L3 21l1.9-5a8.4 8.4 0 01-.9-4 8.4 8.4 0 018.4-8.4h.6A8.4 8.4 0 0121 11v.5z"],
  star: ["M12 3l2.9 5.8 6.4.9-4.6 4.5 1 6.4-5.7-3-5.7 3 1-6.4L2.7 9.7l6.4-.9L12 3z"],
  plus: ["M12 5v14", "M5 12h14"],
  trash: ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14H6L5 6", "M10 11v6", "M14 11v6"],
  refresh: ["M21 12a9 9 0 11-2.6-6.4", "M21 3v6h-6"],
  alert: ["M12 9v4", "M12 17h.01", "M12 3l9 16H3l9-16z"],
  user: ["M12 12a4 4 0 100-8 4 4 0 000 8z", "M4.5 21a7.5 7.5 0 0115 0"],
  home: ["M3 11.5L12 4l9 7.5", "M5.5 10.5V21h13V10.5", "M9.5 21v-6h5v6"],
};

export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: string;
  size?: number;
  className?: string;
}): React.JSX.Element {
  const paths = PATHS[name as IconName] ?? PATHS.settings;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      // The icon is always adjacent to the label it belongs to, so announcing it
      // would just read the same word twice.
      aria-hidden="true"
      focusable="false"
    >
      {paths.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/**
 * An icon in a rounded tile, the way Telegram draws a settings section.
 *
 * The tint is the accent at low alpha rather than a solid fill: a column of
 * saturated tiles fights the content, and the accent is the one colour the
 * user's theme guarantees looks right against a card.
 */
export function IconTile({
  name,
  tone = "accent",
}: {
  name: string;
  tone?: "accent" | "hint" | "destructive";
}): React.JSX.Element {
  const tint = {
    accent: "bg-accent-tint text-accent",
    hint: "bg-hint-tint text-hint",
    destructive: "bg-destructive-tint text-destructive",
  }[tone];
  return (
    <span
      className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-[8px] ${tint}`}
    >
      <Icon name={name} size={18} />
    </span>
  );
}

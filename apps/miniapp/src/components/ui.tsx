/**
 * The primitives every section is built from.
 *
 * They exist so the settings screens describe *what* they show rather than how a
 * Telegram list row is spelled in Tailwind, and so a change to that spelling
 * lands in one file.
 *
 * DECISION: these mirror Telegram's own grouped-list idiom rather than inventing
 * a look. A Mini App is judged against the client it opens inside — the settings
 * screen one swipe away is the comparison the user actually makes — so the
 * geometry here (48px rows, hairline separators, grey ground, uppercase group
 * headings, chevrons on anything that navigates) is copied from that, not chosen.
 */
import React from "react";
import { Icon, IconTile } from "./Icon";
import { useT } from "../i18n/I18nProvider";
import { haptic } from "../telegram/sdk";

export { Icon, IconTile };

export function Screen({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div className="mx-auto w-full max-w-2xl px-3 pb-[calc(6rem+theme(spacing.safe))]">
      {children}
    </div>
  );
}

/**
 * A screen's own title, above the first group.
 *
 * DECISION: the panel draws its own title even though Telegram shows the bot's
 * name in the header. That header says which bot you are in; this says which
 * screen — and without it every screen below the root opened with an anonymous
 * list of rows and no statement of what had just been navigated into.
 */
export function Header({
  title,
  subtitle,
  icon,
  action,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: string;
  action?: React.ReactNode;
}): React.JSX.Element {
  return (
    <header className="flex items-start gap-3 px-1 pb-1 pt-4">
      {icon !== undefined && (
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-accent-tint text-accent">
          <Icon name={icon} size={22} />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-display font-semibold">{title}</h1>
        {subtitle !== undefined && (
          <p className="mt-0.5 text-label text-hint">{subtitle}</p>
        )}
      </div>
      {action !== undefined && <div className="shrink-0 pt-1">{action}</div>}
    </header>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <h2 className="tg-section-title">{children}</h2>;
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}): React.JSX.Element {
  return <div className={`tg-card ${className}`}>{children}</div>;
}

/**
 * One cell of a grouped list.
 *
 * DECISION: a row that navigates gets a chevron, automatically. It was the
 * single clearest thing missing — every row looked identical whether it opened a
 * screen, toggled a switch or just stated a fact, so the list gave the user no
 * way to tell what would happen before tapping. `right` overrides it, because a
 * row with a toggle or a badge already says what it does.
 */
export function Row({
  title,
  subtitle,
  right,
  icon,
  iconTone,
  onClick,
  disabled = false,
  destructive = false,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  icon?: string;
  iconTone?: "accent" | "hint" | "destructive";
  onClick?: () => void;
  disabled?: boolean;
  destructive?: boolean;
}): React.JSX.Element {
  const navigates = onClick !== undefined && !disabled;
  const content = (
    <>
      {icon !== undefined && (
        <IconTile name={icon} tone={iconTone ?? (destructive ? "destructive" : "accent")} />
      )}
      <div className="min-w-0 flex-1">
        <div className={`truncate text-row ${destructive ? "text-destructive" : ""}`}>
          {title}
        </div>
        {subtitle !== undefined && (
          <div className="mt-0.5 text-label leading-snug text-hint">{subtitle}</div>
        )}
      </div>
      {right !== undefined ? (
        <div className="shrink-0">{right}</div>
      ) : (
        navigates && <Icon name="chevron" size={18} className="shrink-0 text-hint opacity-60" />
      )}
    </>
  );

  if (onClick === undefined) {
    return <div className="tg-row">{content}</div>;
  }
  return (
    <button
      type="button"
      disabled={disabled}
      className="tg-row tg-row-pressable w-full text-left disabled:opacity-50"
      onClick={() => {
        haptic();
        onClick();
      }}
    >
      {content}
    </button>
  );
}

/** A small pill: a plan, a state, a count. */
export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "accent" | "success" | "warning" | "destructive";
}): React.JSX.Element {
  // Emerald and amber keep their opacity modifiers: they are Tailwind's own
  // palette, so their channels are known and an alpha can be computed. The
  // theme-derived colours cannot do that and use the pre-mixed tints instead.
  const styles = {
    neutral: "bg-hint-tint text-hint",
    accent: "bg-accent text-accent-text",
    success: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
    warning: "bg-amber-500/15 text-amber-600 dark:text-amber-500",
    destructive: "bg-destructive-tint text-destructive",
  }[tone];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-caption font-medium ${styles}`}
    >
      {children}
    </span>
  );
}

/**
 * A Telegram-style switch.
 *
 * Rendered from a real `<input type="checkbox">` so it keeps the keyboard and
 * screen-reader behaviour a `<div role="switch">` would have to reimplement.
 */
export function Toggle({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
}): React.JSX.Element {
  return (
    <label
      className={`relative inline-flex h-[31px] w-[51px] shrink-0 ${
        disabled ? "opacity-50" : "cursor-pointer"
      }`}
    >
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        disabled={disabled}
        onChange={(event) => {
          haptic();
          onChange(event.target.checked);
        }}
      />
      <span className="absolute inset-0 rounded-full bg-hint-track transition-colors duration-[--panel-motion] ease-panel peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent" />
      <span className="absolute left-0.5 top-0.5 h-[27px] w-[27px] rounded-full bg-white shadow transition-transform duration-[--panel-motion] ease-panel peer-checked:translate-x-5" />
    </label>
  );
}

export function Button({
  children,
  onClick,
  disabled = false,
  variant = "primary",
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "destructive";
  type?: "button" | "submit";
}): React.JSX.Element {
  const styles = {
    primary: "bg-accent text-accent-text",
    secondary: "bg-card border border-card-border text-link",
    destructive: "bg-destructive-tint text-destructive",
  }[variant];
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={
        onClick &&
        (() => {
          haptic();
          onClick();
        })
      }
      className={`w-full rounded-control px-4 py-3 text-row font-medium transition-opacity duration-[--panel-motion] active:opacity-70 disabled:opacity-50 ${styles}`}
    >
      {children}
    </button>
  );
}

export function Spinner(): React.JSX.Element {
  const t = useT();
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-row text-hint">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-hint-tint border-t-hint" />
      {t("panel-loading")}
    </div>
  );
}

/**
 * The shape of the content that is coming, drawn while it loads.
 *
 * DECISION: list screens show this instead of a spinner. A spinner says "wait";
 * a skeleton says "a list of rows is arriving here", which is both less jarring
 * when it resolves and honest about the layout — the page does not jump, because
 * the placeholder is the same height as the rows that replace it.
 */
export function SkeletonRows({ count = 3 }: { count?: number }): React.JSX.Element {
  return (
    <Card>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="tg-row">
          <span className="tg-skeleton h-[30px] w-[30px] shrink-0 rounded-[8px]" />
          <div className="min-w-0 flex-1">
            {/* Uneven widths: rows of identical bars read as a table, not as text. */}
            <span
              className="tg-skeleton block h-[15px]"
              style={{ width: `${58 + ((index * 13) % 30)}%` }}
            />
            <span
              className="tg-skeleton mt-1.5 block h-[11px]"
              style={{ width: `${34 + ((index * 17) % 22)}%` }}
            />
          </div>
        </div>
      ))}
    </Card>
  );
}

export function EmptyState({
  text,
  icon,
  action,
}: {
  text: string;
  icon?: string;
  action?: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="px-6 py-10 text-center">
      {icon !== undefined && (
        <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-hint-tint text-hint">
          <Icon name={icon} size={24} />
        </span>
      )}
      <p className="text-row text-hint">{text}</p>
      {action !== undefined && <div className="mx-auto mt-4 max-w-[240px]">{action}</div>}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}): React.JSX.Element {
  const t = useT();
  return (
    <div className="px-6 py-10 text-center">
      <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-destructive-tint text-destructive">
        <Icon name="alert" size={24} />
      </span>
      <p className="text-row text-destructive">{message}</p>
      {onRetry !== undefined && (
        <div className="mx-auto mt-4 max-w-[200px]">
          <Button variant="secondary" onClick={onRetry}>
            {t("panel-retry")}
          </Button>
        </div>
      )}
    </div>
  );
}

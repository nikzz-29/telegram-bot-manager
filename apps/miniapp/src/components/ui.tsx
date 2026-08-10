/**
 * The handful of primitives every section is built from.
 *
 * They exist so the settings screens describe *what* they show rather than how
 * a Telegram list row is spelled in Tailwind, and so a change to that spelling
 * lands in one file.
 */
import React from "react";
import { useT } from "../i18n/I18nProvider";
import { haptic } from "../telegram/sdk";

export function Screen({ children }: { children: React.ReactNode }): React.JSX.Element {
  return <div className="mx-auto w-full max-w-2xl px-3 pb-24">{children}</div>;
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

export function Row({
  title,
  subtitle,
  right,
  onClick,
  destructive = false,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  right?: React.ReactNode;
  onClick?: () => void;
  destructive?: boolean;
}): React.JSX.Element {
  const content = (
    <>
      <div className="min-w-0 flex-1">
        <div className={`truncate text-[15px] ${destructive ? "text-destructive" : ""}`}>
          {title}
        </div>
        {subtitle !== undefined && (
          <div className="mt-0.5 text-[13px] leading-snug text-hint">{subtitle}</div>
        )}
      </div>
      {right !== undefined && <div className="shrink-0">{right}</div>}
    </>
  );
  if (onClick === undefined) {
    return <div className="tg-row">{content}</div>;
  }
  return (
    <button
      type="button"
      className="tg-row w-full text-left active:opacity-60"
      onClick={() => {
        haptic();
        onClick();
      }}
    >
      {content}
    </button>
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
    <label className={`relative inline-flex h-[31px] w-[51px] shrink-0 ${disabled ? "opacity-50" : "cursor-pointer"}`}>
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
      <span className="absolute inset-0 rounded-full bg-hint/40 transition-colors peer-checked:bg-accent peer-focus-visible:ring-2 peer-focus-visible:ring-accent" />
      <span className="absolute left-0.5 top-0.5 h-[27px] w-[27px] rounded-full bg-white shadow transition-transform peer-checked:translate-x-5" />
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
    secondary: "bg-surface text-link",
    destructive: "bg-surface text-destructive",
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
      className={`w-full rounded-lg px-4 py-3 text-[15px] font-medium disabled:opacity-50 ${styles}`}
    >
      {children}
    </button>
  );
}

export function Spinner(): React.JSX.Element {
  const t = useT();
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-[15px] text-hint">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-hint/30 border-t-hint" />
      {t("panel-loading")}
    </div>
  );
}

export function EmptyState({ text }: { text: string }): React.JSX.Element {
  return <p className="px-4 py-8 text-center text-[15px] text-hint">{text}</p>;
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
    <div className="px-4 py-8 text-center">
      <p className="text-[15px] text-destructive">{message}</p>
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

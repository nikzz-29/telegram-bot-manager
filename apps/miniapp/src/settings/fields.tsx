/**
 * One input per field kind, plus the grouping that keeps a 29-setting module
 * readable.
 *
 * DECISION: groups come from a name-prefix table rather than the schema. The
 * Pydantic models already name settings by feature (`anti_flood_*`, `captcha_*`),
 * so the prefix is the grouping the author intended — recording it here costs one
 * table and saves adding UI metadata to every model field.
 */
import React from "react";
import { Row, Toggle } from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import type { Field } from "./schema";

/** Longest match wins, so `stop_word` beats nothing and `filter` covers both. */
const GROUP_PREFIXES: readonly string[] = [
  "warn",
  "stop_word",
  "filter",
  "anti_flood",
  "captcha",
  "greeting",
  "autoban",
  "anti_raid",
  "forced_subscription",
  "reputation",
  "levels",
  "points",
  "track",
  "report",
  "daily_report",
  "weekly_report",
];

/** Prefixes that name the same feature, folded onto one group. */
const GROUP_ALIASES: Record<string, string> = {
  points: "levels",
  daily_report: "report",
  weekly_report: "report",
};

export function groupOf(field: Field): string {
  const head = field.path.split(".")[0] ?? "";
  const matched = GROUP_PREFIXES.filter((prefix) => head.startsWith(prefix)).sort(
    (a, b) => b.length - a.length,
  )[0];
  if (matched === undefined) {
    return "general";
  }
  return GROUP_ALIASES[matched] ?? matched;
}

/**
 * Bucket a module's fields, in schema order.
 *
 * A prefix that matched only once is not a group — `crossban.autoban_on_join`
 * shares a prefix with the entry module's five-field new-account screen but is a
 * single switch here, and giving it that screen's heading would be a lie. Those
 * fall back to "general".
 */
export function groupFields(fields: readonly Field[]): [string, Field[]][] {
  const counts = new Map<string, number>();
  for (const field of fields) {
    const group = groupOf(field);
    counts.set(group, (counts.get(group) ?? 0) + 1);
  }
  const buckets = new Map<string, Field[]>();
  for (const field of fields) {
    const named = groupOf(field);
    const group = (counts.get(named) ?? 0) > 1 ? named : "general";
    const bucket = buckets.get(group);
    if (bucket === undefined) {
      buckets.set(group, [field]);
    } else {
      bucket.push(field);
    }
  }
  return [...buckets.entries()];
}

/** `filters.links` → `setting-filters-links`, matching the .ftl catalogue. */
function labelKey(field: Field): string {
  return `setting-${field.path.replace(/[._]/g, "-")}`;
}

/** Enum members are kebab-cased the same way: `delete_warn` → `option-delete-warn`. */
export function optionKey(value: string): string {
  return `option-${value.replace(/_/g, "-")}`;
}

/** Group headings live under one prefix too: `anti_flood` → `settings-group-anti-flood`. */
export function groupKey(group: string): string {
  return `settings-group-${group.replace(/_/g, "-")}`;
}

export interface FieldProps {
  field: Field;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}

function NumberInput({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const current = typeof value === "number" ? String(value) : "";
  return (
    <input
      type="number"
      inputMode={field.kind === "integer" ? "numeric" : "decimal"}
      step={field.kind === "integer" ? 1 : 0.05}
      min={field.min}
      max={field.max}
      value={current}
      disabled={disabled}
      className="w-24 bg-transparent text-right text-[15px] text-link outline-none"
      onChange={(event) => {
        const raw = event.target.value;
        if (raw === "") {
          // An empty box is "unset" for a nullable field and "unchanged" otherwise.
          onChange(field.nullable ? null : value);
          return;
        }
        const parsed = field.kind === "integer" ? parseInt(raw, 10) : parseFloat(raw);
        onChange(Number.isNaN(parsed) ? value : parsed);
      }}
    />
  );
}

function StringList({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const items = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div className="px-4 py-3">
      <div className="text-[15px]">{t(labelKey(field))}</div>
      <textarea
        // DECISION: one entry per line rather than a chip editor. Stop-word lists
        // arrive as a paste from another bot's export, and a line-per-entry box
        // accepts that paste as-is.
        className="tg-input mt-2 h-28 w-full resize-y font-mono text-[13px]"
        value={items.join("\n")}
        disabled={disabled}
        spellCheck={false}
        placeholder={t("field-item-placeholder")}
        onChange={(event) =>
          onChange(
            event.target.value
              .split("\n")
              .map((line) => line.trim())
              .filter((line) => line !== ""),
          )
        }
      />
    </div>
  );
}

export function FieldInput(props: FieldProps): React.JSX.Element {
  const { field, value, onChange, disabled } = props;
  const t = useT();
  const label = t(labelKey(field));

  switch (field.kind) {
    case "boolean":
      return (
        <Row
          title={label}
          right={
            <Toggle
              checked={value === true}
              disabled={disabled}
              onChange={(next) => onChange(next)}
            />
          }
        />
      );
    case "enum":
      return (
        <Row
          title={label}
          right={
            <select
              className="max-w-[55vw] bg-transparent text-right text-[15px] text-link outline-none"
              value={typeof value === "string" ? value : ""}
              disabled={disabled}
              onChange={(event) => onChange(event.target.value)}
            >
              {(field.options ?? []).map((option) => (
                <option key={option} value={option}>
                  {t(optionKey(option))}
                </option>
              ))}
            </select>
          }
        />
      );
    case "integer":
    case "number":
      return <Row title={label} right={<NumberInput {...props} />} />;
    case "string":
      return (
        <Row
          title={label}
          right={
            <input
              type="text"
              className="w-40 bg-transparent text-right text-[15px] text-link outline-none"
              value={typeof value === "string" ? value : ""}
              maxLength={field.maxLength}
              disabled={disabled}
              placeholder={t("field-unset")}
              onChange={(event) => onChange(event.target.value)}
            />
          }
        />
      );
    case "text":
      return (
        <div className="px-4 py-3">
          <div className="text-[15px]">{label}</div>
          <textarea
            className="tg-input mt-2 h-32 w-full resize-y"
            value={typeof value === "string" ? value : ""}
            maxLength={field.maxLength}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          />
        </div>
      );
    case "string-list":
      return <StringList {...props} />;
    case "nested":
      // Nested objects are flattened into the parent's group by the form, so a
      // bare nested field never reaches here.
      return <Row title={label} />;
  }
}

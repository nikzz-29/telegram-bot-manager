/**
 * One input per field kind, plus the grouping that keeps a 29-setting module
 * readable.
 *
 * DECISION: groups come from a name-prefix table rather than the schema. The
 * Pydantic models already name settings by feature (`anti_flood_*`, `captcha_*`),
 * so the prefix is the grouping the author intended — recording it here costs one
 * table and saves adding UI metadata to every model field.
 */
import React, { useState } from "react";
import { Icon, Row, Toggle } from "../components/ui";
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

/**
 * The unit a numeric field is counted in, taken from the last word of its name.
 *
 * DECISION: the unit is drawn beside the input instead of being spelled into the
 * label. Every one of these used to end in a dangling clause — "Срок наказания,
 * часов" — which is how a spreadsheet column is titled, not how a settings row
 * reads, and it left the number itself unlabelled: a bare `24` in the corner of
 * the row with the word that gives it meaning stranded at the far left.
 *
 * The Pydantic fields already carry the unit as their name's last token, so this
 * needs no per-field table. Fields whose last token names no unit (`warn_limit`,
 * `anti_raid_joins`, `report_hour_utc`) fall through and get nothing, which is
 * right — their labels say what is being counted.
 */
const UNITS: Readonly<Record<string, string>> = {
  seconds: "field-seconds",
  minutes: "field-minutes",
  hours: "field-hours",
  days: "field-days",
  // `min_text_length` is a count of characters; it is the one field whose unit
  // its name states as a dimension rather than as the unit itself.
  length: "field-characters",
};

function unitKey(field: Field): string | undefined {
  return UNITS[field.path.split(/[._]/).pop() ?? ""];
}

/**
 * Whether a value the user typed falls outside the schema's own bounds.
 *
 * Exported because the Save button is the thing that has to care: the field can
 * say what is wrong, but only the screen holding the draft can decline to send
 * it. Every numeric setting ships `ge`/`le` from its Pydantic field, so the API
 * would reject this anyway — with a 422 the user has to decode, after a round
 * trip, instead of a sentence under the row that caused it.
 */
export function outOfRange(field: Field, value: unknown): boolean {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return false;
  }
  return (
    (field.min !== undefined && value < field.min) ||
    (field.max !== undefined && value > field.max)
  );
}

/**
 * An editable value on a settings row.
 *
 * DECISION: seated on the ground colour rather than left transparent. A bare
 * value flush against the card is indistinguishable from one the row is merely
 * stating — the whole form read as a list of facts, and nothing said which of
 * them could be typed into. This is the same treatment the scheduled-post editor
 * gives its time field.
 */
const VALUE_INPUT =
  "rounded-control bg-ground px-2.5 py-1.5 text-right text-row text-link outline-none disabled:opacity-50";

export interface FieldProps {
  field: Field;
  value: unknown;
  onChange: (value: unknown) => void;
  disabled: boolean;
}

function NumberInput({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const current = typeof value === "number" ? String(value) : "";
  const unit = unitKey(field);
  return (
    <>
      <input
        type="number"
        inputMode={field.kind === "integer" ? "numeric" : "decimal"}
        step={field.kind === "integer" ? 1 : 0.05}
        min={field.min}
        max={field.max}
        value={current}
        disabled={disabled}
        className={`w-20 ${VALUE_INPUT}`}
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
      {unit !== undefined && <span className="text-label text-hint">{t(unit)}</span>}
    </>
  );
}

/**
 * An enum, as a row that opens its options underneath itself.
 *
 * DECISION: not a native `<select>`. It is the one control on these screens that
 * could not be themed — it renders in the OS's own font and chrome, so a form of
 * Telegram-styled rows had a piece of Android or Safari sitting in the middle of
 * it. The two hand-written editors already replaced theirs for exactly this
 * reason; the generated form was the last place it survived.
 *
 * DECISION: it discloses in place rather than listing every option inline the way
 * those two editors do. They pick between three modes once; a module here can
 * carry several enums of five options each, and spelling them all out turns a
 * scannable form into a wall of radio rows. Collapsed, the row still states its
 * current value, which is what the reader came for.
 */
function EnumInput({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const [open, setOpen] = useState(false);
  const options = field.options ?? [];
  const current = typeof value === "string" ? value : "";

  return (
    <>
      <Row
        title={t(labelKey(field))}
        onClick={disabled ? undefined : () => setOpen(!open)}
        right={
          <>
            <span className="text-row text-link">
              {current === "" ? t("field-unset") : t(optionKey(current))}
            </span>
            {/* Hand-drawn rather than `Row`'s own chevron, because this one
                turns: the row does not go anywhere, it opens, and a chevron that
                stayed pointing right would promise a screen. */}
            <Icon
              name="chevron"
              size={18}
              className={`text-hint opacity-60 transition-transform duration-[--panel-motion] ease-panel ${
                open ? "rotate-90" : ""
              }`}
            />
          </>
        }
      />
      {open && (
        /* Recessed onto the ground, so the options read as belonging to the row
           above them rather than as further settings of their own. */
        <div className="bg-ground">
          {options.map((option) => (
            <Row
              key={option}
              title={t(optionKey(option))}
              onClick={() => {
                onChange(option);
                setOpen(false);
              }}
              // Always rendered, merely hidden when unselected: it holds the
              // column steady as the choice moves.
              right={
                <Icon
                  name="check"
                  size={18}
                  className={option === current ? "text-accent" : "invisible"}
                />
              }
            />
          ))}
        </div>
      )}
    </>
  );
}

function StringList({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const items = Array.isArray(value) ? (value as string[]) : [];
  return (
    <div className="px-4 py-3">
      <div className="text-row">{t(labelKey(field))}</div>
      <textarea
        // DECISION: one entry per line rather than a chip editor. Stop-word lists
        // arrive as a paste from another bot's export, and a line-per-entry box
        // accepts that paste as-is.
        className="tg-input mt-2 h-28 w-full resize-y font-mono text-label"
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
      return <EnumInput {...props} />;
    case "integer":
    case "number":
      return (
        <Row
          title={label}
          // The bound is stated only once it is broken. Printing "от 1 до 20"
          // under every numeric row would bury the labels in fine print to
          // forestall a mistake almost nobody makes.
          subtitle={
            outOfRange(field, value) ? (
              <span className="text-destructive">
                {t("field-invalid-number", { min: field.min ?? 0, max: field.max ?? 0 })}
              </span>
            ) : undefined
          }
          right={<NumberInput {...props} />}
        />
      );
    case "string":
      return (
        <Row
          title={label}
          right={
            <input
              type="text"
              className={`w-40 ${VALUE_INPUT}`}
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
          <div className="text-row">{label}</div>
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

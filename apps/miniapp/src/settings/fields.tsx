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
import { Icon, PickerRow, Row, Toggle, VALUE_INPUT } from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { haptic } from "../telegram/sdk";
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
  // `level` as well as `levels`, so `level_titles` joins the levels group instead
  // of falling back to "general" on a missing plural. The alias below folds them.
  "level",
  "levels",
  "points",
  "track",
  "report",
  "daily_report",
  "weekly_report",
  // The two AI maps. Their rows share the same three labels in both, so each
  // map needs a heading of its own to say which is the confidence and which is
  // the response. `thresholds` and `actions` are also full property names, and
  // the rows beneath them are its keys, so the head of the path is the map.
  "thresholds",
  "actions",
];

/** Prefixes that name the same feature, folded onto one group. */
const GROUP_ALIASES: Record<string, string> = {
  level: "levels",
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

/**
 * The label for one part of a compound field: `level_titles` + `key` →
 * `setting-level-titles-key`.
 *
 * The parts are not properties of the config — an entry field's path is relative
 * to its entry, and a map's `key`/`value` are halves of a pair — so they hang off
 * the owning field's key instead of having one derived from a path of their own.
 */
function partKey(field: Field, part: string): string {
  return `${labelKey(field)}-${part.replace(/[._]/g, "-")}`;
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
 * Whether a value is present and does not match the pattern its schema names.
 *
 * Absent counts as fine here; `required` is what decides whether absent is
 * allowed, and running both checks on one empty box would mark it twice.
 */
function patternViolated(field: Field, value: unknown): boolean {
  if (field.pattern === undefined || typeof value !== "string" || value === "") {
    return false;
  }
  return !new RegExp(field.pattern).test(value);
}

/**
 * Whether a field's value is one the API would refuse — the whole check, of which
 * `outOfRange` is the numeric part.
 *
 * A repeating group is the reason this exists: an entry whose required field is
 * blank is not a partially-filled row the server will tidy up, it is a 422, and
 * an inline button with a URL Telegram will not accept costs the greeting it was
 * attached to rather than just itself.
 *
 * `string-map` needs nothing: a key that fails its pattern is never committed, so
 * an invalid one cannot be in the draft, and an empty title reads as unset.
 */
export function fieldInvalid(field: Field, value: unknown): boolean {
  if (field.kind === "object-list") {
    const entries = Array.isArray(value) ? value : [];
    return entries.some((entry) => {
      const record = typeof entry === "object" && entry !== null ? entry : {};
      return (field.itemFields ?? []).some((item) => {
        const inner = (record as Record<string, unknown>)[item.path];
        const blank = item.required === true && (inner === undefined || inner === "");
        return blank || patternViolated(item, inner);
      });
    });
  }
  return patternViolated(field, value) || outOfRange(field, value);
}

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
 * The disclosure itself is `PickerRow`; this only turns a `Field` into the
 * options it takes. The general settings make the same choice over locales, and
 * two copies of a rotating chevron and a checkmark column is one too many.
 */
function EnumInput({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const current = typeof value === "string" ? value : "";

  return (
    <PickerRow
      title={t(labelKey(field))}
      value={current}
      disabled={disabled}
      unsetLabel={t("field-unset")}
      options={(field.options ?? []).map((option) => ({
        value: option,
        label: t(optionKey(option)),
      }))}
      onPick={(option) => onChange(option)}
    />
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

/** A caption above an input, for the fields that are too wide to label from the left. */
function InputLabel({ children }: { children: React.ReactNode }): React.JSX.Element {
  return (
    <span className="text-caption font-medium uppercase tracking-wide text-hint">{children}</span>
  );
}

/**
 * An icon-only control, sized to the 44px Telegram expects a finger to hit.
 *
 * Negative margins keep that box from spacing out the row it sits in: the target
 * is bigger than the glyph, which is the point, but it should not look it.
 */
function IconButton({
  name,
  label,
  onClick,
  disabled,
  className = "",
}: {
  name: "plus" | "trash";
  label: string;
  onClick: () => void;
  disabled: boolean;
  className?: string;
}): React.JSX.Element {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={() => {
        haptic();
        onClick();
      }}
      className={`-my-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-control transition-colors duration-[--panel-motion] disabled:opacity-50 ${className}`}
    >
      <Icon name={name} size={18} />
    </button>
  );
}

/**
 * A `list[Model]` of flat entries, as a repeating group.
 *
 * DECISION: the entries are drawn stacked and full-width rather than as rows with
 * the value on the right. The one field of this shape holds a URL up to 2,048
 * characters; in the `w-40 text-right` box the scalar rows use, that shows about
 * a fifth of one, scrolled to the wrong end.
 */
function ObjectListInput({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const entries: Record<string, unknown>[] = Array.isArray(value)
    ? value.map((entry) => (typeof entry === "object" && entry !== null ? { ...entry } : {}))
    : [];
  const items = field.itemFields ?? [];

  return (
    <div className="px-4 py-3">
      <div className="text-row">{t(labelKey(field))}</div>
      {entries.length === 0 && <p className="mt-1 text-label text-hint">{t("field-list-empty")}</p>}

      {entries.map((entry, index) => (
        <div
          // Keyed by position because an entry carries no id of its own. Safe only
          // because nothing about an entry lives in local state — every input
          // reads from the draft, so a node reused after a removal re-renders
          // with the right contents rather than the departed row's.
          key={index}
          // A hairline between entries, not a box around each: this is one
          // setting repeated, and a card per entry inside a card is a form builder.
          className={index === 0 ? "mt-2" : "mt-3 border-t border-separator pt-3"}
        >
          {items.map((item, position) => {
            const raw = entry[item.path];
            const bad = patternViolated(item, raw);
            return (
              <div key={item.path} className={position === 0 ? "" : "mt-2"}>
                <div className="flex items-center justify-between gap-2">
                  <InputLabel>{t(partKey(field, item.path))}</InputLabel>
                  {/* Removal rides the first field's caption line: an entry has no
                      title bar of its own to hang it off. */}
                  {position === 0 && (
                    <IconButton
                      name="trash"
                      label={t("field-remove")}
                      disabled={disabled}
                      className="text-hint active:text-destructive"
                      onClick={() => onChange(entries.filter((_, other) => other !== index))}
                    />
                  )}
                </div>
                <input
                  type="text"
                  className={`tg-input mt-1 ${bad ? "border-destructive" : ""}`}
                  value={typeof raw === "string" ? raw : ""}
                  maxLength={item.maxLength}
                  disabled={disabled}
                  // Neither half of a button is prose: one is a short label, the
                  // other a URL. And a value a regex has to accept must not be
                  // helped along — iOS capitalises the first letter of a text
                  // field by default, which on its own turns `https://` into a
                  // URL Telegram rejects.
                  spellCheck={false}
                  autoCapitalize={item.pattern === undefined ? undefined : "none"}
                  autoCorrect={item.pattern === undefined ? undefined : "off"}
                  onChange={(event) =>
                    onChange(
                      entries.map((old, other) =>
                        other === index ? { ...old, [item.path]: event.target.value } : old,
                      ),
                    )
                  }
                />
                {item.pattern !== undefined && (
                  <p className={`mt-1 text-caption ${bad ? "text-destructive" : "text-hint"}`}>
                    {t(`${partKey(field, item.path)}-hint`)}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {/* Said here rather than left to the greyed-out Save button, which can show
          that something is wrong but not which entry, or what about it. */}
      {fieldInvalid(field, value) && (
        <p className="mt-2 text-caption text-destructive">{t("field-list-incomplete")}</p>
      )}

      <div className="mt-1 flex items-center gap-1 text-link">
        <IconButton
          name="plus"
          label={t("field-add")}
          disabled={disabled}
          onClick={() =>
            onChange([...entries, Object.fromEntries(items.map((item) => [item.path, ""]))])
          }
        />
        <span className="text-row">{t("field-add")}</span>
      </div>
    </div>
  );
}

/**
 * An open-ended `dict[str, str]`, as a list of key/value pairs.
 *
 * The one field of this shape is the level titles, whose keys are level numbers
 * the admin invents — so this is the only generated editor where the *key* is
 * typed, and the only one that has to defend against a key the config cannot hold.
 */
function StringMapInput({ field, value, onChange, disabled }: FieldProps): React.JSX.Element {
  const t = useT();
  const map =
    typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {};
  /*
   * Insertion order is neither the display order nor a thing to keep track of: an
   * object enumerates its integer-like keys in ascending numeric order, so a map
   * keyed by level number sorts itself. That is what lets the saved object be the
   * only state here — there is no parallel ordered list to hold in step with it.
   */
  const pairs = Object.entries(map);
  // Fails closed. `describe` only produces this kind with a key pattern, but if a
  // broken one ever arrived, `^$` leaves the keys uneditable rather than
  // unconstrained: a key that cannot be changed beats a key that cannot be saved.
  const keyOk = React.useMemo(() => {
    try {
      return new RegExp(field.keyPattern ?? "^$");
    } catch {
      return /^$/;
    }
  }, [field.keyPattern]);

  /*
   * The key being typed, held outside the map until it is committed.
   *
   * A rename cannot go through per keystroke: "2" → "30" passes through "" and
   * "3", the first of which is no key at all and the second of which may already
   * be taken. So the text lives here and lands on blur — which also keeps the row
   * from re-sorting itself out from under the finger still typing in it. Tracked
   * against the committed key rather than the row index, because committing sorts.
   */
  const [typing, setTyping] = React.useState<{ key: string; text: string } | null>(null);

  const commit = (from: string): void => {
    const text = typing?.key === from ? typing.text : from;
    setTyping(null);
    // Anything the map cannot hold reverts: the input falls back to the committed
    // key, which reads as a rename that visibly did not take.
    if (text === from || !keyOk.test(text) || pairs.some(([key]) => key === text)) {
      return;
    }
    onChange(Object.fromEntries(pairs.map(([key, title]) => [key === from ? text : key, title])));
  };

  // One past the highest key, which therefore cannot collide with an existing one.
  // Disabled rather than clamped when that number is not itself a valid key —
  // reachable only from a hand-edited config naming an absurd level.
  const nextKey = String(pairs.reduce((top, [key]) => Math.max(top, Number(key)), 0) + 1);

  return (
    <div className="px-4 py-3">
      <div className="text-row">{t(labelKey(field))}</div>
      {pairs.length === 0 && <p className="mt-1 text-label text-hint">{t("field-list-empty")}</p>}

      {pairs.map(([key, title]) => {
        const shown = typing?.key === key ? typing.text : key;
        return (
          <div key={key} className="mt-2 flex items-center gap-2">
            {/* The placeholder is the visible label and `aria-label` the read one:
                a pair per line has no room for a caption above each half. */}
            <input
              type="text"
              inputMode="numeric"
              aria-label={t(partKey(field, "key"))}
              placeholder={t(partKey(field, "key"))}
              className={`tg-input w-16 shrink-0 text-center ${
                keyOk.test(shown) ? "" : "border-destructive"
              }`}
              value={shown}
              disabled={disabled}
              onChange={(event) => setTyping({ key, text: event.target.value })}
              onBlur={() => commit(key)}
            />
            <input
              type="text"
              aria-label={t(partKey(field, "value"))}
              placeholder={t(partKey(field, "value"))}
              className="tg-input min-w-0 flex-1"
              value={typeof title === "string" ? title : ""}
              maxLength={field.maxLength}
              disabled={disabled}
              onChange={(event) => onChange({ ...map, [key]: event.target.value })}
            />
            <IconButton
              name="trash"
              label={t("field-remove")}
              disabled={disabled}
              className="text-hint active:text-destructive"
              onClick={() => onChange(Object.fromEntries(pairs.filter(([other]) => other !== key)))}
            />
          </div>
        );
      })}

      {/* Stated up front, unlike a numeric bound: the keys are invented rather
          than adjusted, so there is nothing to infer them from, and a rename the
          map refuses is silent by design. */}
      {field.keyPattern !== undefined && (
        <p className="mt-2 text-caption text-hint">{t(`${partKey(field, "key")}-hint`)}</p>
      )}

      <div className="mt-1 flex items-center gap-1 text-link">
        <IconButton
          name="plus"
          label={t("field-add")}
          disabled={disabled || !keyOk.test(nextKey)}
          onClick={() => onChange({ ...map, [nextKey]: "" })}
        />
        <span className="text-row">{t("field-add")}</span>
      </div>
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
              label={label}
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
    case "object-list":
      return <ObjectListInput {...props} />;
    case "string-map":
      return <StringMapInput {...props} />;
    case "nested":
      // Nested objects are flattened into the parent's group by the form, so a
      // bare nested field never reaches here.
      return <Row title={label} />;
  }
}

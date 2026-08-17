/**
 * Turn a module's JSON Schema into a list of fields the panel can draw.
 *
 * DECISION: settings screens are generated from the schema `/api/meta` ships
 * rather than hand-written per module. There are seven modules and roughly sixty
 * settings between them; hand-written forms would drift from the Pydantic models
 * the first time someone adds a field, and the drift is silent — the setting
 * simply never appears. Generating means a new field shows up by existing.
 *
 * DECISION: what the generator cannot express, it declines to render rather than
 * guessing. A wrong widget that writes a wrong shape is worse than an absent
 * one — but "declines to render" is silent, so every shape that falls in that
 * hole is a setting the panel cannot reach at all, and the hole is kept as small
 * as the schema allows. Three shapes used to sit in it and no longer do:
 *
 *   - a map with a *closed* key set (`dict[AiVerdictLabel, float]`) names its
 *     keys in `propertyNames.enum` and its value type in `additionalProperties`,
 *     which is every ingredient needed to draw one row per member. That omission
 *     hid the two settings deciding what AI moderation actually does — the
 *     confidence each verdict needs, and what happens once it clears;
 *   - a list of objects (`list[InlineButton]`) whose fields are all scalars is a
 *     repeating group. That one hid the greeting's inline buttons;
 *   - an open-ended `dict[str, str]` has no row per key, because the keys are the
 *     admin's to invent — but `propertyNames.pattern` says what a key may look
 *     like, which is enough to edit the pairs. That one hid the level titles.
 *
 * What is left in the hole: a genuine union, a list of anything that is not a
 * flat object, and a map whose keys are constrained by nothing at all.
 */

export type FieldKind =
  | "boolean"
  | "integer"
  | "number"
  | "string"
  | "text"
  | "enum"
  | "string-list"
  | "object-list"
  | "string-map"
  | "nested";

export interface Field {
  /** Dotted path into the config object, e.g. `filters.links`. */
  path: string;
  kind: FieldKind;
  /** Fluent key for the label, falling back to the humanized property name. */
  label: string;
  min?: number;
  max?: number;
  maxLength?: number;
  options?: readonly string[];
  /** Fields of a nested object, in order. */
  children?: Field[];
  /**
   * For `object-list`: the fields of one entry, with paths relative to it.
   *
   * Separate from `children` because these describe the *shape* repeated per
   * entry rather than fields at fixed paths — the form flattens `children` into
   * its parent's group, which is exactly the wrong thing to do to these.
   */
  itemFields?: Field[];
  /** The schema said this must be present: an empty value cannot be saved. */
  required?: boolean;
  /** A regex the value must match, when the schema names one. */
  pattern?: string;
  /** For `string-map`: the regex its *keys* must match. */
  keyPattern?: string;
  nullable: boolean;
}

interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: string[];
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  pattern?: string;
  title?: string;
  additionalProperties?: boolean | JsonSchema;
  /** For a `dict[K, V]`: the schema its *keys* satisfy. */
  propertyNames?: JsonSchema;
  /** Server-side compatibility fields can stay accepted without appearing. */
  "x-hidden"?: boolean;
}

/** Long free text gets a textarea; these are the fields that deserve one. */
const MULTILINE = new Set(["greeting_text", "response", "content", "text"]);

/**
 * …but only where there is room for a paragraph.
 *
 * `InlineButton.text` is a button label capped at 64 characters and shares its
 * name with a post body: matching on the name alone gave it a four-line textarea
 * for a value that is never more than a few words. The cap is the honest signal —
 * a field that can hold 4,000 characters was meant to.
 */
const PARAGRAPH_LENGTH = 256;

/** The kinds a repeating group can draw for one of its entries. */
const ENTRY_KINDS = new Set<FieldKind>(["string", "integer", "number"]);

function deref(schema: JsonSchema, defs: Record<string, JsonSchema>): JsonSchema {
  if (schema.$ref === undefined) {
    return schema;
  }
  const name = schema.$ref.split("/").pop() ?? "";
  return defs[name] ?? {};
}

/**
 * Collapse `anyOf: [T, null]` — Pydantic's `T | None` — to `T` plus a nullable flag.
 *
 * Any other `anyOf` is a genuine union the generator has no widget for.
 */
function unwrapNullable(
  schema: JsonSchema,
  defs: Record<string, JsonSchema>,
): { schema: JsonSchema; nullable: boolean } | null {
  if (schema.anyOf === undefined) {
    return { schema, nullable: false };
  }
  const branches = schema.anyOf.filter((branch) => branch.type !== "null");
  if (branches.length !== 1 || branches[0] === undefined) {
    return null;
  }
  return { schema: deref(branches[0], defs), nullable: schema.anyOf.length > branches.length };
}

function describe(
  name: string,
  raw: JsonSchema,
  defs: Record<string, JsonSchema>,
  prefix: string,
): Field | null {
  if (raw["x-hidden"] === true) {
    return null;
  }
  const unwrapped = unwrapNullable(raw, defs);
  if (unwrapped === null) {
    return null;
  }
  const { nullable } = unwrapped;
  const schema = deref(unwrapped.schema, defs);
  const path = prefix === "" ? name : `${prefix}.${name}`;
  const base = { path, label: name, nullable };

  if (schema.enum !== undefined) {
    return { ...base, kind: "enum", options: schema.enum };
  }
  if (schema.type === "boolean") {
    return { ...base, kind: "boolean" };
  }
  if (schema.type === "integer" || schema.type === "number") {
    return {
      ...base,
      kind: schema.type === "integer" ? "integer" : "number",
      min: schema.minimum,
      max: schema.maximum,
    };
  }
  if (schema.type === "string") {
    const multiline = MULTILINE.has(name) && (schema.maxLength ?? Infinity) >= PARAGRAPH_LENGTH;
    return {
      ...base,
      kind: multiline ? "text" : "string",
      maxLength: schema.maxLength,
      pattern: schema.pattern,
    };
  }
  if (schema.type === "array") {
    const items = deref(schema.items ?? {}, defs);
    if (items.type === "string") {
      return { ...base, kind: "string-list" };
    }
    /*
     * A list of flat objects, as a repeating group.
     *
     * Every entry field has to be a kind the group can draw inline: a nested
     * object or a list inside a repeating entry needs a screen of its own, and
     * drawing it as a card-in-a-card is how a settings form turns into a form
     * builder. Anything else declines, per the note at the top.
     */
    if (items.type === "object" && items.properties !== undefined) {
      const itemFields = fieldsOf(items, defs, "");
      const drawable =
        itemFields.length > 0 && itemFields.every((item) => ENTRY_KINDS.has(item.kind));
      return drawable ? { ...base, kind: "object-list", itemFields } : null;
    }
    return null;
  }
  if (schema.type === "object" && schema.properties !== undefined) {
    const children = fieldsOf(schema, defs, path);
    return children.length > 0 ? { ...base, kind: "nested", children } : null;
  }
  if (schema.type === "object") {
    const keys = deref(schema.propertyNames ?? {}, defs);
    const rawValue = schema.additionalProperties;
    if (typeof rawValue !== "object" || rawValue === null) {
      return null;
    }
    const value = deref(rawValue, defs);
    /*
     * A map with a closed key set, expanded into one child per key.
     *
     * It is spelled as `nested` on purpose: the children carry real dotted paths
     * (`thresholds.toxic`), so `readPath`/`writePath` reach into the map with no
     * special case, and the form groups and renders them like any other subobject.
     * The value schema is shared by every key, so each child is described from it
     * once, under the key's own name.
     */
    if (keys.enum !== undefined) {
      const children = keys.enum
        .map((key) => describe(key, value, defs, path))
        .filter((child): child is Field => child !== null);
      return children.length > 0 ? { ...base, kind: "nested", children } : null;
    }
    /*
     * An open-ended `dict[str, str]`, as a list of pairs.
     *
     * There is no row per key here — the schema does not know the keys, the admin
     * invents them — so this is the one generated field whose *keys* are edited.
     * That needs `propertyNames.pattern` to say what a key may be: without it the
     * editor would take any string, and for the one field of this shape (the level
     * titles, looked up as `str(level)`) most strings are a title nothing reads.
     */
    if (value.type === "string" && keys.pattern !== undefined) {
      return {
        ...base,
        kind: "string-map",
        keyPattern: keys.pattern,
        maxLength: value.maxLength,
      };
    }
    return null;
  }
  // Anything left is a shape with no widget — see the note at the top.
  return null;
}

export function fieldsOf(
  schema: JsonSchema,
  defs: Record<string, JsonSchema> = schema.$defs ?? {},
  prefix = "",
): Field[] {
  // Required-ness lives on the parent, not the property, so it is stamped here.
  // Only a repeating group uses it: every module setting has a default, which is
  // what makes a chat row with an empty config valid.
  const required = new Set(schema.required ?? []);
  const fields: Field[] = [];
  for (const [name, property] of Object.entries(schema.properties ?? {})) {
    const field = describe(name, property, defs, prefix);
    if (field !== null) {
      fields.push(required.has(name) ? { ...field, required: true } : field);
    }
  }
  return fields;
}

/** Read a dotted path out of a config object. */
export function readPath(config: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => {
    return typeof value === "object" && value !== null
      ? (value as Record<string, unknown>)[key]
      : undefined;
  }, config);
}

/**
 * Write a dotted path, copying every object along the way.
 *
 * The result is a fresh tree so React sees the change; mutating in place would
 * leave the form rendering its previous state.
 */
export function writePath(
  config: Record<string, unknown>,
  path: string,
  value: unknown,
): Record<string, unknown> {
  const [head, ...rest] = path.split(".");
  if (head === undefined) {
    return config;
  }
  if (rest.length === 0) {
    return { ...config, [head]: value };
  }
  const nested = config[head];
  const branch = typeof nested === "object" && nested !== null ? nested : {};
  return {
    ...config,
    [head]: writePath(branch as Record<string, unknown>, rest.join("."), value),
  };
}

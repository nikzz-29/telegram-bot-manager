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
 * one. Two things fall in that hole today and are genuinely unreachable in the
 * panel: the greeting's inline buttons (`list[InlineButton]`) and the level
 * titles (`dict[str, str]`, open-ended keys). Both need a purpose-built editor
 * that does not exist yet.
 *
 * A map whose keys are a *closed* enum is not in that hole, though it used to be
 * treated as one: `dict[AiVerdictLabel, float]` names its key set in
 * `propertyNames.enum` and its value type in `additionalProperties`, which is
 * every ingredient needed to draw one row per member. That omission hid the two
 * settings that decide what AI moderation actually does — the confidence each
 * verdict needs, and what happens once it clears — leaving a screen that could
 * turn the feature on but never say what it should do about anything.
 */

export type FieldKind =
  | "boolean"
  | "integer"
  | "number"
  | "string"
  | "text"
  | "enum"
  | "string-list"
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
  nullable: boolean;
}

interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  enum?: string[];
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  title?: string;
  additionalProperties?: boolean | JsonSchema;
  /** For a `dict[K, V]`: the schema its *keys* satisfy. */
  propertyNames?: JsonSchema;
}

/** Long free text gets a textarea; these are the fields that deserve one. */
const MULTILINE = new Set(["greeting_text", "response", "content", "text"]);

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
    return {
      ...base,
      kind: MULTILINE.has(name) ? "text" : "string",
      maxLength: schema.maxLength,
    };
  }
  if (schema.type === "array") {
    const items = deref(schema.items ?? {}, defs);
    // Only a list of plain strings: a list of objects needs its own editor.
    return items.type === "string" ? { ...base, kind: "string-list" } : null;
  }
  if (schema.type === "object" && schema.properties !== undefined) {
    const children = fieldsOf(schema, defs, path);
    return children.length > 0 ? { ...base, kind: "nested", children } : null;
  }
  /*
   * A map with a closed key set, expanded into one child per key.
   *
   * It is spelled as `nested` on purpose: the children carry real dotted paths
   * (`thresholds.toxic`), so `readPath`/`writePath` reach into the map with no
   * special case, and the form groups and renders them like any other subobject.
   * The value schema is shared by every key, so each child is described from it
   * once, under the key's own name.
   */
  if (schema.type === "object") {
    const memberKeys = deref(schema.propertyNames ?? {}, defs).enum;
    const value = schema.additionalProperties;
    if (memberKeys === undefined || typeof value !== "object" || value === null) {
      return null;
    }
    const children = memberKeys
      .map((key) => describe(key, value, defs, path))
      .filter((child): child is Field => child !== null);
    return children.length > 0 ? { ...base, kind: "nested", children } : null;
  }
  // Anything left is a shape with no widget — see the note at the top.
  return null;
}

export function fieldsOf(
  schema: JsonSchema,
  defs: Record<string, JsonSchema> = schema.$defs ?? {},
  prefix = "",
): Field[] {
  const fields: Field[] = [];
  for (const [name, property] of Object.entries(schema.properties ?? {})) {
    const field = describe(name, property, defs, prefix);
    if (field !== null) {
      fields.push(field);
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

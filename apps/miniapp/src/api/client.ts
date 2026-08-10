/**
 * The one place the panel talks to the API.
 *
 * Every request goes through the openapi-fetch client, so paths, params and
 * response shapes are checked against `schema.ts` — which is generated from the
 * API's own OpenAPI document. A renamed field breaks `pnpm build`, not
 * production.
 *
 * DECISION: the session token lives in memory, not localStorage. A Mini App is
 * relaunched with fresh `initData` every time it opens, so persisting the token
 * buys nothing and would leave a bearer credential sitting in storage that any
 * injected script could read.
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type ChatSummary = Schemas["ChatSummary"];
export type ChatDetail = Schemas["ChatDetail"];
export type ModuleConfigResponse = Schemas["ModuleConfigResponse"];
export type MetaResponse = Schemas["MetaResponse"];
export type ModuleMeta = Schemas["ModuleMeta"];
export type PlanMeta = Schemas["PlanMeta"];
export type AuthUser = Schemas["AuthUser"];
export type Problem = Schemas["Problem"];
export type Plan = Schemas["Plan"];
export type TriggerEntry = Schemas["TriggerEntry"];
export type TriggerCreate = Schemas["TriggerCreate"];
export type TriggerUpdate = Schemas["TriggerUpdate"];
export type PostEntry = Schemas["PostEntry"];
export type PostCreate = Schemas["PostCreate"];
export type PostUpdate = Schemas["PostUpdate"];
export type StatsOverview = Schemas["StatsOverview"];
export type StatPoint = Schemas["StatPoint"];
export type TopUser = Schemas["TopUser"];
export type ReputationEntry = Schemas["ReputationEntry"];

/** Empty in dev (Vite proxies `/api`); the deployed panel points at the API host. */
const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

let sessionToken: string | null = null;
let onSessionLost: (() => void) | null = null;

export function setSessionToken(token: string | null): void {
  sessionToken = token;
}

/** Called when the API rejects our token, so the shell can re-authenticate. */
export function setSessionLostHandler(handler: (() => void) | null): void {
  onSessionLost = handler;
}

/**
 * A failed request, carrying the RFC7807 body the API returned.
 *
 * `title` is already localized by the API for this caller, so it is safe to
 * render; `code` is the stable discriminator to branch on.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: Problem | null;

  constructor(status: number, problem: Problem | null, fallback: string) {
    super(problem?.title || fallback);
    this.name = "ApiError";
    this.status = status;
    this.code = problem?.code ?? "unknown";
    this.problem = problem;
  }

  /** The plan a locked feature needs, when the API said 402. */
  get requiredPlan(): string | null {
    const value = this.problem?.context?.["required_plan"];
    return typeof value === "string" ? value : null;
  }

  get isFeatureLocked(): boolean {
    return this.status === 402;
  }

  get isSessionExpired(): boolean {
    return this.status === 401;
  }
}

const authMiddleware: Middleware = {
  async onRequest({ request }) {
    if (sessionToken) {
      request.headers.set("Authorization", `Bearer ${sessionToken}`);
    }
    request.headers.set("Accept-Language", currentLocale);
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 401 && sessionToken) {
      // The token outlived its TTL mid-session: drop it so the shell can trade
      // the launch `initData` for a new one instead of showing an error.
      sessionToken = null;
      onSessionLost?.();
    }
    return response;
  },
};

let currentLocale = "en";

export function setLocale(locale: string): void {
  currentLocale = locale;
}

export const client = createClient<paths>({ baseUrl: BASE_URL });
client.use(authMiddleware);

/**
 * Narrow an openapi-fetch result to its data, or throw a typed `ApiError`.
 *
 * `error` is `Problem` rather than `unknown` because every router declares its
 * failure statuses server-side; if that ever regresses, this signature stops
 * compiling instead of quietly widening.
 */
export function unwrap<T>(result: {
  data?: T;
  error?: Problem;
  response: Response;
}): T {
  if (result.error !== undefined || result.data === undefined) {
    throw new ApiError(
      result.response.status,
      result.error ?? null,
      result.response.statusText,
    );
  }
  return result.data;
}

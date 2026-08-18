# Account Site Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a secure, bilingual, responsive account dashboard with per-chat analytics, session-memory caching, persistent animated charts, restrained monochrome glass styling, and production CI coverage.

**Architecture:** The API will derive every account-visible chat from the mirrored administrator list and then fail closed through `AdminService.is_admin`, so stale mirror rows cannot leak data. The React site will be split into typed i18n, dashboard cache, chart geometry/motion, shell controls, and focused screens; authenticated data stays in memory and fetches use `no-store`. A persistent SVG chart will interpolate between cached datasets and expose accessible mouse, keyboard, and touch details without remounting.

**Tech Stack:** FastAPI, SQLAlchemy repository/UoW patterns, Pydantic, pytest, React 18, TypeScript, Vite, Vitest, Testing Library, CSS, Playwright, Docker Compose, Nginx.

---

## File Structure

- Create `apps/api/src/api/chat_scope.py`: live-verified account chat scope shared by account and chat-list endpoints.
- Modify `apps/api/src/api/routers/account.py`: consume verified scope, expose truthful scope counts, and mark responses private/no-store.
- Modify `apps/api/src/api/routers/chats.py`: filter list results through the same verified scope and add private/no-store headers.
- Modify `packages/shared/src/shared/schemas/api.py`: add dashboard scope counters.
- Modify `tests/test_account_api.py` and `tests/test_api.py`: prove stale, inactive, foreign, aggregate, and selected-chat access behavior.
- Modify generated `apps/miniapp/openapi.json` and `apps/miniapp/src/api/schema.ts`: keep the API client contract current.
- Create `apps/site/src/i18n/*`: typed RU/EN dictionaries, locale selection, persistence, and Intl formatting.
- Create `apps/site/src/hooks/useDashboardCache.ts`: per-user/per-chat/per-period memory cache, request dedupe, retries, and bounded prefetch.
- Create `apps/site/src/components/chart/*`: pure chart geometry, persistent motion renderer, and accessible tooltip.
- Create `apps/site/src/components/dashboard/*`: context selector, metric cards, period/metric controls, moderation and member-flow surfaces.
- Create `apps/site/src/screens/*`: overview, activity, chats, plans, profile, and login screens.
- Modify `apps/site/src/SiteApp.tsx`: authentication/session coordinator and responsive shell only.
- Modify `apps/site/src/api.ts` and `apps/site/src/types.ts`: no-store requests and complete typed API contract.
- Modify `apps/site/src/site.css` and `apps/site/index.html`: Onest typography, monochrome glass tokens, responsive navigation, motion, accessibility, and dynamic language metadata.
- Create `apps/site/src/**/*.test.ts(x)` and `apps/site/src/test/setup.ts`: unit and interaction coverage.
- Modify `apps/site/package.json`, `apps/site/pnpm-lock.yaml`, `apps/site/vite.config.ts`: test tooling and production source-map policy.
- Modify `.github/workflows/ci.yml`: install, test, typecheck, and build the standalone site.

### Task 1: Secure Account Chat Scope

- [ ] **Step 1: Write failing authorization tests**

Add tests that supply an `AdminService` fake with configurable live verdicts and assert that an inactive chat or stale former-admin row is absent from profile, dashboard, and `/api/chats`; selecting either returns `ChatNotFoundError`/HTTP 404. Assert an aggregate dashboard sends only live accessible chat IDs to statistics and moderation repositories.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `uv run pytest tests/test_account_api.py tests/test_api.py -q`

Expected: failures because account/profile/chat list currently trust `list_for_admin()` and router call signatures do not accept `AdminsDep`.

- [ ] **Step 3: Implement a shared verified scope**

Create `api.chat_scope.accessible_chats(principal, uow, admins)` using `asyncio.gather` over `admins.is_admin(chat.tg_chat_id, principal.tg_user_id)`, preserve repository order, and return only active chats with a positive live verdict. Inject `AdminsDep` into profile, dashboard, and chat-list endpoints. A requested internal `chat_id` must be selected only from this verified list and otherwise produce the existing indistinguishable 404.

- [ ] **Step 4: Expose truthful scope metadata and response privacy**

Add `scoped_chat_count` and `analytics_chat_count` to `UserDashboard`. Set authenticated account/chat responses to `Cache-Control: private, no-store` through a `Response` dependency or route response mutation, without affecting public metadata.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `uv run pytest tests/test_account_api.py tests/test_api.py -q`

Expected: all focused tests pass, including stale-access and inactive-chat cases.

- [ ] **Step 6: Regenerate the API contract**

Run: `uv run python scripts/export_openapi.py && cd apps/miniapp && pnpm run generate`

Expected: generated OpenAPI and TypeScript schema include both scope counters and no unrelated drift.

- [ ] **Step 7: Commit**

Commit message: `fix: verify account chat access live`

### Task 2: Add Site Test Harness and Typed Localization

- [ ] **Step 1: Install frontend test dependencies and scripts**

Add Vitest, jsdom, `@testing-library/react`, `@testing-library/jest-dom`, and `@testing-library/user-event`; add `test` and `test:watch` scripts and a Vite/Vitest setup file.

- [ ] **Step 2: Write failing localization tests**

Cover locale priority `persisted > Telegram profile > browser`, versioned persistence, RU/EN switching, `document.documentElement.lang`, translated login/navigation/loading/error/graph strings, and localized number/date formatting.

- [ ] **Step 3: Run locale tests and confirm RED**

Run: `cd apps/site && pnpm test --run src/i18n`

Expected: failures because the typed locale modules do not exist and the current UI is hard-coded in English.

- [ ] **Step 4: Implement typed i18n**

Create literal RU dictionary keys, derive the English dictionary type from the Russian shape, implement `LocaleProvider`, `useI18n`, locale normalization, versioned `localStorage` preference, and memoized `Intl.NumberFormat`/`Intl.DateTimeFormat` helpers. Do not persist analytics or auth data in local storage.

- [ ] **Step 5: Move all visible and accessible strings through dictionaries**

Translate screen headings, navigation, periods, metrics, plans, empty/loading/error states, form labels, button titles, aria labels, chart tooltip text, and account/profile descriptions. Update the page title and HTML language whenever locale changes.

- [ ] **Step 6: Run localization tests and confirm GREEN**

Run: `cd apps/site && pnpm test --run src/i18n`

Expected: all locale tests pass in both languages.

- [ ] **Step 7: Commit**

Commit message: `feat: add bilingual account site`

### Task 3: Build Session Dashboard Cache and Per-Chat Context

- [ ] **Step 1: Write failing cache tests**

Test cache keys `all:7` and `<chat-id>:7`, one fetch for concurrent identical reads, no fetch after a cache hit, four-period background prefetch with bounded concurrency, isolated values per chat, recoverable per-key errors, and complete cache disposal on logout/user change.

- [ ] **Step 2: Run cache tests and confirm RED**

Run: `cd apps/site && pnpm test --run src/hooks/useDashboardCache.test.tsx`

Expected: failures because period changes currently refetch the whole account payload and no session cache exists.

- [ ] **Step 3: Implement the cache hook**

Keep `Map<string, Dashboard>` and in-flight promises inside one authenticated `DashboardProvider`, key by `<chat-id-or-all>:<period>`, fetch the selected period immediately, then prefetch missing `1/7/30/90` periods with at most two active requests. Retain prior data while an uncached request loads and expose retry/error state per key.

- [ ] **Step 4: Write failing chat-context tests**

Test selecting `All chats` versus one internal `Chat.id`, passing `chat_id` to `fetchDashboard`, opening a chat row directly in Activity, resetting to all chats after a confirmed 404, and keeping the selector stable across Overview/Activity navigation.

- [ ] **Step 5: Implement per-chat navigation**

Add a global context selector in the top bar, selected-chat state in the authenticated shell, contextual labels and scope counts, chat-row actions that select the chat and navigate to Activity, and explicit states for unavailable analytics and disconnected chats.

- [ ] **Step 6: Make authenticated fetches non-cacheable**

Set `cache: "no-store"` in the API request helper, preserve caller options, clear both session token and dashboard memory on 401/logout, and update frontend types with `selected_chat_id`, `scoped_chat_count`, `analytics_chat_count`, and `top_users`.

- [ ] **Step 7: Run cache and navigation tests and confirm GREEN**

Run: `cd apps/site && pnpm test --run src/hooks src/screens`

Expected: all cache and per-chat tests pass without repeated account/profile/meta requests on period changes.

- [ ] **Step 8: Commit**

Commit message: `feat: add cached per-chat analytics`

### Task 4: Implement Persistent Morphing Chart

- [ ] **Step 1: Write failing pure geometry tests**

Cover empty/single/multi-point series, normalized resampling to a shared point count, interpolation at progress `0`, `0.5`, and `1`, stable x coordinates, finite y coordinates for all-zero data, and authoritative totals for peak metrics such as `active_users`.

- [ ] **Step 2: Run geometry tests and confirm RED**

Run: `cd apps/site && pnpm test --run src/components/chart/geometry.test.ts`

Expected: failures because resampling and interpolation helpers do not exist.

- [ ] **Step 3: Implement geometry and motion helpers**

Create pure functions for SVG coordinates, linear resampling on normalized time, easing, and frame interpolation. The renderer keeps previous and target geometry in refs, uses one `requestAnimationFrame` loop for 320-480 ms, cancels stale frames, and immediately applies targets under `prefers-reduced-motion`.

- [ ] **Step 4: Write failing interaction tests**

Assert the chart DOM node remains mounted on metric/period changes; first data uses draw state once; cached changes morph; hover, keyboard focus, and touch reveal localized date/metric/exact value; guide and point stay within the SVG; Escape or pointer leave dismisses the tooltip.

- [ ] **Step 5: Implement the accessible persistent chart**

Render stable point buttons/circles keyed by data identity rather than coordinates, expose `tabIndex`, pointer and focus handlers, and an HTML tooltip positioned from clamped SVG coordinates. Use the backend `dashboard.totals[metric]` for the caption and never use period or metric as a React key for the chart container.

- [ ] **Step 6: Run chart tests and confirm GREEN**

Run: `cd apps/site && pnpm test --run src/components/chart`

Expected: geometry, persistence, reduced-motion, and tooltip tests pass.

- [ ] **Step 7: Commit**

Commit message: `feat: morph cached activity charts`

### Task 5: Refine Layout, Typography, Glass, and Responsive UX

- [ ] **Step 1: Add UI behavior tests before refactoring**

Cover stable desktop/sidebar and mobile/bottom navigation labels, theme switching, no nested interactive controls, visible focus states, loading overlay that retains the current graph, plans expansion, and profile/logout flows.

- [ ] **Step 2: Run UI tests and confirm RED**

Run: `cd apps/site && pnpm test --run src/SiteApp.test.tsx src/screens`

Expected: failures for the new structure and localized accessible labels.

- [ ] **Step 3: Split the monolithic UI into focused components**

Keep `SiteApp.tsx` responsible for login/session/locale providers and the authenticated shell. Move Overview, Activity, Chats, Plans, Profile, Login, dashboard controls, and chart concerns into their planned modules. Memoize static navigation and dictionaries; avoid unnecessary effects and duplicated derived state.

- [ ] **Step 4: Apply the approved visual system**

Bundle `Onest Variable` locally, use it for headings and body, use a system monospace stack only for metrics, and establish 4/6/8 px radii. Implement neutral dark/light tokens, restrained glass navigation/panels/selectors/tooltips, opaque fallback for missing backdrop filters, 44 px controls, `focus-visible`, reduced motion, safe-area mobile navigation, and no viewport-scaled fonts or decorative color gradients.

- [ ] **Step 5: Densify the information hierarchy**

Compose Overview from context summary, four primary metrics, main chart, moderation, member flow, top users, and a compact managed-chat list. Keep panels unnested and add direct actions to Activity and selected-chat views. Align text to one grid with predictable maximum widths and balanced empty/error states.

- [ ] **Step 6: Run UI tests, typecheck, and build**

Run: `cd apps/site && pnpm test --run && pnpm run typecheck && pnpm run build`

Expected: tests pass, TypeScript has no errors, Vite production build succeeds, and production source maps are disabled.

- [ ] **Step 7: Commit**

Commit message: `feat: refine account dashboard experience`

### Task 6: CI, Browser Verification, and Deployment Restart

- [ ] **Step 1: Add the standalone site CI job**

Use Node 20 and pnpm 9 with `apps/site/pnpm-lock.yaml`; run frozen install, `pnpm test --run`, `pnpm run typecheck`, and `pnpm run build`. Keep Python, Mini App, and schema jobs unchanged except for required regenerated contract files.

- [ ] **Step 2: Run all local gates**

Run: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy .`, `uv run pytest -q`, `cd apps/miniapp && pnpm run build`, and `cd apps/site && pnpm test --run && pnpm run typecheck && pnpm run build`.

Expected: every command exits 0 with no ignored failures.

- [ ] **Step 3: Run Playwright desktop and mobile verification**

Start the production-like stack and verify login, RU/EN, light/dark, all five sections, all four periods, aggregate and individual chat contexts, cached morph transitions, pointer tooltip, keyboard tooltip, mobile navigation, 320 px overflow, and expired-session behavior. Capture desktop and mobile screenshots and inspect them for clipped text, overlapping controls, blank SVG, theme artifacts, and unstable layout.

- [ ] **Step 4: Restart the complete Docker stack**

Run the repository's documented Compose/Nginx startup flow, rebuild changed images, confirm all containers are healthy, and inspect bot/API/Nginx logs for startup errors.

- [ ] **Step 5: Verify public routes**

Check `/api/health`, `/site/`, Mini App root, static assets, API authentication, and the current HTTPS tunnel/domain through Nginx. Report the actual reachable URLs rather than reusing an old quick-tunnel address.

- [ ] **Step 6: Final review and commit**

Review the full diff for spec coverage, secrets, generated files, and unrelated changes. Commit message: `ci: verify account site dashboard`.

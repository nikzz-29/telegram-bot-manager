# Sidebar Navigation Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the desktop site's `01`-`05` sidebar markers with semantic monochrome SVG icons without changing navigation behaviour or layout.

**Architecture:** Keep the sidebar in `apps/site/src/SiteApp.tsx`, add a typed icon component reference to the existing navigation item data, and render the icon in the existing first grid column. Use CSS tokens already present in `apps/site/src/site.css` so light/dark themes remain consistent.

**Tech Stack:** React 18, TypeScript, lucide-react, CSS, Vitest, Testing Library, Vite.

---

### Task 1: Add the icon dependency

**Files:**
- Modify: `apps/site/package.json`
- Modify: `pnpm-lock.yaml`

- [ ] Run `pnpm --filter tg-manager-site add lucide-react`.
- [ ] Confirm `lucide-react` is listed under the site's runtime dependencies and the lockfile changes only include the expected package resolution.
- [ ] Commit with `chore(site): add sidebar icon dependency`.

### Task 2: Write the failing sidebar icon test

**Files:**
- Create: `apps/site/src/sidebar.test.tsx`
- Modify: `apps/site/src/SiteApp.tsx` (export `Sidebar` and its navigation item definition for the focused test)

- [ ] Add a test that renders the exported `Sidebar` with a deterministic profile, translation function, and section state.
- [ ] Assert that the five navigation buttons keep their translated accessible names and expose an SVG inside the first column, with `aria-hidden="true"`.
- [ ] Run `pnpm --filter tg-manager-site test --run src/sidebar.test.tsx` and confirm it fails because the sidebar still renders numeric markers.

### Task 3: Render semantic icons and preserve layout

**Files:**
- Modify: `apps/site/src/SiteApp.tsx`
- Modify: `apps/site/src/site.css`

- [ ] Import only the named Lucide icons `LayoutDashboard`, `ChartNoAxesCombined`, `MessagesSquare`, `CreditCard`, and `UserRound`.
- [ ] Change the sidebar item tuple to hold a typed icon component instead of a number string.
- [ ] Render the icon with `size={18}`, `strokeWidth={1.7}`, focus-safe `aria-hidden`, and a class used only for navigation icon styling.
- [ ] Keep `grid-template-columns: 28px 1fr`; style the SVG to inherit color and apply a restrained transform transition on hover/active.
- [ ] Respect `prefers-reduced-motion` through the existing global media query.
- [ ] Run the focused test and confirm it passes.

### Task 4: Run the full verification suite

**Files:**
- No additional files.

- [ ] Run `pnpm --filter tg-manager-site test --run`.
- [ ] Run `pnpm --filter tg-manager-site typecheck`.
- [ ] Run `pnpm --filter tg-manager-site build`.
- [ ] Check `git diff --check` and inspect the diff for unrelated changes.

### Task 5: Verify the visual result in a real browser

**Files:**
- Create only temporary artifacts under `output/playwright/` if screenshots are needed.

- [ ] Confirm `npx` is available and use the bundled Playwright CLI wrapper.
- [ ] Open the running site, capture the desktop sidebar in light theme, switch to dark theme, and capture it again.
- [ ] Confirm icon-label alignment, active state contrast, no clipping, no layout shift, and unchanged mobile bottom navigation.
- [ ] Remove temporary screenshots unless they are useful as user-facing evidence.
- [ ] Commit the implementation with `feat(site): replace sidebar numbers with icons`.

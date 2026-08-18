# Sidebar Navigation Icons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the desktop site's `01`-`05` sidebar markers with semantic monochrome SVG icons without changing navigation behaviour or layout.

**Architecture:** Keep the sidebar in `apps/site/src/SiteApp.tsx`, add a typed icon component reference to the existing navigation item data, and render the icon in the existing first grid column. The package registry is unavailable in this environment, so the icons will be small local React SVG components rather than adding a new runtime dependency. Use CSS tokens already present in `apps/site/src/site.css` so light/dark themes remain consistent.

**Tech Stack:** React 18, TypeScript, local SVG React components, CSS, Vitest, Testing Library, Vite.

---

### Task 1: Define the local icon surface

**Files:**
- Create: `apps/site/src/components/SidebarIcons.tsx`

- [x] Define five named, typed React SVG components with the same 24x24 viewBox, `fill="none"`, `stroke="currentColor"`, `strokeWidth={1.7}`, round line caps/joins, and no hardcoded theme colors.
- [x] Keep the exported icon map tree-shakeable by using direct named exports.

### Task 2: Write the failing sidebar icon test

**Files:**
- Create: `apps/site/src/sidebar.test.tsx`
- Modify: `apps/site/src/SiteApp.tsx` (export `Sidebar` and its navigation item definition for the focused test)

- [x] Add a test that renders the exported `Sidebar` with a deterministic profile, translation function, and section state.
- [x] Assert that the five navigation buttons keep their translated accessible names and expose an SVG inside the first column, with `aria-hidden="true"`.
- [x] Run the focused test before and after implementation; it failed before the icon render and passes with the implementation.

### Task 3: Render semantic icons and preserve layout

**Files:**
- Modify: `apps/site/src/SiteApp.tsx`
- Modify: `apps/site/src/site.css`

- [x] Import only the named local icons `LayoutDashboardIcon`, `ActivityIcon`, `MessagesSquareIcon`, `CreditCardIcon`, and `UserRoundIcon`.
- [x] Change the sidebar item tuple to hold a typed icon component instead of a number string.
- [x] Render the icon with `size={18}`, focus-safe `aria-hidden`, and a class used only for navigation icon styling.
- [x] Keep `grid-template-columns: 28px 1fr`; style the SVG to inherit color and apply a restrained transform transition on hover/active.
- [x] Respect `prefers-reduced-motion` through the existing global media query.
- [x] Run the focused test and confirm it passes.

### Task 4: Run the full verification suite

**Files:**
- No additional files.

- [x] Run the full site test suite (`18` tests passed).
- [x] Run the site typecheck.
- [x] Run the production build.
- [x] Check `git diff --check` and inspect the diff for unrelated changes.

### Task 5: Verify the visual result in a real browser

**Files:**
- Create only temporary artifacts under `output/playwright/` if screenshots are needed.

- [x] Open the current site in a real browser and inspect the desktop sidebar in light theme.
- [x] Switch to dark theme and confirm active icon contrast.
- [x] Confirm icon-label alignment, no clipping, and unchanged mobile bottom navigation.
- [x] Remove temporary browser artifacts.
- [ ] Commit the implementation with `feat(site): replace sidebar numbers with icons`.

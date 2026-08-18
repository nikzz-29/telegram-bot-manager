# Sidebar Navigation Icons Design

## Goal

Replace the decorative `01`-`05` markers in the desktop account-site sidebar with recognizable SVG icons while preserving the site's restrained black-and-white visual language and existing navigation geometry.

## Icon Set

Use direct named imports from `lucide-react`:

- Overview: `LayoutDashboard`
- Activity: `ChartNoAxesCombined`
- Chats: `MessagesSquare`
- Plans: `CreditCard`
- Profile: `UserRound`

The icons are semantic navigation aids, not decoration. Each icon is rendered at 18px with a consistent 1.7px stroke and `aria-hidden="true"`; the visible translated label remains the accessible button name.

## Visual Behaviour

Keep the existing 28px first grid column so labels do not move. Icons inherit the muted sidebar color by default and the foreground color in hover and active states. A restrained wrapper transition may shift or scale the icon slightly, but must not change layout, add glow, or conflict with reduced-motion settings.

The active row keeps its existing surface, shadow, and contrast treatment. Light and dark themes use the existing color tokens without icon-specific hardcoded colors.

## Scope

Only the desktop sidebar number markers change. The mobile bottom navigation remains text-only in this focused change. No navigation behaviour, translations, routes, or data loading changes.

## Verification

- A component test confirms all five navigation buttons keep their accessible translated names and render the expected icon marker.
- Site tests, TypeScript checking, and the production build pass.
- Desktop screenshots in light and dark themes confirm consistent alignment, optical weight, active state, and absence of clipping or layout shift.
- Mobile verification confirms the existing bottom navigation is unchanged.

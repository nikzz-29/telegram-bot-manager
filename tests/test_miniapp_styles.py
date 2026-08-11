"""Static checks on the Mini App's source that its own toolchain will not make.

Both of these cover failures that are *silent* — the panel builds, boots, and
renders, and the defect only shows up as something looking wrong on a phone.

DECISION: these live in the Python suite rather than as a JS lint rule. The
facts they check straddle both halves of the repo — the second one compares
`.tsx` against the `.ftl` catalogues that Python owns — and `task test` is the
gate that actually runs in CI. A rule in `eslint` would only cover the first,
and there is no eslint here to hang it on.
"""

from __future__ import annotations

from pathlib import Path
import re

from i18n.runtime import LOCALES_DIR

_ROOT = Path(__file__).resolve().parents[1]
_MINIAPP = _ROOT / "apps" / "miniapp"
_SOURCES = (*(_MINIAPP / "src").rglob("*.tsx"), *(_MINIAPP / "src").rglob("*.css"))

# `name: "var(--anything)"` in the Tailwind config — every colour whose value is
# a CSS variable rather than something Tailwind can read channels out of.
_VAR_COLOR = re.compile(r'^\s*"?([a-z][a-z0-9-]*)"?:\s*"var\(--', re.MULTILINE)

# The utility prefixes that take a colour. `w-1/2` and `top-1/2` are also
# `something/number`, which is why the prefix has to be part of the match.
_COLOR_UTILITIES = (
    "bg",
    "text",
    "border",
    "ring",
    "fill",
    "stroke",
    "divide",
    "outline",
    "shadow",
    "accent",
    "caret",
    "decoration",
    "from",
    "via",
    "to",
)


def _var_backed_colors() -> set[str]:
    config = (_MINIAPP / "tailwind.config.js").read_text(encoding="utf-8")
    return set(_VAR_COLOR.findall(config))


def test_no_opacity_modifier_on_a_theme_colour() -> None:
    """`bg-hint/20` compiles to nothing at all, and nothing warns you.

    Every colour in this panel arrives from Telegram's `themeParams` as an opaque
    `var(--tg-*)`. Tailwind can only fold an alpha into a colour whose channels it
    can see, so a modifier on one of these does not degrade — the utility is
    dropped from the stylesheet entirely. In JSX that is silent; only inside
    `@apply` does it raise.

    This is not hypothetical: the toggle track, every icon tile and the
    destructive button all shipped with no fill because of it, which is most of
    why the panel looked like unstyled markup.

    Use the pre-mixed tints (`bg-hint-tint`, `bg-accent-tint`, …) instead, or
    `opacity-60` when it is genuinely the element that should fade. Tailwind's own
    palette (`emerald-500/15`) is fine and deliberately not matched here.
    """
    colors = _var_backed_colors()
    assert colors, "parsed no var()-backed colours out of tailwind.config.js"
    utilities = "|".join(_COLOR_UTILITIES)
    # Longest first, so `hint-tint` is matched before `hint` leaves `-tint/20`
    # dangling and unmatched.
    names = "|".join(sorted(colors, key=len, reverse=True))
    pattern = re.compile(rf"\b(?:{utilities})-(?:{names})/\d+")

    offenders: dict[str, list[str]] = {}
    for path in _SOURCES:
        text = path.read_text(encoding="utf-8")
        # Strip block comments: the tokens are named in prose in several files
        # precisely to explain why they must not be used.
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        found = pattern.findall(text)
        if found:
            offenders[str(path.relative_to(_ROOT))] = sorted(set(found))
    assert not offenders, f"opacity modifiers on theme colours compile to nothing: {offenders}"


def test_panel_only_uses_keys_that_exist() -> None:
    """Every `t("...")` literal in the Mini App resolves against the catalogues.

    The panel's fallback chain ends at the key itself, so an invented key renders
    as `stats-screen-titel` in the UI rather than failing anywhere. `test_i18n`
    already covers this for `.py`; the panel is the other half, and it is the half
    where the keys are typed by hand into JSX.

    Runtime-built keys (`t(`plan-${plan}`)`) use backticks and are deliberately
    not matched — they cannot be checked statically.
    """
    call = re.compile(r"""\bt\(\s*["']([a-z][a-z0-9_-]*)["']""")
    defined: set[str] = set()
    for catalogue in ("main.ftl", "panel.ftl"):
        source = (LOCALES_DIR / "ru" / catalogue).read_text(encoding="utf-8")
        # Underscores are legal in Fluent identifiers (`plan-white_label`), so
        # the character class must include them or the regex would miss keys.
        defined |= set(re.findall(r"^([a-z][a-z0-9_-]*)\s*=", source, re.MULTILINE))

    missing: dict[str, list[str]] = {}
    for path in (_MINIAPP / "src").rglob("*.tsx"):
        absent = sorted(set(call.findall(path.read_text(encoding="utf-8"))) - defined)
        if absent:
            missing[str(path.relative_to(_ROOT))] = absent
    assert not missing, f"undefined translation keys in the panel: {missing}"

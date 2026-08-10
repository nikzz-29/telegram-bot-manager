"""Locale tests: parity, resolvability, and no leaked placeables.

A missing translation key does not fail at import — `Translator.get` returns the
key itself by design, so a typo surfaces as a chat message reading
`trigger-list-titel` in front of a thousand people. These tests are what turn
that into a red build instead.

DECISION: parity and placeholder agreement are checked across every catalogue,
including `panel.ftl`, which only the Mini App reads. Python never loads that
file, so nothing else in this suite would notice a Russian-only panel key — and
the panel's fallback is just as silent as the bot's.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

from i18n.runtime import LOCALES_DIR, SUPPORTED_LOCALES, translator

# `key = value` at the start of a line. Fluent attributes (`    .label = ...`)
# and comments are indented or prefixed, so this matches messages only.
_MESSAGE = re.compile(r"^([a-z][a-z0-9-]*)\s*=\s*(.+)$", re.MULTILINE)

# `{$placeholder}` — every argument a message expects from its caller.
_PLACEABLE = re.compile(r"\{\s*\$([a-zA-Z_][a-zA-Z0-9_]*)\s*\}")

# `main.ftl` is the bot's and the API's; `panel.ftl` is the Mini App's alone.
CATALOGUES = ("main.ftl", "panel.ftl")


def _messages(locale: str, catalogue: str = "main.ftl") -> dict[str, str]:
    source = (LOCALES_DIR / locale / catalogue).read_text(encoding="utf-8")
    return {match.group(1): match.group(2) for match in _MESSAGE.finditer(source)}


@pytest.mark.parametrize("catalogue", CATALOGUES)
def test_every_locale_ships_a_catalogue(catalogue: str) -> None:
    for locale in SUPPORTED_LOCALES:
        assert (LOCALES_DIR / locale / catalogue).is_file(), f"{locale}/{catalogue}"


@pytest.mark.parametrize("catalogue", CATALOGUES)
def test_locales_define_the_same_keys(catalogue: str) -> None:
    """A key present in one locale and absent in another falls back silently.

    English is the fallback chain's tail, so a Russian-only key renders as the
    key itself for an English user — visible only in production.
    """
    catalogues = {locale: set(_messages(locale, catalogue)) for locale in SUPPORTED_LOCALES}
    reference = catalogues["ru"]
    for locale, keys in catalogues.items():
        assert keys == reference, f"{locale}/{catalogue} differs: {keys ^ reference}"


@pytest.mark.parametrize("catalogue", CATALOGUES)
def test_locales_agree_on_placeholders(catalogue: str) -> None:
    """Both locales must ask their caller for the same arguments.

    A translation that adds `{$limit}` where the other has none renders as
    `{$limit}` verbatim, because the call site never passes it.
    """
    reference = {
        key: set(_PLACEABLE.findall(value)) for key, value in _messages("ru", catalogue).items()
    }
    for locale in SUPPORTED_LOCALES:
        for key, value in _messages(locale, catalogue).items():
            assert set(_PLACEABLE.findall(value)) == reference[key], f"{locale}/{key}"


def test_panel_keys_do_not_collide_with_the_bot_catalogue() -> None:
    """The Mini App merges both files into one bundle, first definition winning.

    `addResource` reports a duplicate id as an error and keeps the entry already
    in the bundle, so a key defined in both resolves to `main.ftl` — the bot's
    wording, in a panel that asked for its own. Invisible until the two drift.
    """
    for locale in SUPPORTED_LOCALES:
        shared = set(_messages(locale, "main.ftl")) & set(_messages(locale, "panel.ftl"))
        assert not shared, f"{locale} defines in both catalogues: {sorted(shared)}"


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_key_renders(locale: str) -> None:
    """Nothing resolves to its own key, and nothing leaks an unfilled placeable."""
    t = translator(locale)
    for key, value in _messages(locale).items():
        args = dict.fromkeys(_PLACEABLE.findall(value), 1)
        rendered = t(key, **args)
        assert rendered != key, f"{locale}/{key} did not resolve"
        assert "{" not in rendered, f"{locale}/{key} leaked a placeable: {rendered}"


def test_code_only_uses_keys_that_exist() -> None:
    """Every `t("...")` literal in the tree resolves.

    Keys built at runtime (`f"log-action-{action}"` in `core.audit`) are guarded
    by `Translator.has` at their call site and cannot be checked statically, so
    this covers the literal ones — which is where typos actually happen.
    """
    root = Path(__file__).resolve().parents[1]
    call = re.compile(r"""\bt\(\s*["']([a-z][a-z0-9-]*)["']""")
    defined = set(_messages("ru"))

    missing: set[str] = set()
    for path in (*(root / "apps").rglob("*.py"), *(root / "packages").rglob("*.py")):
        missing |= set(call.findall(path.read_text(encoding="utf-8"))) - defined
    assert not missing, f"undefined translation keys: {sorted(missing)}"


def test_audit_action_titles_exist() -> None:
    """Every icon in `ACTION_ICONS` has the log-channel title that goes with it."""
    from core.audit import ACTION_ICONS

    t = translator("ru")
    for action in ACTION_ICONS:
        key = f"log-action-{action.replace('_', '-')}"
        assert t.has(key), f"missing {key}"

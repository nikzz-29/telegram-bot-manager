"""Fluent localization runtime.

DECISION: `FluentLocalization` objects are memoized per locale. Building one
parses `main.ftl` from disk, and the bot renders a string on essentially every
update — re-parsing per message would be the single most expensive thing in the
hot path.

DECISION: a missing key returns the key itself rather than raising. A typo in a
translation key must not take down a moderation action; the untranslated key
shows up in the chat and in the logs, which is loud enough to get fixed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Final

from fluent.runtime import FluentLocalization, FluentResourceLoader

LOCALES_DIR = Path(__file__).resolve().parents[2] / "locales"

SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("ru", "en")
DEFAULT_LOCALE: Final = "ru"
FALLBACK_LOCALE: Final = "en"

# The catalogues the bot, the worker and the API read, in load order.
#
# DECISION: copy is split by surface rather than kept in one file. `main.ftl` is
# what the bot says in groups and changes with the modules; `dm.ftl` is the
# private-chat dialogue; `guide.ftl` is the manual, which is long and nearly
# static. One file meant every change to any of the three landed in the same
# three hundred lines.
#
# The split is a filing decision only — the bundle is flat, so a key defined in
# two catalogues resolves to whichever loads first and the other wording silently
# never ships. `tests/test_i18n.py` checks that no key is defined twice.
BOT_CATALOGUES: Final[tuple[str, ...]] = ("main.ftl", "dm.ftl", "guide.ftl")

# The Mini App's own copy. Python never loads it: nothing server-side renders a
# panel string, and parsing it per process would be dead weight. The panel bundles
# it together with the files above (see `apps/miniapp/src/i18n/bundles.ts`).
PANEL_CATALOGUES: Final[tuple[str, ...]] = ("panel.ftl",)

# Every catalogue that ships, for the tests that check parity across all of them.
CATALOGUES: Final[tuple[str, ...]] = BOT_CATALOGUES + PANEL_CATALOGUES


def normalize_locale(locale: str | None) -> str:
    """Map a Telegram `language_code` onto a locale we actually ship."""
    if not locale:
        return DEFAULT_LOCALE
    short = locale.replace("_", "-").split("-")[0].lower()
    return short if short in SUPPORTED_LOCALES else FALLBACK_LOCALE


@lru_cache(maxsize=len(SUPPORTED_LOCALES) + 1)
def localization(locale: str) -> FluentLocalization:
    """Memoized `FluentLocalization` for one locale, with English as fallback."""
    selected = normalize_locale(locale)
    chain = [selected] if selected == FALLBACK_LOCALE else [selected, FALLBACK_LOCALE]
    resource_loader = FluentResourceLoader(str(LOCALES_DIR / "{locale}"))
    return FluentLocalization(chain, list(BOT_CATALOGUES), resource_loader, use_isolating=False)


class Translator:
    """Thin per-locale wrapper: `t("warn-issued", count=2, limit=3)`."""

    __slots__ = ("_bundle", "locale")

    def __init__(self, locale: str | None = None) -> None:
        self.locale = normalize_locale(locale)
        self._bundle = localization(self.locale)

    def __call__(self, key: str, /, **args: Any) -> str:
        return self.get(key, **args)

    def get(self, key: str, /, **args: Any) -> str:
        rendered: str = self._bundle.format_value(key, args or None)
        return rendered

    def has(self, key: str) -> bool:
        """True when the key resolves — `format_value` echoes unknown keys back."""
        return self.get(key) != key

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Translator({self.locale!r})"


@lru_cache(maxsize=len(SUPPORTED_LOCALES) + 1)
def translator(locale: str | None = None) -> Translator:
    return Translator(locale)


__all__ = [
    "BOT_CATALOGUES",
    "CATALOGUES",
    "DEFAULT_LOCALE",
    "FALLBACK_LOCALE",
    "LOCALES_DIR",
    "PANEL_CATALOGUES",
    "SUPPORTED_LOCALES",
    "Translator",
    "localization",
    "normalize_locale",
    "translator",
]

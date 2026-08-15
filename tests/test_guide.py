"""Every rendered manual line stays scannable in a Telegram DM."""

from __future__ import annotations

import unicodedata

import pytest

from bot.guide import PAGES, GuidePage, render
from i18n.runtime import SUPPORTED_LOCALES, translator


def _has_symbol(line: str) -> bool:
    return bool(line) and unicodedata.category(line[0]) in {"So", "Sk"}


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
@pytest.mark.parametrize("page", PAGES)
def test_every_nonblank_manual_line_has_an_emoji_anchor(locale: str, page: GuidePage) -> None:
    text = render(page, translator(locale))
    for line in text.splitlines():
        if not line.strip():
            continue
        visible = line.lstrip()
        if visible.startswith(("├ ", "└ ")):
            visible = visible[2:].lstrip()
        assert _has_symbol(visible), (locale, page.slug, line)

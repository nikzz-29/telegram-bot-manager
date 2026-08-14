"""The in-bot manual: which pages exist, and how one is rendered.

DECISION: the manual is a table of pages here and prose in `guide.ftl`, not one
long message. Telegram refuses a message over 4096 characters, and a full
description of moderation, the AI, entry control, triggers, autoposting,
statistics, plans and every command is several times that. Splitting it also
makes it navigable: a page is what someone tapped, not what they have to scroll
past to reach what they tapped.

DECISION: the page list lives in Python and the text lives in the catalogue, so
adding a language is a translation and never a code change. A page carries only
its slug, its icon and the two keys it renders; nothing here knows what any page
says.

DECISION: slugs are short and stable because they travel in callback data, which
Telegram caps at 64 bytes for the whole payload. `guide:moderation` fits with
room to spare; a slug that is a sentence would not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
import unicodedata

from i18n.runtime import Translator

# Telegram's hard ceiling is 4096 characters. The margin absorbs a long chat
# title or a locale that runs longer than the one a page was written in, and
# `tests/test_guide.py` holds every rendered page under it.
MAX_PAGE_CHARS: Final = 3500


@dataclass(frozen=True, slots=True)
class GuidePage:
    """One screen of the manual."""

    slug: str
    icon: str
    title_key: str
    body_key: str

    def button(self, t: Translator) -> str:
        """The label this page gets in the manual's index keyboard."""
        return f"{self.icon} {t(self.title_key)}"


def _page(slug: str, icon: str) -> GuidePage:
    """Key names are derived, never spelled twice — a typo would render as a key."""
    return GuidePage(
        slug=slug,
        icon=icon,
        title_key=f"guide-{slug}-title",
        body_key=f"guide-{slug}-body",
    )


# Reading order, which is also the order of the buttons: what the bot is, how to
# set it up, then one page per module in the order a chat grows into them, then
# the reference material.
PAGES: Final[tuple[GuidePage, ...]] = (
    _page("overview", "🧭"),
    _page("setup", "🚀"),
    _page("moderation", "🛡"),
    _page("entry", "🚪"),
    _page("ai", "🤖"),
    _page("engagement", "💬"),
    _page("autopost", "📅"),
    _page("stats", "📊"),
    _page("crossban", "🌐"),
    _page("plans", "💎"),
    _page("commands", "⌨️"),
    _page("faq", "❓"),
)

_BY_SLUG: Final[dict[str, GuidePage]] = {page.slug: page for page in PAGES}


def page_for(slug: str) -> GuidePage | None:
    """Look a page up by slug. `None` for anything else — callback data is input."""
    return _BY_SLUG.get(slug)


def neighbours(page: GuidePage) -> tuple[GuidePage | None, GuidePage | None]:
    """The pages before and after this one, for ‹ and › buttons.

    Deliberately not a ring: someone who reaches the last page and taps forward
    should find nothing there rather than silently start over, because a manual
    that loops gives no signal that it has ended.
    """
    index = PAGES.index(page)
    previous = PAGES[index - 1] if index > 0 else None
    following = PAGES[index + 1] if index + 1 < len(PAGES) else None
    return previous, following


def position(page: GuidePage) -> tuple[int, int]:
    """`(nth, total)`, one-based — what "3 / 12" in the footer is built from."""
    return PAGES.index(page) + 1, len(PAGES)


def _starts_with_emoji(line: str) -> bool:
    """Recognise the symbol-led lines already authored in the catalogues."""
    content = line.lstrip()
    return bool(content) and unicodedata.category(content[0]) in {"So", "Sk"}


def _decorate_body(body: str) -> str:
    """Give every visible manual line a small semantic visual anchor.

    Guide copy is translated prose, so requiring translators to remember a
    prefix on every wrapped line is brittle. The renderer keeps explicit icons,
    then applies stable markers to headings, commands, lists and prose. This
    also covers new language files without changing their words.
    """
    decorated: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            decorated.append("")
        elif _starts_with_emoji(line):
            decorated.append(line)
        elif line.startswith("<b>"):
            decorated.append(f"📌 {line}")
        elif line.startswith("•"):
            decorated.append(f"▫️ {line[1:].lstrip()}")
        elif line.startswith(("/", "<code>")):
            decorated.append(f"⌨️ {line}")
        elif line[0].isdigit():
            decorated.append(f"🔢 {line}")
        else:
            decorated.append(f"💡 {line}")
    return "\n".join(decorated)


def render(page: GuidePage, t: Translator) -> str:
    """The message body for one page: heading, then prose.

    Nothing is escaped here and nothing needs to be: every character comes from
    the catalogue, which is ours and which deliberately contains HTML tags.
    """
    return f"{page.icon} <b>{t(page.title_key)}</b>\n\n{_decorate_body(t(page.body_key))}"


__all__ = [
    "MAX_PAGE_CHARS",
    "PAGES",
    "GuidePage",
    "_decorate_body",
    "neighbours",
    "page_for",
    "position",
    "render",
]

"""Rendering an admin-authored greeting.

Spec §5.2: the welcome text supports `{name}`, `{chat}` and `{rules_link}`, plus
optional media and inline buttons.

DECISION: greetings are not Fluent messages. Fluent covers strings *we* ship and
translate; a greeting is content the chat's own admin wrote, so it is stored
verbatim and only has its placeholders filled. That also means the bot's parse
mode applies to it — an admin who writes `<b>` gets bold, which is the feature
they expect from every other bot.

DECISION: substituted *values* are HTML-escaped, the surrounding template is not.
A member called `<script>` must not inject markup into a message the admin wrote,
and a member called `Bob & Alice` must not break its parsing. The one value that
is legitimately markup — the `<a href="tg://user?id=…">` mention — says so by
being an `Html` instance, so "insert verbatim" is a decision made at the call
site and visible in the code, not a flag that quietly disables escaping for
everything.
"""

from __future__ import annotations

from html import escape
from typing import Final


class Html(str):
    """A string that is already HTML and must not be escaped again."""

    __slots__ = ()


# Only these three are replaced. `str.format` is deliberately not used: an admin
# writing a literal `{` (a smiley, a code sample) would otherwise raise, and any
# unknown `{placeholder}` would take the whole greeting down at send time.
PLACEHOLDERS: Final[tuple[str, ...]] = ("name", "chat", "rules_link")

MAX_LENGTH: Final = 4_000


def _safe(value: str) -> str:
    return value if isinstance(value, Html) else escape(value)


def render_greeting(
    template: str,
    *,
    name: str,
    chat: str,
    rules_link: str = "",
) -> str:
    """Fill `{name}`, `{chat}` and `{rules_link}` in an admin's greeting."""
    values = {"name": name, "chat": chat, "rules_link": rules_link}
    rendered = template
    for key in PLACEHOLDERS:
        rendered = rendered.replace(f"{{{key}}}", _safe(values[key]))
    return rendered[:MAX_LENGTH]


def uses_placeholder(template: str, name: str) -> bool:
    """Whether a template references a placeholder — used to validate settings."""
    return f"{{{name}}}" in template


__all__ = ["MAX_LENGTH", "PLACEHOLDERS", "Html", "render_greeting", "uses_placeholder"]

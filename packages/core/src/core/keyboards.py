"""Inline keyboards built from stored JSON.

Triggers and scheduled posts both keep their buttons as a list of
`{"text": ..., "url": ...}` dicts, written by the Mini App composer. The bot
renders them when a trigger fires and the worker renders them when a post goes
out, so the builder lives here rather than in either process.

DECISION: only URL buttons are supported. A callback button would need a handler
that knows what the callback means, and a post composed in the Mini App has no
handler behind it — a dead button is worse than no button.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Telegram rejects a keyboard with more than 100 buttons; a post that long is a
# composer bug rather than a layout, so the extras are dropped rather than
# turning the whole send into a 400.
MAX_BUTTONS = 100


def inline_url_keyboard(raw: list[dict[str, Any]]) -> InlineKeyboardMarkup | None:
    """One button per row, skipping any entry missing a label or a URL."""
    rows = [
        [InlineKeyboardButton(text=str(button["text"]), url=str(button["url"]))]
        for button in raw[:MAX_BUTTONS]
        if button.get("text") and button.get("url")
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


__all__ = ["MAX_BUTTONS", "inline_url_keyboard"]

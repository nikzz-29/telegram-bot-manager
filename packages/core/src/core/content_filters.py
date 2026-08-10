"""Content filters — which message types a chat refuses to keep.

DECISION: the rules run against a `MessageFacts` snapshot rather than an aiogram
`Message`. Extracting the facts is ten lines in the bot layer; keeping the rules
Telegram-free makes every filter a table-driven unit test instead of a fixture
factory, and the same facts feed anti-flood's media window and the AI sampler.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

from shared.schemas.module_configs import ContentFilters

# Entity types Telegram assigns to anything that navigates out of the chat.
LINK_ENTITIES: Final[frozenset[str]] = frozenset({"url", "text_link"})
MENTION_ENTITIES: Final[frozenset[str]] = frozenset({"mention", "text_mention"})


@dataclass(frozen=True, slots=True)
class MessageFacts:
    """The properties of one message that any filter might care about."""

    text: str = ""
    content_kind: str = "text"
    entity_types: frozenset[str] = field(default_factory=frozenset)
    is_forward: bool = False
    is_channel_sender: bool = False
    has_link_preview: bool = False
    is_service: bool = False
    via_bot: bool = False

    @property
    def has_links(self) -> bool:
        return bool(self.entity_types & LINK_ENTITIES) or self.has_link_preview

    @property
    def has_mentions(self) -> bool:
        return bool(self.entity_types & MENTION_ENTITIES)


# Filter switch -> predicate. Ordered most-specific first so the reported reason
# is the interesting one: a forwarded sticker reads better as "forwards".
_RULES: Final[tuple[tuple[str, str], ...]] = (
    ("channel_senders", "is_channel_sender"),
    ("forwards", "is_forward"),
    ("links", "has_links"),
    ("mentions", "has_mentions"),
)

# Filter switch -> the `content_kind` it rejects.
_KIND_RULES: Final[dict[str, str]] = {
    "photo": "photos",
    "video": "videos",
    "animation": "gifs",
    "sticker": "stickers",
    "voice": "voices",
    "video_note": "video_notes",
    "document": "documents",
}


def enabled_filters(filters: ContentFilters) -> Iterator[str]:
    """Names of the switches a chat has turned on."""
    for name, value in filters.model_dump().items():
        if value:
            yield name


def check(facts: MessageFacts, filters: ContentFilters) -> str | None:
    """Return the name of the first filter this message trips, or `None`.

    Service messages are exempt: they are removed by `delete_service_messages`,
    which is a separate switch with separate intent.
    """
    if facts.is_service or not filters.any_enabled:
        return None

    for switch, attribute in _RULES:
        if getattr(filters, switch) and getattr(facts, attribute):
            return switch

    kind_switch = _KIND_RULES.get(facts.content_kind)
    if kind_switch is not None and getattr(filters, kind_switch):
        return kind_switch
    return None


__all__ = [
    "LINK_ENTITIES",
    "MENTION_ENTITIES",
    "MessageFacts",
    "check",
    "enabled_filters",
]

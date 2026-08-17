"""Turning an aiogram `Message` into the Telegram-free facts the domain uses.

This is the only place that knows which of the forty-odd optional attributes on
`Message` are set for which kind of content, so the filters, the anti-flood media
window and (later) the AI sampler all read the same snapshot.
"""

from __future__ import annotations

from html import escape
from typing import Final

from aiogram.enums import ChatType
from aiogram.types import Message, User

from core.content_filters import MessageFacts

# Checked in order: the first attribute that is set names the content kind.
# Text comes last, because a media message with a caption sets both.
_KIND_ATTRIBUTES: Final[tuple[tuple[str, str], ...]] = (
    ("photo", "photo"),
    ("video", "video"),
    ("animation", "animation"),
    ("sticker", "sticker"),
    ("voice", "voice"),
    ("video_note", "video_note"),
    ("audio", "audio"),
    ("document", "document"),
    ("poll", "poll"),
    ("dice", "dice"),
    ("contact", "contact"),
    ("location", "location"),
    ("venue", "venue"),
    ("game", "game"),
    ("story", "story"),
    ("invoice", "invoice"),
)

# Attributes Telegram sets on messages the *chat itself* produced (joins, pins,
# title changes). `delete_service_messages` is the switch that removes them.
_SERVICE_ATTRIBUTES: Final[tuple[str, ...]] = (
    "new_chat_members",
    "left_chat_member",
    "new_chat_title",
    "new_chat_photo",
    "delete_chat_photo",
    "group_chat_created",
    "supergroup_chat_created",
    "channel_chat_created",
    "message_auto_delete_timer_changed",
    "migrate_to_chat_id",
    "migrate_from_chat_id",
    "pinned_message",
    "video_chat_scheduled",
    "video_chat_started",
    "video_chat_ended",
    "video_chat_participants_invited",
    "forum_topic_created",
    "forum_topic_edited",
    "forum_topic_closed",
    "forum_topic_reopened",
    "general_forum_topic_hidden",
    "general_forum_topic_unhidden",
    "boost_added",
    "users_shared",
    "chat_shared",
    "successful_payment",
    "proximity_alert_triggered",
    "write_access_allowed",
    "giveaway_created",
    "giveaway_completed",
)

DEFAULT_KIND: Final = "text"


def content_kind(message: Message) -> str:
    """Name the kind of content this message carries."""
    for attribute, kind in _KIND_ATTRIBUTES:
        if getattr(message, attribute, None) is not None:
            return kind
    return DEFAULT_KIND


def is_service(message: Message) -> bool:
    """True for messages the chat generated rather than a member composing one."""
    return any(getattr(message, attribute, None) is not None for attribute in _SERVICE_ATTRIBUTES)


def is_anonymous_admin(message: Message) -> bool:
    """True when Telegram says an anonymous administrator posted as the chat."""
    sender_chat = message.sender_chat
    return sender_chat is not None and sender_chat.id == message.chat.id


def message_text(message: Message) -> str:
    """Whatever text a filter should read: body, caption or poll question."""
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    if message.poll is not None:
        options = " ".join(option.text for option in message.poll.options)
        return f"{message.poll.question} {options}".strip()
    return ""


def _entity_types(message: Message) -> frozenset[str]:
    entities = message.entities or message.caption_entities or []
    return frozenset(entity.type for entity in entities)


def _is_forward(message: Message) -> bool:
    """DECISION: `is_automatic_forward` is not a forward for filter purposes — it
    is the linked channel's post arriving in the discussion group, which the
    admins wired up on purpose."""
    if message.is_automatic_forward:
        return False
    return message.forward_origin is not None


def _is_channel_sender(message: Message) -> bool:
    """A member posting under a channel's identity, not the group itself."""
    sender_chat = message.sender_chat
    if sender_chat is None or message.is_automatic_forward:
        return False
    return sender_chat.id != message.chat.id and sender_chat.type != ChatType.PRIVATE


def facts_from(message: Message) -> MessageFacts:
    """Snapshot everything the domain rules need from one message."""
    preview = message.link_preview_options
    return MessageFacts(
        text=message_text(message),
        content_kind=content_kind(message),
        entity_types=_entity_types(message),
        is_forward=_is_forward(message),
        is_channel_sender=_is_channel_sender(message),
        has_link_preview=bool(preview is not None and preview.url),
        is_service=is_service(message),
        via_bot=message.via_bot is not None,
    )


def display_name(user: User | None) -> str:
    """Best human-readable label for a user: full name, or `@username`."""
    if user is None:
        return ""
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    if name:
        return name
    return f"@{user.username}" if user.username else str(user.id)


def mention(user: User | None) -> str:
    """HTML mention that survives the user having no username."""
    if user is None:
        return ""
    return f'<a href="tg://user?id={user.id}">{escape(display_name(user))}</a>'


__all__ = [
    "DEFAULT_KIND",
    "content_kind",
    "display_name",
    "facts_from",
    "is_anonymous_admin",
    "is_service",
    "mention",
    "message_text",
]

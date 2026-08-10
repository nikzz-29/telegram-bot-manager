"""Telegram method builders for enforcement.

The bot process applies a punishment and the worker lifts it hours later. Both
have to send byte-identical calls, so the calls are built here once rather than
spelled out at each site.

DECISION: every builder returns an unsent `TelegramMethod`. The caller hands it
to `MessageSender`, which owns rate limiting and retries — nothing in this file
touches the network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from aiogram.methods import (
    BanChatMember,
    DeleteMessage,
    RestrictChatMember,
    SetChatPermissions,
    UnbanChatMember,
)
from aiogram.types import ChatPermissions

# DECISION: unmuting sends every permission as True rather than restoring the
# chat's defaults. Telegram exposes no way to read a member's pre-restriction
# state, and a user who can suddenly post again is a far smaller surprise than
# one who is still half-muted with no way for an admin to tell why.
FULL_PERMISSIONS: Final = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_change_info=False,
    can_invite_users=True,
    can_pin_messages=False,
    can_manage_topics=False,
)

MUTED_PERMISSIONS: Final = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_manage_topics=False,
)

# Read-only mode: nobody but admins may post, but the chat stays readable.
READ_ONLY_PERMISSIONS: Final = MUTED_PERMISSIONS


def mute(tg_chat_id: int, tg_user_id: int, until: datetime | None = None) -> RestrictChatMember:
    return RestrictChatMember(
        chat_id=tg_chat_id,
        user_id=tg_user_id,
        permissions=MUTED_PERMISSIONS,
        until_date=until,
    )


def unmute(tg_chat_id: int, tg_user_id: int) -> RestrictChatMember:
    return RestrictChatMember(chat_id=tg_chat_id, user_id=tg_user_id, permissions=FULL_PERMISSIONS)


def ban(
    tg_chat_id: int,
    tg_user_id: int,
    until: datetime | None = None,
    *,
    revoke_messages: bool = False,
) -> BanChatMember:
    return BanChatMember(
        chat_id=tg_chat_id,
        user_id=tg_user_id,
        until_date=until,
        revoke_messages=revoke_messages,
    )


def unban(tg_chat_id: int, tg_user_id: int) -> UnbanChatMember:
    """`only_if_banned` keeps an unban from evicting a member who never was."""
    return UnbanChatMember(chat_id=tg_chat_id, user_id=tg_user_id, only_if_banned=True)


def kick(tg_chat_id: int, tg_user_id: int) -> tuple[BanChatMember, UnbanChatMember]:
    """A kick is a ban followed by an unban — Telegram has no other spelling."""
    return ban(tg_chat_id, tg_user_id), unban(tg_chat_id, tg_user_id)


def delete_message(tg_chat_id: int, message_id: int) -> DeleteMessage:
    return DeleteMessage(chat_id=tg_chat_id, message_id=message_id)


def set_read_only(tg_chat_id: int, *, enabled: bool) -> SetChatPermissions:
    return SetChatPermissions(
        chat_id=tg_chat_id,
        permissions=READ_ONLY_PERMISSIONS if enabled else FULL_PERMISSIONS,
    )


__all__ = [
    "FULL_PERMISSIONS",
    "MUTED_PERMISSIONS",
    "READ_ONLY_PERMISSIONS",
    "ban",
    "delete_message",
    "kick",
    "mute",
    "set_read_only",
    "unban",
    "unmute",
]

"""aiogram filters shared by every module.

DECISION: the admin check is a filter, not a line at the top of each handler.
A handler that fails the filter simply does not match, so a non-admin typing
`/ban` in a chat where another bot owns that command does not get an argument
about it — and the check is impossible to forget on a new handler.
"""

from __future__ import annotations

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot.facts import is_anonymous_admin
from core.admins import admins
from core.context import ChatContext


class IsChatAdmin(BaseFilter):
    """Passes when the author administers the chat (cached `getChatMember`)."""

    async def __call__(self, message: Message, **data: Any) -> bool:
        ctx: ChatContext | None = data.get("ctx")
        if ctx is None:
            return False
        # An anonymous admin posts as the chat itself; Telegram already proved
        # they hold the rights, and `getChatMember` cannot confirm it for them.
        if is_anonymous_admin(message):
            return True
        if message.from_user is None:
            return False
        return await admins.is_admin(ctx.tg_chat_id, message.from_user.id)


class InGroup(BaseFilter):
    """Passes only where a `ChatContext` exists — i.e. in a managed group."""

    async def __call__(self, message: Message, **data: Any) -> bool:
        return data.get("ctx") is not None


__all__ = ["InGroup", "IsChatAdmin"]

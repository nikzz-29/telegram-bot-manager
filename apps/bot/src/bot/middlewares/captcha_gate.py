"""Captcha gate — read-only until the challenge is solved.

Spec §4.3 puts this immediately after the global-ban check and before any content
rule: a member who has not passed the captcha should not be able to trip filters,
move counters, or fire triggers.

DECISION: a pending member is *already* muted in Telegram, so in the normal case
this gate never sees a message from one. It exists for the gap — a member who was
restricted a moment too late, an admin who lifted the mute by hand, a message
that was in flight — and for anonymous-admin sends that Telegram exempts from
restrictions. That makes it a second lock, which is why it may fail open.

DECISION: the check is one Redis `EXISTS` against a marker, not a query, and it
only runs in chats that actually have captcha switched on. A chat without the
feature pays nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from core import actions
from core.captcha import captcha
from core.context import ChatContext
from core.sender import SendPriority, sender
from shared.logging import get_logger

logger = get_logger(__name__)


class CaptchaGateMiddleware(BaseMiddleware):
    """Drops (and deletes) messages from members with a pending challenge."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        user = getattr(event, "from_user", None)
        if (
            ctx is None
            or user is None
            or user.is_bot
            or not ctx.entry.captcha_enabled
            or not isinstance(event, Message)
        ):
            return await handler(event, data)

        if not await captcha.is_pending(ctx.chat_id, user.id):
            return await handler(event, data)

        sender.enqueue(
            actions.delete_message(ctx.tg_chat_id, event.message_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        logger.info("captcha_gate.blocked", chat_id=ctx.chat_id, user_id=user.id)
        return None


__all__ = ["CaptchaGateMiddleware"]

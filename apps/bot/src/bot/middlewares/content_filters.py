"""Content filters: the message types a chat refuses to keep.

The rule itself lives in `core.content_filters`; this middleware is the bridge —
it builds the facts, asks the domain, and hands the verdict to the enforcement
helper. Admins are exempt when the chat says so.

DECISION: filters run on edited messages too. Posting a clean message and editing
a link into it is the oldest way around a link filter.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.enforcement import enforce
from bot.facts import facts_from
from core import actions, content_filters
from core.admins import admins
from core.context import ChatContext
from core.sender import SendPriority, sender
from shared.enums import ModerationAction, ModuleName
from shared.logging import get_logger

logger = get_logger(__name__)


class ContentFilterMiddleware(BaseMiddleware):
    """Deletes messages whose content type the chat has switched off."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        if not isinstance(event, Message) or ctx is None or event.from_user is None:
            return await handler(event, data)
        if not ctx.module_enabled(ModuleName.MODERATION):
            return await handler(event, data)

        config = ctx.moderation
        facts = facts_from(event)
        data["facts"] = facts

        if facts.is_service:
            if config.delete_service_messages:
                sender.enqueue(
                    actions.delete_message(ctx.tg_chat_id, event.message_id),
                    chat_id=ctx.tg_chat_id,
                    priority=SendPriority.MODERATION,
                )
                return None
            return await handler(event, data)

        if not config.filters.any_enabled:
            return await handler(event, data)
        if config.exempt_admins and await admins.is_admin(ctx.tg_chat_id, event.from_user.id):
            return await handler(event, data)

        tripped = content_filters.check(facts, config.filters)
        if tripped is None:
            return await handler(event, data)

        await enforce(
            event,
            ctx,
            action=config.filter_action or ModerationAction.DELETE,
            audit_action="content_filter",
            reason=f"filter:{tripped}",
            notice_key="notice-filter",
            notice_args={"filter": tripped},
        )
        return None


__all__ = ["ContentFilterMiddleware"]

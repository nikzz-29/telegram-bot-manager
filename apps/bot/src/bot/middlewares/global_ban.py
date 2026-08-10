"""Global ban gate.

A user on the platform-wide blacklist is a known scammer, and their updates stop
here for every tenant: no handler runs, no counters move, nothing is logged
beyond one line.

DECISION: the gate stops processing everywhere, but only *enforces* a chat-side
ban when the chat has the cross-ban module on. Blocking a known scammer from
driving our handlers is platform hygiene and costs nothing; removing them from a
group is a moderation decision that belongs to the chat's plan (spec §5.7,
Business), so a Free chat sees the message ignored, not its member banned.

DECISION: the verdict is cached for `TTL_GLOBAL_BAN` (5 min) against a key tagged
by user, so promoting or appealing a ban invalidates it with one call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from core import actions, cache
from core.context import ChatContext
from core.sender import SendPriority, sender
from db.uow import UnitOfWork
from shared.enums import ModuleName
from shared.logging import get_logger

logger = get_logger(__name__)


async def is_globally_banned(tg_user_id: int) -> bool:
    """Read-through cached blacklist lookup."""
    key = cache.global_ban_key(tg_user_id)
    cached = await cache.get_value(key)
    if isinstance(cached, bool):
        return cached

    async with UnitOfWork() as uow:
        banned = await uow.global_bans.is_banned(tg_user_id)
    await cache.set_value(key, banned, ttl=cache.TTL_GLOBAL_BAN, tags=(cache.user_tag(tg_user_id),))
    return banned


class GlobalBanMiddleware(BaseMiddleware):
    """Stops updates from blacklisted users before any module sees them."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.is_bot:
            return await handler(event, data)
        if not await is_globally_banned(user.id):
            return await handler(event, data)

        ctx: ChatContext | None = data.get("ctx")
        logger.info(
            "global_ban.blocked",
            user_id=user.id,
            chat_id=ctx.chat_id if ctx is not None else None,
        )

        if isinstance(event, Message) and ctx is not None:
            sender.enqueue(
                actions.delete_message(ctx.tg_chat_id, event.message_id),
                chat_id=ctx.tg_chat_id,
                priority=SendPriority.MODERATION,
            )
            if ctx.module_enabled(ModuleName.CROSSBAN):
                sender.enqueue(
                    actions.ban(ctx.tg_chat_id, user.id),
                    chat_id=ctx.tg_chat_id,
                    priority=SendPriority.MODERATION,
                )
        elif isinstance(event, CallbackQuery):
            # An unanswered callback spins in the client until it times out.
            await event.answer()
        return None


__all__ = ["GlobalBanMiddleware", "is_globally_banned"]

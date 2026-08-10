"""Forced subscription: hold back messages from people who have not joined.

Placed after the captcha gate and before the content filters. A newcomer still
solving a captcha is already held, and there is no point spending a channel
membership check — or a Redis lookup — on a message the stop-word rules are about
to delete anyway.

DECISION: the prompt is rate-limited to one per user per five minutes, keyed in
the same cache entry the verdict uses. Someone typing into a chat they cannot
post in would otherwise get a bot reply per attempt, which is how a helpful gate
turns into the noisiest thing in the room.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from bot.facts import mention
from bot.replies import send
from core import actions, cache
from core.admins import admins
from core.context import ChatContext
from core.sender import SendPriority, sender
from core.subscription import subscription
from i18n.runtime import translator
from shared.enums import ModuleName
from shared.logging import get_logger
from shared.plans import Feature

logger = get_logger(__name__)

# How long the prompt stays in the chat, and how long before the same user is
# prompted again.
PROMPT_TTL: Final = timedelta(minutes=2)
PROMPT_COOLDOWN: Final = 300

CALLBACK_DATA: Final = "sub:check"


def _prompt_key(chat_id: int, tg_user_id: int) -> str:
    return f"{cache.KEY_PREFIX}:sub:prompt:{chat_id}:{tg_user_id}"


def _keyboard(url: str, label: str, check_label: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=check_label, callback_data=CALLBACK_DATA)]]
    if url:
        rows.insert(0, [InlineKeyboardButton(text=label, url=url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class ForcedSubscriptionMiddleware(BaseMiddleware):
    """Deletes messages from members who have not joined the required channel."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        ctx: ChatContext | None = data.get("ctx")
        if not isinstance(event, Message) or ctx is None or event.from_user is None:
            return await handler(event, data)
        if not ctx.module_enabled(ModuleName.ENTRY) or not ctx.has(Feature.FORCED_SUBSCRIPTION):
            return await handler(event, data)

        channel_id = subscription.required(ctx.entry)
        if channel_id is None:
            return await handler(event, data)

        user = event.from_user
        if user.is_bot or await admins.is_admin(ctx.tg_chat_id, user.id):
            return await handler(event, data)

        if await subscription.is_subscribed(ctx.chat_id, user.id, channel_id=channel_id):
            return await handler(event, data)

        sender.enqueue(
            actions.delete_message(ctx.tg_chat_id, event.message_id),
            chat_id=ctx.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        await self._prompt(ctx, user_id=user.id, mention_html=mention(user))
        logger.info("forced_sub.blocked", chat_id=ctx.chat_id, user_id=user.id)
        return None

    @staticmethod
    async def _prompt(ctx: ChatContext, *, user_id: int, mention_html: str) -> None:
        """Explain the gate, at most once per `PROMPT_COOLDOWN` per user."""
        key = _prompt_key(ctx.chat_id, user_id)
        if await cache.get_value(key) is not None:
            return
        await cache.set_value(
            key, True, ttl=PROMPT_COOLDOWN, tags=(cache.chat_tag(ctx.chat_id),)
        )

        t = translator(ctx.language)
        await send(
            ctx.tg_chat_id,
            t("forced-sub-required", user=mention_html),
            priority=SendPriority.MODERATION,
            ttl=PROMPT_TTL,
            keyboard=_keyboard(
                ctx.entry.forced_subscription_channel_url,
                t("forced-sub-join-button"),
                t("forced-sub-check-button"),
            ),
        )


__all__ = ["CALLBACK_DATA", "PROMPT_COOLDOWN", "PROMPT_TTL", "ForcedSubscriptionMiddleware"]

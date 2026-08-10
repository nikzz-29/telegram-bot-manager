"""Forced subscription: you must join the channel to speak in the chat.

Spec §5.2 lists it under the entry module — an admin points the chat at a channel
and the bot holds back messages from anyone who has not joined it.

DECISION: the check fails *open*. Telegram answers `getChatMember` for a channel
only while the bot is an administrator there; the moment an admin removes it, or
the API blips, every member would otherwise be silenced at once. A chat going
briefly unguarded is a far smaller failure than a chat going mute, so an
unreachable channel is logged and treated as "subscribed".

DECISION: verdicts are cached per chat+user for `admin_cache_ttl_seconds`, the
same five minutes the spec fixes for `getChatMember`, and a *positive* verdict is
what gets cached longest. Someone who just joined must not be blocked again on
their next message, while someone who left keeps posting for at most one TTL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from core import cache
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.module_configs import EntryConfig

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Bot

logger = get_logger(__name__)

# Statuses that count as "in the channel". `restricted` is included: a channel
# member who cannot post is still a subscriber, which is all this gate asks for.
SUBSCRIBED_STATUSES = frozenset(
    {
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.RESTRICTED,
    }
)

# A member who has not joined is re-checked sooner than the positive TTL, so the
# "I joined, let me in" round trip stays short.
NEGATIVE_TTL = 60


class MemberFetcher(Protocol):
    """The one Bot method this service needs."""

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any: ...


class SubscriptionService:
    """Cached channel-membership checks for the forced-subscription gate."""

    def __init__(self, bot: MemberFetcher | None = None) -> None:
        self._bot = bot

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    def required(self, config: EntryConfig) -> int | None:
        """The channel a chat requires, or `None` when the gate is off."""
        if not config.forced_subscription_enabled:
            return None
        return config.forced_subscription_channel_id or None

    async def is_subscribed(self, chat_id: int, tg_user_id: int, *, channel_id: int) -> bool:
        """Whether the user belongs to the channel. Cached; fails open."""
        key = cache.subscription_key(chat_id, tg_user_id)
        cached = await cache.get_value(key)
        if isinstance(cached, bool):
            return cached

        verdict = await self._fetch(channel_id, tg_user_id)
        await cache.set_value(
            key,
            verdict,
            ttl=get_settings().admin_cache_ttl_seconds if verdict else NEGATIVE_TTL,
            tags=(cache.chat_tag(chat_id),),
        )
        return verdict

    async def _fetch(self, channel_id: int, tg_user_id: int) -> bool:
        if self._bot is None:
            logger.warning("subscription.no_bot")
            return True
        try:
            member = await self._bot.get_chat_member(channel_id, tg_user_id)
        except TelegramAPIError as exc:
            # See the module docstring: unreachable channel means no gate, not a
            # muted chat.
            logger.warning(
                "subscription.check_failed",
                channel_id=channel_id,
                user_id=tg_user_id,
                error=str(exc),
            )
            return True
        return bool(member.status in SUBSCRIBED_STATUSES)

    async def forget(self, chat_id: int, tg_user_id: int) -> None:
        """Drop a cached verdict — after the user presses "I joined"."""
        await cache.cache.delete(cache.subscription_key(chat_id, tg_user_id))


subscription = SubscriptionService()

__all__ = [
    "NEGATIVE_TTL",
    "SUBSCRIBED_STATUSES",
    "MemberFetcher",
    "SubscriptionService",
    "subscription",
]

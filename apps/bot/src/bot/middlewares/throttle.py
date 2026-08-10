"""Inbound throttle: the platform's own guard against pathological load.

DECISION: this is not anti-flood. Anti-flood is a moderation rule an admin tunes
and it *punishes* the sender; this is a hard ceiling that protects the bot process
from spending Postgres queries and Bot API calls on a user hammering it. The limit
sits deliberately far above any sane anti-flood setting, so a chat's own rules
always trip first and the user gets told why.

DECISION: a throttled update is dropped silently. Replying "you are too fast"
costs a send per dropped message, which is exactly the load being shed, and
Telegram would rate-limit the replies anyway.

DECISION: the window is shared with anti-flood's `RedisSlidingWindow` rather than
reimplemented, so both counters have the same atomicity and the same self-expiring
keys.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from core.anti_flood import RedisSlidingWindow
from shared.logging import get_logger

logger = get_logger(__name__)

# 30 updates in 5 seconds from one user in one chat. No human types that fast;
# anti-flood's default (8 in 10s) trips long before this does.
LIMIT: Final = 30
WINDOW: Final = timedelta(seconds=5)


class ThrottleMiddleware(BaseMiddleware):
    """Drops updates from a single author once they exceed the hard ceiling."""

    def __init__(self, window: RedisSlidingWindow | None = None) -> None:
        self._window = window or RedisSlidingWindow()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)

        key = f"throttle:{event.chat.id}:{event.from_user.id}"
        try:
            count = await self._window.hit(key, window=WINDOW)
        except Exception:
            # DECISION: fail open, like dedup. Redis being unavailable must not
            # stop the bot from moderating.
            logger.debug("throttle.redis_unavailable", user_id=event.from_user.id)
            return await handler(event, data)

        if count > LIMIT:
            logger.warning(
                "throttle.dropped",
                chat_id=event.chat.id,
                user_id=event.from_user.id,
                count=count,
                limit=LIMIT,
            )
            return None
        return await handler(event, data)


__all__ = ["LIMIT", "WINDOW", "ThrottleMiddleware"]

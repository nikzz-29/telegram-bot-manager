"""Update deduplication.

DECISION: Redis, not an in-process set. Telegram redelivers an update when a
webhook reply is slow, and two bot replicas can be handed the same update during
a rolling deploy. A user banned twice is noise; a user *warned* twice from one
message is wrong.

DECISION: the key TTL is an hour. Telegram gives up redelivering long before
that, and one small key per update is cheap next to processing it twice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from core.redis_client import get_redis
from shared.logging import get_logger

logger = get_logger(__name__)

KEY_PREFIX: Final = "tgm:update"
TTL_SECONDS: Final = 3600


class DedupMiddleware(BaseMiddleware):
    """Drops an update whose `update_id` this platform has already handled."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        try:
            first = await get_redis().set(
                f"{KEY_PREFIX}:{event.update_id}", b"1", nx=True, ex=TTL_SECONDS
            )
        except Exception:
            # DECISION: fail open. Redis being down must not stop the bot from
            # moderating; a duplicate is the lesser failure of the two.
            logger.exception("dedup.redis_unavailable", update_id=event.update_id)
            return await handler(event, data)

        if not first:
            logger.debug("dedup.duplicate_dropped", update_id=event.update_id)
            return None
        return await handler(event, data)


__all__ = ["DedupMiddleware"]

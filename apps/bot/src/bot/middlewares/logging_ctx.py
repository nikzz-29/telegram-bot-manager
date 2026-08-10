"""Per-update structlog context.

Binds `update_id`, `chat_id` and `user_id` into contextvars so every log line
emitted downstream carries them without being passed the values. The context is
cleared in a `finally`, because contextvars survive on the task that aiogram
reuses for the next update.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from shared.logging import bind_update_context, clear_update_context


def _subject(update: Update) -> tuple[int | None, int | None]:
    """The chat and user this update is about, whatever kind of update it is."""
    event = update.event
    chat = getattr(event, "chat", None)
    user = getattr(event, "from_user", None)
    if chat is None:
        message = getattr(event, "message", None)
        chat = getattr(message, "chat", None)
    return (
        getattr(chat, "id", None),
        getattr(user, "id", None),
    )


class LoggingContextMiddleware(BaseMiddleware):
    """Binds update identity into structlog contextvars for the whole update."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        chat_id, user_id = _subject(event)
        bind_update_context(
            update_id=event.update_id,
            chat_id=chat_id,
            user_id=user_id,
            event_type=event.event_type,
        )
        try:
            return await handler(event, data)
        finally:
            clear_update_context()


__all__ = ["LoggingContextMiddleware"]

"""Resolve the tenant once per update.

Every handler downstream reads `data["ctx"]` and answers "is this chat on Pro?",
"is anti-flood on?", "what language do I reply in?" with no awaits of its own.

DECISION: private chats get no `ChatContext`. A DM is not a tenant — it has no
plan, no modules and no settings — so `data["ctx"]` stays `None` there and the
`/start` handler falls back to the user's own Telegram locale.

DECISION: the author's profile row is refreshed at most once an hour per user,
gated by a Redis marker. `find_by_username` is what lets `/ban @name` work
without a reply, so the mirror has to exist; paying a DB write for every message
to maintain it would not be worth it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Final

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Chat, Message, TelegramObject, Update, User

from core.context import chat_context
from core.redis_client import get_redis
from db.uow import UnitOfWork
from shared.logging import bind_contextvars, get_logger

logger = get_logger(__name__)

GROUP_TYPES: Final = frozenset({ChatType.GROUP, ChatType.SUPERGROUP})

SEEN_PREFIX: Final = "tgm:seen:user"
SEEN_TTL_SECONDS: Final = 3600


def _chat_and_user(update: Update) -> tuple[Chat | None, User | None]:
    """The chat and author of whatever kind of update this is."""
    event = update.event
    chat = getattr(event, "chat", None)
    if chat is None:
        message = getattr(event, "message", None)
        chat = getattr(message, "chat", None)
    return chat, getattr(event, "from_user", None)


def _migration_ids(update: Update) -> tuple[int, int] | None:
    """Return the old/new Telegram ids carried by a migration service message."""
    event = update.event
    if not isinstance(event, Message):
        return None
    if event.migrate_to_chat_id is not None:
        return event.chat.id, event.migrate_to_chat_id
    if event.migrate_from_chat_id is not None:
        return event.migrate_from_chat_id, event.chat.id
    return None


async def _first_sight(tg_user_id: int) -> bool:
    """True when this user's profile has not been mirrored in the last hour."""
    try:
        return bool(
            await get_redis().set(f"{SEEN_PREFIX}:{tg_user_id}", b"1", nx=True, ex=SEEN_TTL_SECONDS)
        )
    except Exception:
        # Redis down: skip the refresh rather than hammer Postgres per message.
        logger.debug("chat_context.seen_marker_unavailable", user_id=tg_user_id)
        return False


class ChatContextMiddleware(BaseMiddleware):
    """Injects `ctx` (ChatContext | None) and mirrors the author's profile."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        chat, user = _chat_and_user(event)
        if user is not None and not user.is_bot and await _first_sight(user.id):
            async with UnitOfWork() as uow:
                await uow.users.upsert(
                    tg_user_id=user.id,
                    username=user.username,
                    first_name=user.first_name or "",
                    last_name=user.last_name,
                    language_code=user.language_code,
                    is_bot=user.is_bot,
                )
                await uow.commit()

        if chat is None or chat.type not in GROUP_TYPES:
            data["ctx"] = None
            return await handler(event, data)

        migration = _migration_ids(event)
        resolved_tg_chat_id = migration[1] if migration is not None else chat.id
        previous_tg_chat_id = migration[0] if migration is not None else None
        resolved_chat_type = ChatType.SUPERGROUP if migration is not None else chat.type
        ctx = await chat_context.resolve(
            resolved_tg_chat_id,
            title=chat.title or "",
            chat_type=resolved_chat_type,
            # The author of the first message we happen to receive is not
            # necessarily the chat owner.  The lifecycle handler mirrors the
            # authoritative creator returned by getChatAdministrators.
            owner_tg_id=None,
            previous_tg_chat_id=previous_tg_chat_id,
        )
        data["ctx"] = ctx
        bind_contextvars(**ctx.log_fields())

        if not ctx.is_active and event.my_chat_member is None:
            # The bot was removed from this chat, or the chat was disabled from the
            # panel. Stay silent rather than moderate a chat nobody manages.  A
            # my_chat_member update is the exception: it is how a re-added or
            # promoted bot reactivates the chat.
            logger.debug("chat_context.inactive_chat", chat_id=ctx.chat_id)
            return None

        return await handler(event, data)


__all__ = ["ChatContextMiddleware", "_migration_ids"]

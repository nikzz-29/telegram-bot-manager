"""Everything the bot says, in one place.

DECISION: handlers never call `message.answer()`. Every outbound call goes
through `MessageSender`, which is what enforces the ~30 msg/s global and
~20 msg/min per-group ceilings and handles `TelegramRetryAfter`. A direct
`answer()` bypasses all of it and is exactly what earns a chat-wide 429.

DECISION: automatic notices delete themselves after `NOTICE_TTL`; answers to a
command an admin typed do not. A busy group would otherwise accumulate a line per
deletion, while a moderator who asked a question deserves to keep the answer.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup, Message

from core import jobs
from core.context import ChatContext
from core.jobs import JobName, job_id
from core.sender import SendPriority, sender

# How long an automatic notice stays in the chat before it removes itself.
NOTICE_TTL: Final = timedelta(seconds=30)


async def _schedule_removal(tg_chat_id: int, message_id: int, after: timedelta) -> None:
    await jobs.schedule_in(
        JobName.DELETE_MESSAGE,
        after,
        tg_chat_id,
        message_id,
        _id=job_id(JobName.DELETE_MESSAGE, tg_chat_id, message_id),
    )


async def send(
    tg_chat_id: int,
    text: str,
    *,
    reply_to: int | None = None,
    priority: SendPriority = SendPriority.REPLY,
    ttl: timedelta | None = None,
    silent: bool = True,
    keyboard: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Queue one message; optionally schedule its own deletion.

    Returns the sent `Message` when a TTL was requested (the id is needed to
    delete it) and `None` otherwise — a fire-and-forget send never waits.
    """
    method = SendMessage(
        chat_id=tg_chat_id,
        text=text,
        disable_notification=silent,
        reply_to_message_id=reply_to,
        allow_sending_without_reply=True,
        reply_markup=keyboard,
    )
    if ttl is None:
        sender.enqueue(method, chat_id=tg_chat_id, priority=priority)
        return None

    sent: Message | None = await sender.call(method, chat_id=tg_chat_id, priority=priority)
    if sent is not None:
        await _schedule_removal(tg_chat_id, sent.message_id, ttl)
    return sent


async def notify(ctx: ChatContext, text: str, *, ephemeral: bool = True) -> None:
    """An automatic rule explaining itself to the chat."""
    await send(
        ctx.tg_chat_id,
        text,
        priority=SendPriority.MODERATION,
        ttl=NOTICE_TTL if ephemeral else None,
    )


async def answer(message: Message, text: str, *, ttl: timedelta | None = None) -> None:
    """A reply to a command someone typed, threaded onto it."""
    await send(
        message.chat.id,
        text,
        reply_to=message.message_id,
        priority=SendPriority.REPLY,
        ttl=ttl,
    )


__all__ = ["NOTICE_TTL", "answer", "notify", "send"]

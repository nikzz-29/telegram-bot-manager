"""Autoposting: firing a scheduled post and re-arming it for next time.

Spec §5.6. The schedule itself is arithmetic and lives in `core.autopost`; this
module is what turns a fire time into a message, a pin, and the next fire time.
"""

from __future__ import annotations

from typing import Any, Final

from aiogram.methods import DeleteMessage, PinChatMessage, SendMessage, SendPhoto
from aiogram.types import Message

from core.autopost import arm, next_run
from core.context import chat_context
from core.keyboards import inline_url_keyboard
from core.sender import SendPriority, sender
from db.models import ScheduledPost
from db.uow import UnitOfWork
from shared.enums import ModuleName
from shared.logging import get_logger
from shared.plans import Feature
from shared.schemas.module_configs import AutopostConfig
from shared.time_utils import utc_now
from worker.registry import job, scheduled

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]

# Telegram's caption ceiling. A longer post is sent as text with the media
# dropped rather than truncated into nonsense.
MAX_CAPTION: Final = 1_024

# How many overdue posts one sweep will fire.
SWEEP_LIMIT: Final = 200


def _build(post: ScheduledPost, tg_chat_id: int) -> SendMessage | SendPhoto:
    """The send call for one post: photo with caption, or plain text."""
    keyboard = inline_url_keyboard(post.buttons)
    if post.media_file_id and len(post.content) <= MAX_CAPTION:
        return SendPhoto(
            chat_id=tg_chat_id,
            photo=post.media_file_id,
            caption=post.content or None,
            reply_markup=keyboard,
            disable_notification=True,
        )
    return SendMessage(
        chat_id=tg_chat_id,
        text=post.content,
        reply_markup=keyboard,
        disable_notification=True,
        link_preview_options=None,
    )


@job
async def run_scheduled_post(ctx: WorkerContext, post_id: int) -> bool:
    """Publish one scheduled post, then re-arm it.

    DECISION: the row is re-read and re-validated on every fire. A post can be
    paused, edited, deleted or its chat downgraded between the moment it was
    armed and the moment this runs — the schedule is a hint, the row is the
    truth. This is also what makes a duplicate fire (Redis restored from a
    snapshot, the sweep racing the queue) safe: the second run sees an already
    advanced `next_run_at` and stops.

    DECISION: the previous copy is deleted *after* the new one is sent, not
    before. If the send fails, the chat keeps the old post instead of losing
    both.
    """
    async with UnitOfWork() as uow:
        post = await uow.posts.get_by_id(post_id)
        if post is None:
            logger.info("job.run_scheduled_post.gone", post_id=post_id)
            return False
        if not post.enabled:
            logger.debug("job.run_scheduled_post.paused", post_id=post_id)
            return False
        chat = await uow.chats.get_by_id(post.chat_id)
        if chat is None or not chat.is_active:
            logger.warning("job.run_scheduled_post.inactive_chat", post_id=post_id)
            return False
        chat_id = post.chat_id
        tg_chat_id = chat.tg_chat_id
        previous_message_id = post.last_message_id
        # Detached copies of what the send needs: the session closes below.
        schedule_kind, schedule_value = post.schedule_kind, post.schedule_value
        pin, delete_previous = post.pin, post.delete_previous
        target_chat_id = post.target_chat_id
        method = _build(post, target_chat_id or tg_chat_id)

    context = await chat_context.for_chat_id(chat_id, tg_chat_id=tg_chat_id)
    if not context.has(Feature.AUTOPOST) or not context.module_enabled(ModuleName.AUTOPOST):
        # Downgraded or switched off since the post was armed. Left enabled in
        # the database on purpose: re-subscribing should bring the schedule back
        # without the owner having to recreate every post.
        logger.info("job.run_scheduled_post.locked", post_id=post_id, plan=context.plan.value)
        return False

    config = await chat_context.config(context, ModuleName.AUTOPOST, AutopostConfig)
    if not config.enabled:
        logger.debug("job.run_scheduled_post.module_paused", post_id=post_id)
        return False
    timezone = config.timezone or context.timezone
    destination = target_chat_id or tg_chat_id

    sent: Message | None = await sender.call(
        method, chat_id=destination, priority=SendPriority.BROADCAST
    )
    if sent is None:
        # The sender exhausted its retries (chat gone, bot kicked, media dead).
        # Re-arming anyway is deliberate: a recurring post should resume once the
        # chat is back, and `mark_ran` records that this occurrence was consumed.
        logger.warning("job.run_scheduled_post.send_failed", post_id=post_id, chat_id=chat_id)

    if sent is not None and delete_previous and previous_message_id:
        sender.enqueue(
            DeleteMessage(chat_id=destination, message_id=previous_message_id),
            chat_id=destination,
            priority=SendPriority.SYSTEM,
        )
    if sent is not None and pin:
        sender.enqueue(
            PinChatMessage(
                chat_id=destination, message_id=sent.message_id, disable_notification=True
            ),
            chat_id=destination,
            priority=SendPriority.SYSTEM,
        )

    upcoming = next_run(schedule_kind, schedule_value, timezone=timezone, after=utc_now())
    async with UnitOfWork() as uow:
        await uow.posts.mark_ran(
            post_id,
            message_id=sent.message_id if sent is not None else previous_message_id,
            next_run_at=upcoming,
        )
        if upcoming is None:
            # A one-shot that has fired never fires again; retiring it here is
            # what keeps it out of the due sweep forever.
            await uow.posts.update(chat_id, post_id, enabled=False)
        await uow.commit()

    await arm(post_id, upcoming)
    logger.info(
        "job.run_scheduled_post.done",
        post_id=post_id,
        chat_id=chat_id,
        message_id=sent.message_id if sent is not None else None,
        next_run_at=upcoming.isoformat() if upcoming else None,
    )
    return sent is not None


@scheduled(minute={1, 16, 31, 46})
async def sweep_due_posts(ctx: WorkerContext) -> int:
    """Fire posts whose time has passed — the safety net for a lost queue.

    Same reasoning as `sweep_expired_punishments`: ARQ's Redis queue is the only
    record of an armed post, so a flush or a restore from an old snapshot would
    silently stop every schedule on the platform. The partial index on
    `(next_run_at) WHERE enabled = true` makes the query cheap, and the
    deterministic job id means racing the real queue is a no-op.
    """
    async with UnitOfWork() as uow:
        due = await uow.posts.list_due(now=utc_now(), limit=SWEEP_LIMIT)
    if not due:
        return 0

    fired = 0
    for post in due:
        try:
            if await run_scheduled_post(ctx, post.id):
                fired += 1
        except Exception:
            logger.exception("job.sweep_due_posts.failed", post_id=post.id)
    if fired:
        logger.warning("job.sweep_due_posts", fired=fired, due=len(due))
    return fired


__all__ = ["MAX_CAPTION", "SWEEP_LIMIT", "run_scheduled_post", "sweep_due_posts"]

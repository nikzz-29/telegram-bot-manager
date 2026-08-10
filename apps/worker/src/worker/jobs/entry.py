"""Deferred entry work: captcha timeouts and lockdowns that end on their own.

DECISION: the captcha timeout is a job, never a sleeping task (spec §4.4). A
`asyncio.sleep` would die with the process and leave the user muted forever;
an ARQ job with an explicit `_job_id` survives a restart and can be cancelled
by id the moment the challenge is solved.
"""

from __future__ import annotations

from typing import Any

from aiogram.methods import SendMessage

from core import actions
from core.audit import audit
from core.captcha import captcha
from core.context import chat_context
from core.entry import anti_raid
from core.sender import SendPriority, sender
from db.uow import UnitOfWork
from i18n.runtime import translator
from shared.enums import StatEventType
from shared.logging import get_logger
from shared.time_utils import utc_now
from worker.registry import job, scheduled

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]


@job
async def captcha_timeout(ctx: WorkerContext, tg_chat_id: int, tg_user_id: int) -> bool:
    """The challenge ran out of time: kick, or leave them muted.

    DECISION: re-reads the row instead of trusting the schedule. A challenge
    solved a second before this fires has already been marked, and the correct
    action then is nothing at all.
    """
    async with UnitOfWork() as uow:
        chat = await uow.chats.get_by_tg_id(tg_chat_id)
        if chat is None:
            logger.warning("job.captcha_timeout.unknown_chat", tg_chat_id=tg_chat_id)
            return False
        pending = await uow.captcha.get_pending(chat.id, tg_user_id)
        if pending is None:
            logger.debug("job.captcha_timeout.already_settled", chat_id=chat.id, user_id=tg_user_id)
            return False
        message_id = pending.message_id
        await uow.captcha.delete(chat.id, tg_user_id)
        await uow.stats.add_event(
            chat_id=chat.id, event_type=StatEventType.CAPTCHA_FAILED, tg_user_id=tg_user_id
        )
        await uow.commit()

    await captcha.unmark(chat.id, tg_user_id)
    context = await chat_context.for_chat_id(chat.id, tg_chat_id=tg_chat_id)

    if message_id is not None:
        sender.enqueue(
            actions.delete_message(tg_chat_id, message_id),
            chat_id=tg_chat_id,
            priority=SendPriority.SYSTEM,
        )

    if context.entry.captcha_kick_on_timeout:
        # Kick, not ban: they can come back and try again. A ban over an unsolved
        # captcha turns a slow phone into a permanent exclusion.
        for method in actions.kick(tg_chat_id, tg_user_id):
            sender.enqueue(method, chat_id=tg_chat_id, priority=SendPriority.MODERATION)

    await audit.report(
        log_channel_id=context.moderation.log_channel_id,
        locale=context.language,
        action="captcha_timeout",
        target_id=tg_user_id,
        note="kicked" if context.entry.captcha_kick_on_timeout else "muted",
    )
    logger.info(
        "job.captcha_timeout.done",
        chat_id=chat.id,
        user_id=tg_user_id,
        kicked=context.entry.captcha_kick_on_timeout,
    )
    return True


@job
async def end_lockdown(ctx: WorkerContext, tg_chat_id: int) -> bool:
    """Clear an anti-raid lockdown once its window has passed.

    Members held during it keep their own `until_date` and are released by
    Telegram; see the `_hold` decision in `bot.modules.entry`.
    """
    async with UnitOfWork() as uow:
        chat = await uow.chats.get_by_tg_id(tg_chat_id)
    if chat is None:
        logger.warning("job.end_lockdown.unknown_chat", tg_chat_id=tg_chat_id)
        return False

    await anti_raid.end_lockdown(chat.id, tg_chat_id)
    context = await chat_context.for_chat_id(chat.id, tg_chat_id=tg_chat_id)
    sender.enqueue(
        SendMessage(
            chat_id=tg_chat_id,
            text=translator(context.language)("lockdown-over"),
            disable_notification=True,
        ),
        chat_id=tg_chat_id,
        priority=SendPriority.MODERATION,
    )
    await audit.report(
        log_channel_id=context.moderation.log_channel_id,
        locale=context.language,
        action="lockdown_off",
        note="expired",
    )
    logger.info("job.end_lockdown.done", chat_id=chat.id)
    return True


@scheduled(minute={8, 23, 38, 53})
async def sweep_expired_captchas(ctx: WorkerContext) -> int:
    """Safety net, same reasoning as `sweep_expired_punishments`.

    ARQ's queue is the only record of a pending timeout, so a flushed Redis would
    otherwise leave newcomers muted with nobody coming to release them. The
    partial index on `(expires_at) WHERE solved_at IS NULL` makes this cheap.
    """
    async with UnitOfWork() as uow:
        expired = await uow.captcha.list_expired(now=utc_now())
        if not expired:
            return 0
        chats = {
            chat_id: await uow.chats.get_by_id(chat_id)
            for chat_id in {challenge.chat_id for challenge in expired}
        }

    settled = 0
    for challenge in expired:
        chat = chats.get(challenge.chat_id)
        if chat is None:
            continue
        if await captcha_timeout(ctx, chat.tg_chat_id, challenge.tg_user_id):
            settled += 1
    if settled:
        logger.warning("job.sweep_expired_captchas", settled=settled, found=len(expired))
    return settled


__all__ = ["captcha_timeout", "end_lockdown", "sweep_expired_captchas"]

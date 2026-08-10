"""Deferred moderation work: restrictions that expire on their own.

DECISION: the job takes Telegram ids, not row ids. A punishment row can be
superseded between scheduling and firing, and re-reading the *current* active
punishment for that user is what keeps the lift honest — the job asks "is this
still in force?" rather than trusting a snapshot taken hours earlier.
"""

from __future__ import annotations

from typing import Any

from aiogram.methods import SendMessage

from core import actions
from core.anti_flood import anti_flood
from core.audit import audit
from core.context import chat_context
from core.sender import SendPriority, sender
from db.uow import UnitOfWork
from i18n.runtime import translator
from shared.enums import PunishmentType
from shared.logging import get_logger
from shared.time_utils import utc_now
from worker.registry import job, scheduled

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]


async def _lift(tg_chat_id: int, tg_user_id: int, punishment_type: PunishmentType) -> bool:
    """Undo one restriction in Telegram and close its row. Idempotent."""
    async with UnitOfWork() as uow:
        chat = await uow.chats.get_by_tg_id(tg_chat_id)
        if chat is None:
            logger.warning("job.lift_restriction.unknown_chat", tg_chat_id=tg_chat_id)
            return False
        chat_id = chat.id
        active = await uow.punishments.get_active(chat_id, tg_user_id, punishment_type)
        if active is None:
            # Already lifted by an admin: the cancel raced us, nothing to do.
            logger.debug(
                "job.lift_restriction.already_lifted",
                chat_id=chat_id,
                user_id=tg_user_id,
                type=punishment_type.value,
            )
            return False
        await uow.punishments.deactivate(active.id)
        await uow.moderation_logs.add(
            chat_id=chat_id,
            action=f"auto_un{punishment_type.value}",
            tg_user_id=tg_user_id,
            moderator_tg_id=None,
            reason="expired",
        )
        await uow.commit()

    method = (
        actions.unmute(tg_chat_id, tg_user_id)
        if punishment_type == PunishmentType.MUTE
        else actions.unban(tg_chat_id, tg_user_id)
    )
    sender.enqueue(method, chat_id=tg_chat_id, priority=SendPriority.MODERATION)
    if punishment_type == PunishmentType.MUTE:
        # The window that earned the mute is stale by now; keep it from firing again.
        await anti_flood.reset(chat_id, tg_user_id)

    ctx = await chat_context.for_chat_id(chat_id, tg_chat_id=tg_chat_id)
    await audit.report(
        log_channel_id=ctx.moderation.log_channel_id,
        locale=ctx.language,
        action=f"un{punishment_type.value}",
        target_id=tg_user_id,
        note="expired",
    )
    logger.info(
        "job.lift_restriction.done",
        chat_id=chat_id,
        user_id=tg_user_id,
        type=punishment_type.value,
    )
    return True


@job
async def lift_restriction(
    ctx: WorkerContext, tg_chat_id: int, tg_user_id: int, punishment_type: str
) -> bool:
    """Fired at the punishment's expiry: unmute or unban the user."""
    return await _lift(tg_chat_id, tg_user_id, PunishmentType(punishment_type))


@job
async def delete_message(ctx: WorkerContext, tg_chat_id: int, message_id: int) -> bool:
    """Remove a self-deleting notice once its TTL is up.

    DECISION: failures here are swallowed by the sender and never retried. The
    message was already deleted by an admin, or the bot lost the right to delete
    it — neither is worth a job that keeps coming back.
    """
    sender.enqueue(
        actions.delete_message(tg_chat_id, message_id),
        chat_id=tg_chat_id,
        priority=SendPriority.SYSTEM,
    )
    return True


@job
async def end_read_only(ctx: WorkerContext, tg_chat_id: int) -> bool:
    """Reopen a chat that `/ro <duration>` closed."""
    sender.enqueue(
        actions.set_read_only(tg_chat_id, enabled=False),
        chat_id=tg_chat_id,
        priority=SendPriority.MODERATION,
    )
    async with UnitOfWork() as uow:
        chat = await uow.chats.get_by_tg_id(tg_chat_id)
    if chat is None:
        logger.warning("job.end_read_only.unknown_chat", tg_chat_id=tg_chat_id)
        return False

    context = await chat_context.for_chat_id(chat.id, tg_chat_id=tg_chat_id)
    sender.enqueue(
        SendMessage(
            chat_id=tg_chat_id,
            text=translator(context.language)("read-only-off"),
            disable_notification=True,
        ),
        chat_id=tg_chat_id,
        priority=SendPriority.MODERATION,
    )
    await audit.report(
        log_channel_id=context.moderation.log_channel_id,
        locale=context.language,
        action="read_only",
        note="expired",
    )
    logger.info("job.end_read_only.done", chat_id=chat.id)
    return True


@scheduled(minute={3, 18, 33, 48})
async def sweep_expired_punishments(ctx: WorkerContext) -> int:
    """Safety net for jobs Redis lost.

    DECISION: this exists because ARQ's queue is the only record of a pending
    lift. A `FLUSHALL`, an evicted key or a Redis restore from an old snapshot
    would otherwise leave a user muted forever with no way to notice. The sweep
    is cheap — one indexed query every fifteen minutes — and it can only ever
    lift restrictions that are already past their expiry.
    """
    async with UnitOfWork() as uow:
        expired = await uow.punishments.list_expired(now=utc_now())
        if not expired:
            return 0
        chat_ids = {punishment.chat_id for punishment in expired}
        chats = {chat_id: await uow.chats.get_by_id(chat_id) for chat_id in chat_ids}

    lifted = 0
    for punishment in expired:
        chat = chats.get(punishment.chat_id)
        if chat is None:
            continue
        if await _lift(chat.tg_chat_id, punishment.tg_user_id, punishment.type):
            lifted += 1
    if lifted:
        logger.warning("job.sweep_expired_punishments", lifted=lifted, found=len(expired))
    return lifted


__all__ = [
    "delete_message",
    "end_read_only",
    "lift_restriction",
    "sweep_expired_punishments",
]

"""Platform-level background work: the ban network and AI-log retention.

Spec §5.5 and §5.6. Neither job belongs to a chat — one fans a blacklist entry
out across every chat that opted into the network, the other applies retention to
the AI audit log for all of them at once.

DECISION: propagation is a job, not part of `crossban.promote`. Promotion happens
inside a request or a command and has to answer quickly; banning the user in
however many chats have the network on is unbounded work that the sender will
rate-limit anyway. The blacklist is authoritative the moment it is written — the
gate reads it on the user's next message regardless of whether this job has run.

DECISION: propagation bans, but never *unbans*. Revoking a global ban lifts the
network's judgement, not each chat's own: a chat that banned this user itself
still means it, and quietly restoring them everywhere would overrule moderators
who never asked the network for an opinion.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from core import actions
from core.crossban import crossban
from core.sender import SendPriority, sender
from db.uow import UnitOfWork
from shared.enums import ModuleName
from shared.logging import get_logger
from shared.schemas.module_configs import CrossbanConfig
from shared.time_utils import utc_now
from worker.registry import job, scheduled

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]

# The AI log is an audit trail, not a data set. Long enough to answer "why was my
# message deleted last week", short enough that it never becomes the biggest
# table in the database.
AI_LOG_RETENTION: Final = timedelta(days=30)


@job
async def propagate_global_ban(ctx: WorkerContext, tg_user_id: int, reason: str = "") -> int:
    """Ban a freshly blacklisted user in every chat that asked for it.

    Returns how many chats were acted on. Chats in alert-only mode are skipped
    here on purpose: they asked to be told, and they are told by the join handler
    if the user ever shows up.
    """
    async with UnitOfWork() as uow:
        chat_ids = await uow.module_configs.list_enabled_chats(ModuleName.CROSSBAN.value)
        if not chat_ids:
            return 0
        chats = await uow.chats.list_by_ids(chat_ids)
        configs = await uow.module_configs.get_many(chat_ids, ModuleName.CROSSBAN.value)

    acted = 0
    for chat in chats:
        if not chat.is_active:
            continue
        row = configs.get(chat.id)
        config = CrossbanConfig.model_validate(row.config if row is not None else {})
        if crossban.enforcement_for(config) != "ban":
            continue
        sender.enqueue(
            actions.ban(chat.tg_chat_id, tg_user_id),
            chat_id=chat.tg_chat_id,
            priority=SendPriority.MODERATION,
        )
        acted += 1

    logger.info(
        "job.propagate_global_ban",
        tg_user_id=tg_user_id,
        chats=acted,
        candidates=len(chat_ids),
        reason=reason,
    )
    return acted


@scheduled(hour={4}, minute={33})
async def prune_ai_logs(ctx: WorkerContext) -> int:
    """Drop AI verdicts older than the retention window, in one statement.

    Runs at the same quiet hour as the stats prune but on a different minute, so
    two bulk deletes never contend for the same autovacuum window.
    """
    before = utc_now() - AI_LOG_RETENTION
    async with UnitOfWork() as uow:
        removed = await uow.ai_logs.prune(before=before)
        await uow.commit()
    if removed:
        logger.info("job.prune_ai_logs", removed=removed, before=before.isoformat())
    return removed


__all__ = ["AI_LOG_RETENTION", "propagate_global_ban", "prune_ai_logs"]

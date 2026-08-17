"""Statistics pipeline jobs: buffer flush, rollups, digests, retention.

The write path is staged by design (see `core.stats`): handlers RPUSH events into
Redis and these jobs are what turns them into rows, rollups and a readable
digest. Every job here re-reads state rather than trusting its schedule, the same
reasoning as the moderation sweeps.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.methods import SendMessage

from core import cache, reports
from core.context import chat_context
from core.features import effective_plan
from core.redis_client import get_redis
from core.sender import SendPriority, sender
from core.stats import stats
from db.uow import UnitOfWork
from i18n.runtime import translator
from shared.config import get_settings
from shared.enums import ModuleName
from shared.logging import get_logger
from shared.plans import limits_for_plan
from shared.schemas.module_configs import StatsConfig
from shared.time_utils import utc_now
from worker.registry import scheduled

logger = get_logger(__name__)

WorkerContext = dict[Any, Any]

# One digest per chat per day. The marker is what makes a retried run, or a
# worker restarted mid-fan-out, harmless; it expires on its own.
REPORT_MARKER_KEY: Final = "tgm:stats:report:{chat_id}:{kind}:{day}"
REPORT_MARKER_TTL: Final = timedelta(days=3)

# Ceiling on one flush run: enough to clear a busy quarter-hour, low enough that
# a wedged buffer cannot hold the worker's only slot for minutes.
MAX_FLUSH_BATCHES: Final = 40

# Chats scanned per prune pass. Retention grouping needs the plan of every chat,
# and one page of ten thousand rows is a few milliseconds.
PRUNE_PAGE: Final = 10_000


def _marker_key(chat_id: int, kind: str, day: date) -> str:
    return REPORT_MARKER_KEY.format(chat_id=chat_id, kind=kind, day=day.isoformat())


def _report_windows(
    config: StatsConfig, *, now: datetime | None = None
) -> tuple[tuple[str, int, date], ...]:
    """Reports due now as ``(kind, days, end_date)`` in the chat timezone."""
    moment = now or utc_now()
    try:
        local_now = moment.astimezone(ZoneInfo(config.timezone or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        local_now = moment.astimezone(ZoneInfo("UTC"))
    if local_now.hour != config.report_hour_utc:
        return ()

    completed_day = local_now.date() - timedelta(days=1)
    due: list[tuple[str, int, date]] = []
    if config.daily_report_enabled:
        due.append(("daily", 1, completed_day))
    if config.weekly_report_enabled and local_now.weekday() == 0:
        due.append(("weekly", 7, completed_day))
    return tuple(due)


@scheduled(minute={5, 20, 35, 50})
async def flush_stat_events(ctx: WorkerContext) -> int:
    """Move buffered activity into Postgres, batch by batch.

    DECISION: the run drains repeatedly instead of once. A quarter-hour of a busy
    platform is many multiples of `stats_flush_batch`, and leaving the remainder
    for the next cron would let the buffer grow monotonically. `MAX_FLUSH_BATCHES`
    is the other half of that decision — the loop always ends, so a buffer being
    filled faster than it drains produces a backlog warning rather than a job
    that never returns.
    """
    batch_size = get_settings().stats_flush_batch
    total = 0
    for _ in range(MAX_FLUSH_BATCHES):
        written = await stats.flush()
        total += written
        if written < batch_size:
            break

    pending = await stats.pending()
    if pending:
        # Either a flood, or a batch size too small for this platform's rate.
        # Both are worth seeing in the logs before the buffer hits `MAX_BUFFER`.
        logger.warning("job.flush_stat_events.backlog", pending=pending, flushed=total)
    elif total:
        logger.debug("job.flush_stat_events", flushed=total)
    return total


@scheduled(minute={10, 25, 40, 55})
async def aggregate_daily_stats(ctx: WorkerContext) -> int:
    """Roll raw events into `stat_daily` for every chat that produced some.

    DECISION: the fan-out comes from `chats_with_events(day=...)` rather than
    from the chats with the statistics module enabled. Joins and moderation
    actions are recorded regardless of that switch, and the Mini App chart reads
    the rollups either way — rolling up whatever has data keeps the two
    consistent and needs no per-chat config read.

    DECISION: just after midnight the previous day is rolled up again. The last
    run of a day fires at :55, so the final five minutes of events would
    otherwise never reach a rollup, and the daily digest reads exactly that day.
    """
    today = utc_now().date()
    days = [today]
    if utc_now().hour == 0:
        days.append(today - timedelta(days=1))

    aggregated = 0
    for day in days:
        async with UnitOfWork() as uow:
            chat_ids = await uow.stats.chats_with_events(day=day)
        for chat_id in chat_ids:
            try:
                await stats.rollup(chat_id, day=day)
                aggregated += 1
            except Exception:
                logger.exception("job.aggregate_daily_stats.failed", chat_id=chat_id, day=str(day))
    if aggregated:
        logger.info("job.aggregate_daily_stats.done", rollups=aggregated, days=len(days))
    return aggregated


async def _send_digest(chat_id: int, tg_chat_id: int) -> int:
    """Render and queue every daily/weekly digest due for one chat now."""
    context = await chat_context.for_chat_id(chat_id, tg_chat_id=tg_chat_id)
    config = await chat_context.config(context, ModuleName.STATS, StatsConfig)
    due = _report_windows(config)
    if not due:
        return 0

    client = get_redis()
    sent = 0
    for kind, days, end in due:
        key = _marker_key(chat_id, kind, end)
        if not await client.set(key, "1", ex=REPORT_MARKER_TTL, nx=True):
            continue
        overview = await stats.overview(chat_id, days=days, end=end)
        text = reports.format_overview(
            overview,
            title=context.title,
            t=translator(context.language),
        )
        sender.enqueue(
            SendMessage(chat_id=tg_chat_id, text=text, disable_notification=True),
            chat_id=tg_chat_id,
            priority=SendPriority.BROADCAST,
        )
        sent += 1
        logger.info(
            "job.send_stats_report.queued",
            chat_id=chat_id,
            kind=kind,
            days=days,
            end=str(end),
        )
    return sent


@scheduled(minute={12, 42})
async def send_daily_report(ctx: WorkerContext) -> int:
    """Send yesterday's digest to chats whose `report_hour_utc` has arrived.

    DECISION: one cron entry covers all 24 possible report hours, with the hour
    compared per chat. Twenty-four hourly variants of the same job would be
    twenty-four places for the same typo, and the fan-out itself is one indexed
    query.

    DECISION: the digest reports the day that is over, not the one in progress.
    A "daily report" arriving at 09:00 with nine hours of numbers reads as a
    broken report; yesterday's rollup is also final, so the digest cannot
    disagree with `/stats` run a minute later.
    """
    async with UnitOfWork() as uow:
        chat_ids = await uow.module_configs.list_enabled_chats(ModuleName.STATS.value)
        chats = {chat_id: await uow.chats.get_by_id(chat_id) for chat_id in chat_ids}

    sent = 0
    for chat_id, chat in chats.items():
        if chat is None or not chat.is_active:
            continue
        try:
            sent += await _send_digest(chat_id, chat.tg_chat_id)
        except Exception:
            # The marker stays: a digest that failed to render will fail again
            # this hour, and a retry storm is worse than a missed digest.
            logger.exception("job.send_daily_report.failed", chat_id=chat_id)
    if sent:
        logger.info("job.send_daily_report.done", sent=sent, considered=len(chat_ids))
    return sent


@scheduled(hour={4}, minute={17})
async def prune_old_stats(ctx: WorkerContext) -> int:
    """Apply retention: one DELETE per distinct window, not per chat.

    DECISION: the window is `max(plan quota, Settings.stats_retention_days)`.
    The plan quota is the promise made to a paying chat; the settings value is
    the platform floor that keeps a free chat's own `/stats` meaningful and
    covers the gap right after a downgrade. Chats are grouped by the resulting
    window, so a platform of thousands of chats prunes in a handful of
    statements.

    DECISION: each window commits separately rather than the whole sweep sharing
    one transaction. A day's worth of rows deletes in seconds, and staying out of
    one long transaction keeps autovacuum's work small.
    """
    floor = get_settings().stats_retention_days
    now = utc_now()

    async with UnitOfWork() as uow:
        chats = await uow.chats.list_all(limit=PRUNE_PAGE)

    by_window: dict[int, list[int]] = {}
    for chat in chats:
        retention = max(limits_for_plan(effective_plan(chat, now=now)).stats_retention_days, floor)
        by_window.setdefault(retention, []).append(chat.id)

    removed = 0
    for retention, chat_ids in by_window.items():
        dropped = await stats.prune(retention_days=retention, chat_ids=chat_ids)
        removed += dropped
        if dropped:
            # A pruned window changes what `/stats` returns, and the overview is
            # cached per chat.
            for chat_id in chat_ids:
                await cache.invalidate_chat(chat_id)
    if removed:
        logger.info("job.prune_old_stats.done", removed=removed, windows=len(by_window))
    return removed


__all__ = [
    "MAX_FLUSH_BATCHES",
    "PRUNE_PAGE",
    "REPORT_MARKER_KEY",
    "REPORT_MARKER_TTL",
    "_report_windows",
    "aggregate_daily_stats",
    "flush_stat_events",
    "prune_old_stats",
    "send_daily_report",
]

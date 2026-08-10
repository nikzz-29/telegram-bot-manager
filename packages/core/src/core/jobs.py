"""ARQ job helpers — the only sanctioned way to defer work.

DECISION: no `asyncio.sleep()` + `create_task()` anywhere in the codebase. A mute
that expires in seven days must survive a deploy, a crash and a scale-down; an
in-process timer survives none of them. Everything time-shifted goes through
ARQ, which persists the job in Redis.

DECISION: every deferred job carries a deterministic `_job_id` built from its
subject (`unmute:{chat_id}:{user_id}`). ARQ treats a duplicate job id as already
queued, which gives idempotency for free: re-muting a user who is already muted
replaces the pending unmute instead of stacking a second one that would lift the
restriction early.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from arq.jobs import Job, JobStatus
import structlog

from shared.config import get_settings

logger = structlog.get_logger(__name__)

QUEUE_NAME: Final = "tgm:jobs"


class JobName(StrEnum):
    """Every deferred task. The value is the worker function's name."""

    # --- moderation ---
    LIFT_RESTRICTION = "lift_restriction"
    EXPIRE_WARN = "expire_warn"
    DELETE_MESSAGE = "delete_message"
    END_READ_ONLY = "end_read_only"
    END_LOCKDOWN = "end_lockdown"
    # --- entry ---
    CAPTCHA_TIMEOUT = "captcha_timeout"
    # --- engagement / autopost ---
    RUN_SCHEDULED_POST = "run_scheduled_post"
    # --- stats ---
    FLUSH_STAT_EVENTS = "flush_stat_events"
    AGGREGATE_DAILY_STATS = "aggregate_daily_stats"
    SEND_DAILY_REPORT = "send_daily_report"
    PRUNE_OLD_STATS = "prune_old_stats"
    # --- billing ---
    EXPIRE_SUBSCRIPTIONS = "expire_subscriptions"
    SEND_RENEWAL_REMINDERS = "send_renewal_reminders"
    APPLY_DOWNGRADE = "apply_downgrade"
    # --- platform ---
    PROPAGATE_GLOBAL_BAN = "propagate_global_ban"


def job_id(name: JobName, *parts: object) -> str:
    """Deterministic job id: re-scheduling the same subject replaces the old job."""
    suffix = ":".join(str(part) for part in parts)
    return f"{name.value}:{suffix}" if suffix else name.value


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


_pool: ArqRedis | None = None


async def get_arq() -> ArqRedis:
    """Process-wide ARQ pool, created on first use."""
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings(), default_queue_name=QUEUE_NAME)
    return _pool


def set_arq(pool: ArqRedis) -> None:
    """Override the pool (tests, and the worker which already owns one)."""
    global _pool
    _pool = pool


async def close_arq() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue(
    name: JobName,
    *args: Any,
    _id: str | None = None,
    _defer_by: timedelta | float | None = None,
    _defer_until: datetime | None = None,
    _expires: timedelta | float | None = None,
    **kwargs: Any,
) -> Job | None:
    """Queue a job. Returns `None` when a job with this id is already pending.

    A `None` return is the normal, expected outcome of double-scheduling — it
    means the deterministic id did its job, not that anything failed.
    """
    pool = await get_arq()
    job = await pool.enqueue_job(
        name.value,
        *args,
        _job_id=_id,
        _queue_name=QUEUE_NAME,
        _defer_by=_defer_by,
        _defer_until=_defer_until,
        _expires=_expires,
        **kwargs,
    )
    if job is None:
        logger.debug("job.already_queued", job=name.value, job_id=_id)
    else:
        logger.debug("job.enqueued", job=name.value, job_id=job.job_id)
    return job


async def schedule_at(
    name: JobName,
    when: datetime,
    *args: Any,
    _id: str | None = None,
    **kwargs: Any,
) -> Job | None:
    """Run a job at an absolute UTC time (restriction expiry, scheduled post)."""
    return await enqueue(name, *args, _id=_id, _defer_until=when, **kwargs)


async def schedule_in(
    name: JobName,
    delay: timedelta,
    *args: Any,
    _id: str | None = None,
    **kwargs: Any,
) -> Job | None:
    """Run a job after a delay (captcha timeout, retry sweep)."""
    return await enqueue(name, *args, _id=_id, _defer_by=delay, **kwargs)


async def cancel(job_ident: str) -> bool:
    """Drop a pending job — the mute was lifted early, the post was deleted.

    DECISION: `abort=False`. Aborting only helps a job already executing, and
    every deferred job here is idempotent anyway; the case that matters is
    removing one that has not started.
    """
    pool = await get_arq()
    job = Job(job_ident, pool, _queue_name=QUEUE_NAME)
    status = await job.status()
    if status in {JobStatus.not_found, JobStatus.complete}:
        return False
    removed = await job.abort(timeout=0.1) if status == JobStatus.in_progress else True
    if status in {JobStatus.deferred, JobStatus.queued}:
        await pool.zrem(QUEUE_NAME, job_ident)
        await pool.delete(f"arq:job:{job_ident}")
    logger.debug("job.cancelled", job_id=job_ident, status=status.value)
    return bool(removed)


async def cancel_many(job_idents: Sequence[str]) -> int:
    cancelled = 0
    for ident in job_idents:
        if await cancel(ident):
            cancelled += 1
    return cancelled


async def is_pending(job_ident: str) -> bool:
    pool = await get_arq()
    status = await Job(job_ident, pool, _queue_name=QUEUE_NAME).status()
    return status in {JobStatus.deferred, JobStatus.queued, JobStatus.in_progress}


async def queue_depth() -> int:
    """Jobs waiting or deferred — the number to alert on."""
    pool = await get_arq()
    return int(await pool.zcard(QUEUE_NAME))


__all__ = [
    "QUEUE_NAME",
    "JobName",
    "cancel",
    "cancel_many",
    "close_arq",
    "enqueue",
    "get_arq",
    "is_pending",
    "job_id",
    "queue_depth",
    "redis_settings",
    "schedule_at",
    "schedule_in",
    "set_arq",
]

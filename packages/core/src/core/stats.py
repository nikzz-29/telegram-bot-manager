"""Activity statistics: buffered ingest, daily rollups, report assembly.

Spec §5.5 wants message/join/leave counts, activity charts and a top-10 board.
The hard part is not the arithmetic, it is the write rate: a busy chat produces
one event per message, and thousands of chats share one database.

DECISION: events are buffered in a Redis list and flushed to Postgres in
batches by `flush_stat_events`. One `RPUSH` costs microseconds and never blocks
a handler behind a transaction; the flush job turns up to
`Settings.stats_flush_batch` rows into a single multi-row INSERT. Losing the
tail of the buffer on a hard Redis failure is acceptable — these are analytics,
not moderation records, and the alternative is a database write on the hottest
path in the product.

DECISION: the buffer is a single global list, not one per chat. The flusher then
does one `LPOP count` instead of scanning thousands of keys, and batches stay
full even when individual chats are quiet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from typing import Any, Final

from redis.asyncio import Redis

from core.redis_client import get_redis
from db.uow import UnitOfWork
from shared.config import get_settings
from shared.enums import StatEventType
from shared.logging import get_logger
from shared.schemas.api import StatPoint, StatsOverview, TopUser
from shared.time_utils import utc_now

logger = get_logger(__name__)

BUFFER_KEY: Final = "tgm:stats:buffer"

# Refuse to let the buffer grow without bound when the worker is down: past this
# many pending events the oldest ones are dropped rather than exhausting Redis.
MAX_BUFFER: Final = 200_000

# Report windows offered by `/stats` and the Mini App.
DEFAULT_PERIOD_DAYS: Final = 7
MAX_PERIOD_DAYS: Final = 365


@dataclass(frozen=True, slots=True)
class BufferedEvent:
    """One activity event on its way to `stat_events`."""

    chat_id: int
    event_type: StatEventType
    tg_user_id: int | None = None
    payload: dict[str, Any] | None = None

    def to_row(self) -> dict[str, Any]:
        """The dict shape `StatsRepository.bulk_insert_events` inserts."""
        return {
            "chat_id": self.chat_id,
            "tg_user_id": self.tg_user_id,
            "event_type": self.event_type.value,
            "payload": self.payload or {},
        }


class StatsBuffer:
    """Redis-side write buffer in front of `stat_events`."""

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    def _client(self) -> Redis:
        return self._redis if self._redis is not None else get_redis()

    async def push(self, event: BufferedEvent) -> None:
        """Append one event. Never raises — statistics must not break a handler."""
        try:
            client = self._client()
            await client.rpush(BUFFER_KEY, json.dumps(event.to_row()))  # type: ignore[misc]
            await client.ltrim(BUFFER_KEY, -MAX_BUFFER, -1)  # type: ignore[misc]
        except Exception as error:
            logger.debug("stats.buffer_push_failed", error=str(error))

    async def drain(self, limit: int) -> list[dict[str, Any]]:
        """Pop up to `limit` buffered rows, oldest first."""
        if limit < 1:
            return []
        raw = await self._client().lpop(BUFFER_KEY, limit)  # type: ignore[misc]
        if not raw:
            return []
        items: Sequence[Any] = raw if isinstance(raw, list) else [raw]
        rows: list[dict[str, Any]] = []
        for item in items:
            try:
                decoded = json.loads(item)
            except (TypeError, ValueError):
                continue
            if isinstance(decoded, dict):
                rows.append(decoded)
        return rows

    async def depth(self) -> int:
        """Events waiting to be flushed — the number to alert on."""
        try:
            return int(await self._client().llen(BUFFER_KEY))  # type: ignore[misc]
        except Exception:
            return 0


class StatsService:
    """The single entry point for recording and reading activity data."""

    def __init__(self, buffer: StatsBuffer | None = None) -> None:
        self._buffer = buffer or StatsBuffer()

    # --- ingest ---------------------------------------------------------------
    async def record(
        self,
        chat_id: int,
        event_type: StatEventType,
        *,
        tg_user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Buffer one event. Called from the message hot path."""
        await self._buffer.push(
            BufferedEvent(
                chat_id=chat_id,
                event_type=event_type,
                tg_user_id=tg_user_id,
                payload=payload,
            )
        )

    async def flush(self, limit: int | None = None) -> int:
        """Move buffered events into Postgres. Returns the number written."""
        batch = limit if limit is not None else get_settings().stats_flush_batch
        rows = await self._buffer.drain(batch)
        if not rows:
            return 0
        async with UnitOfWork() as uow:
            written = await uow.stats.bulk_insert_events(rows)
            await uow.commit()
        return written

    async def pending(self) -> int:
        return await self._buffer.depth()

    # --- reads ----------------------------------------------------------------
    async def overview(
        self,
        chat_id: int,
        *,
        days: int = DEFAULT_PERIOD_DAYS,
        end: date | None = None,
    ) -> StatsOverview:
        """The chart payload behind `/stats` and the Mini App's Statistics tab.

        Reads only the daily rollups, never the raw events: the rollup table has
        one row per chat per day, so the query stays flat no matter how busy the
        chat is. Today's row exists as soon as the aggregation job has run once
        today, which it does hourly. `end` moves the window off today — the
        daily digest asks for yesterday, whose rollup is already final.
        """
        window = max(1, min(days, MAX_PERIOD_DAYS))
        last = end or utc_now().date()
        start = last - timedelta(days=window - 1)

        async with UnitOfWork() as uow:
            daily = await uow.stats.daily_range(chat_id=chat_id, start=start, end=last)
            totals = await uow.stats.totals_since(chat_id=chat_id, start=start, end=last)
            leaders = await uow.stats.top_users(chat_id=chat_id, start=start, end=last, limit=10)

        by_day = {row.date: row for row in daily}
        series = []
        for offset in range(window):
            day = start + timedelta(days=offset)
            row = by_day.get(day)
            series.append(
                StatPoint(
                    date=day,
                    messages=row.messages if row is not None else 0,
                    active_users=row.active_users if row is not None else 0,
                    joins=row.joins if row is not None else 0,
                    leaves=row.leaves if row is not None else 0,
                    moderation_actions=row.moderation_actions if row is not None else 0,
                )
            )
        return StatsOverview(
            period_days=window,
            total_messages=totals["messages"],
            total_active_users=totals["peak_active_users"],
            total_joins=totals["joins"],
            total_leaves=totals["leaves"],
            net_growth=totals["joins"] - totals["leaves"],
            series=series,
            top_users=[TopUser(tg_user_id=uid, messages=count) for uid, count in leaders],
        )

    async def rollup(self, chat_id: int, *, day: date | None = None) -> None:
        """Recompute one chat's daily rollup from its raw events."""
        target = day or utc_now().date()
        async with UnitOfWork() as uow:
            await uow.stats.aggregate_day(chat_id=chat_id, day=target)
            await uow.commit()

    async def prune(self, *, retention_days: int, chat_ids: Sequence[int] | None = None) -> int:
        """Drop events and rollups older than the retention window.

        `chat_ids` restricts the sweep to chats that share one window, which is
        how the prune job applies a per-plan retention without a statement per
        chat; omitting it prunes every chat against the platform floor.
        """
        cutoff_at = utc_now() - timedelta(days=max(retention_days, 1))
        async with UnitOfWork() as uow:
            events = await uow.stats.prune_events(before=cutoff_at, chat_ids=chat_ids)
            daily = await uow.stats.prune_daily(before=cutoff_at.date(), chat_ids=chat_ids)
            await uow.commit()
        return events + daily


def period_bounds(days: int, *, now: datetime | None = None) -> tuple[date, date]:
    """Inclusive `(start, end)` dates for a report window."""
    window = max(1, min(days, MAX_PERIOD_DAYS))
    end = (now or utc_now()).date()
    return end - timedelta(days=window - 1), end


stats = StatsService()

__all__ = [
    "BUFFER_KEY",
    "DEFAULT_PERIOD_DAYS",
    "MAX_BUFFER",
    "MAX_PERIOD_DAYS",
    "BufferedEvent",
    "StatsBuffer",
    "StatsService",
    "period_bounds",
    "stats",
]

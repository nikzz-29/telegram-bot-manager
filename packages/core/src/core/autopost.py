"""Autoposting schedules: when does a post next fire?

Spec §5.6 — recurring or one-shot posts, in the chat's timezone, optionally
pinned, optionally replacing the previous copy.

DECISION: the next fire time is computed here rather than delegated to croniter.
The project needs exactly three shapes — a one-shot ISO timestamp, a daily
`HH:MM`, and a 5-field cron — and the cron subset that reaches this code is
already validated by `shared.time_utils.parse_cron` (digits, `*`, `/`, `,`, `-`).
Walking candidate minutes forward over that subset is about sixty lines, needs no
new dependency in the bot's runtime image, and cannot disagree with the validator
that accepted the expression.

DECISION: the walk is done in the chat's local timezone and the result converted
to UTC. `9 AM every day` must stay 9 AM after a DST change, which computing in
UTC would silently break by an hour twice a year. A local time that DST skips
(02:30 on a spring-forward night) resolves to the first valid instant after the
jump instead of being dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from shared.enums import ScheduleKind
from shared.errors import InvalidScheduleError
from shared.logging import get_logger
from shared.time_utils import parse_clock, parse_cron, utc, utc_now

logger = get_logger(__name__)

# How far ahead the cron walk is allowed to look before giving up. Four years
# covers every leap-day expression; anything beyond it is an unsatisfiable
# schedule such as `0 0 30 2 *`.
MAX_LOOKAHEAD_DAYS: Final = 366 * 4

_FIELD_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),  # day of week, Sunday = 0
)


def resolve_timezone(name: str) -> ZoneInfo:
    """The chat's timezone, falling back to UTC rather than failing a job."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("autopost.unknown_timezone", timezone=name)
        return ZoneInfo("UTC")


def _expand_field(spec: str, low: int, high: int) -> frozenset[int]:
    """Turn one cron field into the set of values it admits."""
    values: set[int] = set()
    for part in spec.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        step = 1
        if "/" in chunk:
            chunk, _, raw_step = chunk.partition("/")
            if not raw_step.isdigit() or int(raw_step) < 1:
                raise InvalidScheduleError(f"Invalid step in cron field: {part}")
            step = int(raw_step)
            chunk = chunk or "*"
        if chunk == "*":
            start, end = low, high
        elif "-" in chunk.lstrip("-"):
            raw_start, _, raw_end = chunk.partition("-")
            if not (raw_start.isdigit() and raw_end.isdigit()):
                raise InvalidScheduleError(f"Invalid range in cron field: {part}")
            start, end = int(raw_start), int(raw_end)
        elif chunk.isdigit():
            start = end = int(chunk)
        else:
            raise InvalidScheduleError(f"Invalid cron field: {part}")

        if start > end or start < low or end > high:
            raise InvalidScheduleError(f"Cron field out of range: {part}")
        values.update(range(start, end + 1, step))

    if not values:
        raise InvalidScheduleError("Cron field matched no values.")
    return frozenset(values)


class CronSchedule:
    """A parsed 5-field cron expression that can name its next fire time."""

    __slots__ = ("_days_restricted", "expression", "fields")

    def __init__(self, expression: str) -> None:
        self.expression = parse_cron(expression)
        parts = self.expression.split()
        self.fields = tuple(
            _expand_field(part, low, high)
            for part, (low, high) in zip(parts, _FIELD_RANGES, strict=True)
        )
        # Standard cron semantics: when *both* day-of-month and day-of-week are
        # restricted the expression fires on either, not on their intersection.
        self._days_restricted = (parts[2] != "*", parts[4] != "*")

    def _day_matches(self, moment: datetime) -> bool:
        dom_restricted, dow_restricted = self._days_restricted
        # `isoweekday() % 7` maps Monday..Sunday onto cron's Sunday-is-0.
        dom_ok = moment.day in self.fields[2]
        dow_ok = (moment.isoweekday() % 7) in self.fields[4]
        if dom_restricted and dow_restricted:
            return dom_ok or dow_ok
        return dom_ok and dow_ok

    def matches(self, moment: datetime) -> bool:
        return (
            moment.minute in self.fields[0]
            and moment.hour in self.fields[1]
            and moment.month in self.fields[3]
            and self._day_matches(moment)
        )

    def next_after(self, after: datetime) -> datetime | None:
        """The first matching local minute strictly after `after`, or `None`.

        `after` must be timezone-aware; the walk stays in that timezone so DST
        transitions are handled by the tzinfo rather than by arithmetic.
        """
        cursor = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
        limit = after + timedelta(days=MAX_LOOKAHEAD_DAYS)
        while cursor <= limit:
            if cursor.month not in self.fields[3]:
                cursor = _advance_month(cursor)
                continue
            if not self._day_matches(cursor):
                cursor = _advance_day(cursor)
                continue
            if cursor.hour not in self.fields[1]:
                cursor = (cursor + timedelta(hours=1)).replace(minute=0)
                continue
            if cursor.minute not in self.fields[0]:
                cursor += timedelta(minutes=1)
                continue
            return cursor
        logger.warning("autopost.cron_unsatisfiable", expression=self.expression)
        return None


def _advance_day(moment: datetime) -> datetime:
    return (moment + timedelta(days=1)).replace(hour=0, minute=0)


def _advance_month(moment: datetime) -> datetime:
    year, month = (moment.year + 1, 1) if moment.month == 12 else (moment.year, moment.month + 1)
    return moment.replace(year=year, month=month, day=1, hour=0, minute=0)


def parse_once(value: str) -> datetime:
    """Parse a one-shot schedule value: an ISO 8601 timestamp.

    A value without an offset is read as UTC — the API and the Mini App both send
    `Z`-suffixed timestamps, and guessing a chat timezone for a naive one would
    make the same string mean different instants in different chats.
    """
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidScheduleError(
            "One-shot schedule must be an ISO timestamp, e.g. 2026-01-31T09:00:00Z."
        ) from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def validate_schedule(kind: ScheduleKind, value: str) -> str:
    """Check a schedule and return it normalized for storage."""
    if kind is ScheduleKind.CRON:
        return CronSchedule(value).expression
    if kind is ScheduleKind.DAILY:
        offset = parse_clock(value)
        return f"{offset.seconds // 3600:02d}:{offset.seconds // 60 % 60:02d}"
    return parse_once(value).isoformat()


def next_run(
    kind: ScheduleKind,
    value: str,
    *,
    timezone: str = "UTC",
    after: datetime | None = None,
) -> datetime | None:
    """When this schedule next fires, in UTC. `None` when it never will again.

    A one-shot whose moment has passed returns `None`, which is what retires the
    post; recurring schedules always produce a next time.
    """
    reference = utc(after) if after is not None else utc_now()

    if kind is ScheduleKind.ONCE:
        moment = parse_once(value)
        return moment if moment > reference else None

    zone = resolve_timezone(timezone)
    local = reference.astimezone(zone)

    if kind is ScheduleKind.DAILY:
        offset = parse_clock(value)
        candidate = local.replace(
            hour=offset.seconds // 3600,
            minute=offset.seconds // 60 % 60,
            second=0,
            microsecond=0,
        )
        if candidate <= local:
            # Wall-clock arithmetic: `ZoneInfo` recomputes the offset from the new
            # local time, so 09:00 stays 09:00 across a DST boundary. A local time
            # the jump skips resolves to the first real instant after it.
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC)

    upcoming = CronSchedule(value).next_after(local)
    if upcoming is None:
        return None
    return upcoming.astimezone(UTC)


def describe(kind: ScheduleKind, value: str) -> str:
    """Short human form for a bot reply: `daily 09:00`, `cron 0 9 * * 1`."""
    if kind is ScheduleKind.ONCE:
        return value
    return f"{kind.value} {value}"


async def arm(post_id: int, when: datetime | None) -> None:
    """Queue a post's next fire, replacing whatever was queued before.

    DECISION: the job id is derived from the post id alone, so re-arming a post
    whose schedule changed replaces the pending job instead of stacking a second
    one that would fire at the old time. `when=None` retires the post — nothing
    is queued, and `sweep_due_posts` will not see it because a retired post is
    disabled.
    """
    from core import jobs
    from core.jobs import JobName, job_id

    if when is None:
        return
    await jobs.schedule_at(
        JobName.RUN_SCHEDULED_POST,
        when,
        post_id,
        _id=job_id(JobName.RUN_SCHEDULED_POST, post_id),
    )


async def disarm(post_id: int) -> bool:
    """Drop a post's pending fire — it was paused or deleted."""
    from core import jobs
    from core.jobs import JobName, job_id

    return await jobs.cancel(job_id(JobName.RUN_SCHEDULED_POST, post_id))


__all__ = [
    "MAX_LOOKAHEAD_DAYS",
    "CronSchedule",
    "arm",
    "describe",
    "disarm",
    "next_run",
    "parse_once",
    "resolve_timezone",
    "validate_schedule",
]

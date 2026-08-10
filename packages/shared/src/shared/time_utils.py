"""Time parsing utilities shared by bot commands, schedules and the API."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re

from shared.errors import InvalidDurationError, InvalidScheduleError

_DURATION_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)\s*(?P<unit>[mhdw])$", re.IGNORECASE)
_UNIT_SECONDS: dict[str, int] = {"m": 60, "h": 60 * 60, "d": 24 * 60 * 60, "w": 7 * 24 * 60 * 60}
_MAX_DURATION_SECONDS = 365 * 24 * 60 * 60

# A real CRON has exactly 5 fields of numbers or the supported wildcards.
_CRON_FIELD = r"[0-9*/,-]+"
_CRON_PATTERN = re.compile(rf"^{' '.join([_CRON_FIELD] * 5)}$")


def parse_duration(value: str) -> timedelta:
    """Parse Telegram-friendly durations: `30m`, `2h`, `7d`, `1w`.

    Raises:
        InvalidDurationError: the string does not match the format or is
            unreasonably long (Telegram caps `until_date` ~366 days ahead).
    """
    stripped = (value or "").strip().lower()
    match = _DURATION_PATTERN.fullmatch(stripped)
    if match is None:
        raise InvalidDurationError("Duration must use the format 30m, 2h, 7d or 1w.")
    seconds = int(match.group("amount")) * _UNIT_SECONDS[match.group("unit")]
    if seconds > _MAX_DURATION_SECONDS:
        raise InvalidDurationError("Duration must not exceed one year.")
    return timedelta(seconds=seconds)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware UTC, converting if needed."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_clock(value: str) -> timedelta:
    """Parse `HH:MM` (24h clock) into a time-of-day offset from midnight."""
    parts = value.strip().split(":", maxsplit=1)
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        raise InvalidScheduleError("Clock time must look like HH:MM.")
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        raise InvalidScheduleError("Clock time is out of range.")
    return timedelta(hours=hour, minutes=minute)


def parse_cron(value: str) -> str:
    """Validate a 5-field cron expression and return it normalized."""
    normalized = " ".join((value or "").split())
    if not _CRON_PATTERN.fullmatch(normalized):
        raise InvalidScheduleError("Cron must be a 5-field expression like '0 9 * * *'.")
    return normalized


def schedule_to_cron(kind: str, value: str) -> str:
    """Translate a schedule spec into a cron string.

    Supported shapes: ``daily HH:MM`` (chat timezone), a 5-field cron
    expression, or an ISO timestamp for a one-shot post.
    """
    if kind == "cron":
        return parse_cron(value)
    if kind == "daily":
        offset = parse_clock(value)
        return f"{offset.seconds // 60 % 60} {offset.seconds // 3600} * * *"
    raise InvalidScheduleError(f"Unsupported schedule kind: {kind}")


def human_duration(delta: timedelta) -> str:
    """Compact human form for localized log lines: '2h 30m'."""
    total = int(delta.total_seconds())
    days, rest = divmod(total, 86_400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def is_within(now: datetime, expires_at: datetime | None) -> bool:
    """Whether a time-bound restriction is still active."""
    if expires_at is None:
        return False
    return utc(expires_at) > utc(now)


__all__ = [
    "human_duration",
    "is_within",
    "parse_clock",
    "parse_cron",
    "parse_duration",
    "schedule_to_cron",
    "utc",
    "utc_now",
]

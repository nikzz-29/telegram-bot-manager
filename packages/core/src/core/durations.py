"""Duration parsing and formatting for moderation commands."""

from __future__ import annotations

from datetime import datetime, timedelta
import re

from shared.errors import InvalidDurationError
from shared.time_utils import utc_now

_DURATION_PATTERN = re.compile(r"^(?P<amount>[1-9][0-9]*)(?P<unit>[smhdw])$", re.IGNORECASE)
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
}

# Telegram treats a restriction shorter than 30s or longer than 366d as "forever",
# so callers get told rather than silently surprised.
MIN_RESTRICTION = timedelta(seconds=30)
MAX_RESTRICTION = timedelta(days=366)


def parse_duration(value: str) -> timedelta:
    """Parse Telegram-friendly durations such as `30m`, `2h`, `7d` or `1w`."""
    match = _DURATION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise InvalidDurationError("Duration must use the format 30m, 2h, 7d or 1w.")
    seconds = int(match.group("amount")) * _UNIT_SECONDS[match.group("unit").lower()]
    return timedelta(seconds=seconds)


def parse_optional_duration(value: str | None) -> timedelta | None:
    """`None` or an empty argument means a permanent action."""
    if value is None or not value.strip():
        return None
    return parse_duration(value)


def split_duration(value: str | None) -> tuple[timedelta | None, str]:
    """Split `30m spamming links` into its duration and the free-text reason.

    A first word that is not a duration is treated as part of the reason, so
    `/mute being rude` reads as a reason rather than a syntax error.
    """
    if not value or not value.strip():
        return None, ""
    parts = value.strip().split(maxsplit=1)
    try:
        duration = parse_duration(parts[0])
    except InvalidDurationError:
        return None, value.strip()
    return duration, (parts[1].strip() if len(parts) > 1 else "")


def expiry_from(duration: timedelta | None, *, now: datetime | None = None) -> datetime | None:
    """Absolute UTC expiry for a relative duration; `None` stays permanent."""
    if duration is None:
        return None
    return (now or utc_now()) + duration


def clamp_restriction(duration: timedelta | None) -> timedelta | None:
    """Clamp to the window Telegram actually honours for restrictions."""
    if duration is None:
        return None
    if duration < MIN_RESTRICTION:
        return MIN_RESTRICTION
    if duration > MAX_RESTRICTION:
        return None  # beyond Telegram's ceiling — treat as permanent
    return duration


def format_duration(duration: timedelta | None) -> str:
    """Compact human form (`2h30m`); `""` for permanent."""
    if duration is None:
        return ""
    total = int(duration.total_seconds())
    if total <= 0:
        return "0s"
    parts: list[str] = []
    for unit, size in (("w", 604_800), ("d", 86_400), ("h", 3_600), ("m", 60), ("s", 1)):
        count, total = divmod(total, size)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


__all__ = [
    "MAX_RESTRICTION",
    "MIN_RESTRICTION",
    "clamp_restriction",
    "expiry_from",
    "format_duration",
    "parse_duration",
    "parse_optional_duration",
    "split_duration",
]

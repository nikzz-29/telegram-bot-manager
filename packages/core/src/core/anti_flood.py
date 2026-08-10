"""Anti-flood counters.

Spec §5.1: the counters live in Redis as a sliding window and cost no database
hit per message. `RedisSlidingWindow` is therefore what the bot middleware uses —
one Lua round-trip per message, atomic across replicas, keys that expire on their
own when a chat goes quiet.

DECISION: the in-memory `SlidingWindowRateLimiter` stays as the reference
implementation. It needs no infrastructure, which makes the window semantics
unit-testable, and cheap per-process guards can use it without touching Redis.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

from redis.asyncio import Redis

from core.redis_client import get_redis
from shared.schemas.module_configs import ModerationConfig

KEY_PREFIX: Final = "tgm:flood"

# Message content that arrives in bursts and is worth counting separately from
# plain text — five stickers in five seconds is a flood, five words is not.
MEDIA_KINDS: Final[frozenset[str]] = frozenset(
    {"sticker", "animation", "photo", "video", "video_note", "voice", "document", "audio"}
)

# KEYS[1] = window key
# ARGV[1] = window length in ms, ARGV[2] = unique member token
# Returns the number of events inside the window, this one included.
_HIT_LUA: Final = """
local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local token = ARGV[2]

local clock = redis.call('TIME')
local now_ms = (tonumber(clock[1]) * 1000) + math.floor(tonumber(clock[2]) / 1000)

redis.call('ZREMRANGEBYSCORE', key, 0, now_ms - window_ms)
redis.call('ZADD', key, now_ms, token)
redis.call('PEXPIRE', key, window_ms + 1000)
return redis.call('ZCARD', key)
"""


@dataclass(frozen=True, slots=True)
class FloodPolicy:
    limit: int = 6
    window: timedelta = timedelta(seconds=10)
    message_types: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class FloodVerdict:
    """How many events landed in the window, and whether that is too many."""

    count: int
    limit: int
    window_seconds: int
    kind: str = "message"

    @property
    def tripped(self) -> bool:
        return self.count > self.limit


class RedisSlidingWindow:
    """Sorted-set sliding window shared by every bot process.

    DECISION: the member is a random token rather than the timestamp. Two
    messages landing in the same millisecond would otherwise collide on the same
    sorted-set member and the second one would not be counted.
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis
        self._script: Any | None = None

    def _client(self) -> Redis:
        return self._redis if self._redis is not None else get_redis()

    def _registered(self) -> Any:
        if self._script is None:
            self._script = self._client().register_script(_HIT_LUA)
        return self._script

    async def hit(self, key: str, *, window: timedelta) -> int:
        """Record one event and return the window's occupancy, this one included."""
        window_ms = max(int(window.total_seconds() * 1000), 1)
        count = await self._registered()(
            keys=[f"{KEY_PREFIX}:{key}"], args=[window_ms, uuid4().hex]
        )
        return int(count)

    async def count(self, key: str) -> int:
        """Events currently stored. Diagnostics and "N messages in Ms" reports."""
        return int(await self._client().zcard(f"{KEY_PREFIX}:{key}"))

    async def reset(self, key: str) -> None:
        """Clear a window — called after a mute so it restarts clean."""
        await self._client().delete(f"{KEY_PREFIX}:{key}")


class AntiFloodService:
    """Per-user flood detection driven by a chat's `ModerationConfig`."""

    def __init__(self, window: RedisSlidingWindow | None = None) -> None:
        self._window = window or RedisSlidingWindow()

    @staticmethod
    def _key(chat_id: int, tg_user_id: int, suffix: str = "") -> str:
        base = f"{chat_id}:{tg_user_id}"
        return f"{base}:{suffix}" if suffix else base

    async def check(
        self,
        chat_id: int,
        tg_user_id: int,
        *,
        config: ModerationConfig,
        content_kind: str = "text",
    ) -> FloodVerdict | None:
        """Count this message and report a verdict when a window is over its limit.

        Returns `None` when anti-flood is off or the user is inside both limits.
        The media window is checked first: a sticker burst should be reported as
        a media flood even when it also pushes the general counter over.
        """
        if not config.anti_flood_enabled:
            return None

        if content_kind in MEDIA_KINDS:
            media_window = timedelta(seconds=config.anti_flood_media_seconds)
            media_count = await self._window.hit(
                self._key(chat_id, tg_user_id, "media"), window=media_window
            )
            if media_count > config.anti_flood_media_messages:
                return FloodVerdict(
                    count=media_count,
                    limit=config.anti_flood_media_messages,
                    window_seconds=config.anti_flood_media_seconds,
                    kind="media",
                )

        window = timedelta(seconds=config.anti_flood_seconds)
        count = await self._window.hit(self._key(chat_id, tg_user_id), window=window)
        if count > config.anti_flood_messages:
            return FloodVerdict(
                count=count,
                limit=config.anti_flood_messages,
                window_seconds=config.anti_flood_seconds,
                kind="message",
            )
        return None

    async def reset(self, chat_id: int, tg_user_id: int) -> None:
        """Forget a user's history — after a mute, so the window starts clean."""
        await self._window.reset(self._key(chat_id, tg_user_id))
        await self._window.reset(self._key(chat_id, tg_user_id, "media"))


class SlidingWindowRateLimiter:
    """Per-key in-memory sliding window; keys are `"chat_id:user_id"`."""

    def __init__(self) -> None:
        self._events: defaultdict[str, deque[datetime]] = defaultdict(deque)

    def is_allowed(
        self,
        key: str,
        policy: FloodPolicy,
        now: datetime | None = None,
    ) -> bool:
        if policy.limit < 1:
            raise ValueError("Flood limit must be positive.")
        if policy.window <= timedelta():
            raise ValueError("Flood window must be positive.")
        current_time = now or datetime.now(UTC)
        events = self._events[key]
        threshold = current_time - policy.window
        while events and events[0] <= threshold:
            events.popleft()
        if len(events) >= policy.limit:
            return False
        events.append(current_time)
        return True

    def is_allowed_type(
        self,
        key: str,
        message_type: str,
        policy: FloodPolicy,
        now: datetime | None = None,
    ) -> bool:
        """Per-message-type variant for media floods (stickers/gifs in bursts)."""
        if message_type not in policy.message_types:
            return True
        subkey = f"{key}:{message_type}"
        current_time = now or datetime.now(UTC)
        threshold = current_time - policy.window
        events = self._events[subkey]
        while events and events[0] <= threshold:
            events.popleft()
        if len(events) >= policy.limit:
            return False
        events.append(current_time)
        return True

    def hit_count(self, key: str, window: timedelta, now: datetime | None = None) -> int:
        """Live event count in `window` — used to report "N messages in Ms"."""
        current_time = now or datetime.now(UTC)
        events = self._events[key]
        while events and events[0] <= current_time - window:
            events.popleft()
        return len(events)

    def reset(self, key: str) -> None:
        """Clear a key's history — called after a mute so the window starts clean."""
        self._events.pop(key, None)


anti_flood = AntiFloodService()

__all__ = [
    "MEDIA_KINDS",
    "AntiFloodService",
    "FloodPolicy",
    "FloodVerdict",
    "RedisSlidingWindow",
    "SlidingWindowRateLimiter",
    "anti_flood",
]

"""Distributed token bucket on Redis.

Telegram enforces roughly 30 messages/second globally and about 20 per minute
into a single group. Exceeding either earns a 429 with a `retry_after` that
stalls every chat behind it, so the limit has to hold across *all* processes,
not per-process — hence Redis rather than an in-memory counter.

DECISION: the refill/consume step runs as a Lua script so check-and-decrement is
atomic. Two bot replicas asking at the same millisecond cannot both be told yes
for the last token.

DECISION: time comes from Redis (`TIME`) rather than each caller's clock, so a
skewed container cannot hand itself extra tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from redis.asyncio import Redis

from core.redis_client import get_redis

KEY_PREFIX: Final = "tgm:bucket"

# KEYS[1] = bucket key
# ARGV[1] = capacity, ARGV[2] = refill tokens per second, ARGV[3] = requested
# Returns {allowed (0|1), wait_ms}
_CONSUME_LUA: Final = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])

local now_arr = redis.call('TIME')
local now = tonumber(now_arr[1]) + (tonumber(now_arr[2]) / 1000000)

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

local elapsed = now - ts
if elapsed > 0 then
  tokens = math.min(capacity, tokens + (elapsed * rate))
  ts = now
end

local allowed = 0
local wait_ms = 0
if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  wait_ms = math.ceil(((requested - tokens) / rate) * 1000)
end

redis.call('HSET', key, 'tokens', tokens, 'ts', ts)
-- Idle buckets expire: a chat that goes quiet must not leak a key forever.
local ttl = math.ceil(capacity / rate) * 2 + 10
redis.call('EXPIRE', key, ttl)

return {allowed, wait_ms}
"""


@dataclass(frozen=True, slots=True)
class BucketSpec:
    """Capacity and refill rate for one bucket."""

    key: str
    capacity: int
    refill_per_second: float

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("Bucket capacity must be positive.")
        if self.refill_per_second <= 0:
            raise ValueError("Bucket refill rate must be positive.")


@dataclass(frozen=True, slots=True)
class BucketResult:
    """Outcome of one `consume` attempt."""

    allowed: bool
    retry_after: float

    def __bool__(self) -> bool:
        return self.allowed


class TokenBucket:
    """Redis-backed token bucket shared by every process."""

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis
        self._script: Any | None = None

    def _client(self) -> Redis:
        return self._redis if self._redis is not None else get_redis()

    def _registered(self) -> Any:
        if self._script is None:
            self._script = self._client().register_script(_CONSUME_LUA)
        return self._script

    async def consume(self, spec: BucketSpec, tokens: int = 1) -> BucketResult:
        """Take `tokens` from a bucket, or report how long to wait."""
        raw = await self._registered()(
            keys=[f"{KEY_PREFIX}:{spec.key}"],
            args=[spec.capacity, spec.refill_per_second, tokens],
        )
        allowed = bool(int(raw[0]))
        wait_ms = float(raw[1])
        return BucketResult(allowed=allowed, retry_after=wait_ms / 1000.0)

    async def consume_all(self, specs: tuple[BucketSpec, ...], tokens: int = 1) -> BucketResult:
        """Take from several buckets, giving back anything taken if one refuses.

        DECISION: not atomic across buckets — the global and per-chat buckets are
        separate keys and may live on different cluster slots. On a partial
        failure the already-taken tokens are returned, so the worst case is a
        brief over-refund, never a stuck bucket.
        """
        taken: list[BucketSpec] = []
        for spec in specs:
            result = await self.consume(spec, tokens)
            if result.allowed:
                taken.append(spec)
                continue
            for used in taken:
                await self.give_back(used, tokens)
            return result
        return BucketResult(allowed=True, retry_after=0.0)

    async def give_back(self, spec: BucketSpec, tokens: int = 1) -> None:
        """Return unused tokens (the send failed before it reached Telegram)."""
        client = self._client()
        key = f"{KEY_PREFIX}:{spec.key}"
        current = await client.hget(key, "tokens")  # type: ignore[misc]
        if current is None:
            return
        restored = min(float(spec.capacity), float(current) + tokens)
        await client.hset(key, "tokens", str(restored))  # type: ignore[misc]

    async def peek(self, spec: BucketSpec) -> float:
        """Tokens currently stored, without refilling. Diagnostics only."""
        current = await self._client().hget(f"{KEY_PREFIX}:{spec.key}", "tokens")  # type: ignore[misc]
        return float(spec.capacity) if current is None else float(current)

    async def reset(self, spec: BucketSpec) -> None:
        await self._client().delete(f"{KEY_PREFIX}:{spec.key}")


def global_bucket(rate_per_second: int) -> BucketSpec:
    """The shared ~30 msg/s ceiling across every chat."""
    return BucketSpec(
        key="global", capacity=rate_per_second, refill_per_second=float(rate_per_second)
    )


def chat_bucket(chat_id: int, rate_per_minute: int) -> BucketSpec:
    """The ~20 msg/min ceiling for one group."""
    return BucketSpec(
        key=f"chat:{chat_id}",
        capacity=rate_per_minute,
        refill_per_second=rate_per_minute / 60.0,
    )


token_bucket = TokenBucket()

__all__ = [
    "BucketResult",
    "BucketSpec",
    "TokenBucket",
    "chat_bucket",
    "global_bucket",
    "token_bucket",
]

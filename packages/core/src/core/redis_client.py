"""Process-wide Redis connection.

DECISION: one `ConnectionPool` per process, shared by the rate limiter, the
sender's dead-letter list and anything else needing raw Redis. cashews keeps its
own pool for the cache — mixing the two would mean one library's decode settings
dictating the other's.

Values are kept as raw bytes (`decode_responses=False`) because the dead-letter
list stores JSON we encode ourselves and Lua scripts return numbers.
"""

from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from shared.config import get_settings

_pool: ConnectionPool | None = None
_client: Redis | None = None


def get_redis(url: str | None = None) -> Redis:
    """Lazily created, process-wide Redis client."""
    global _pool, _client
    if _client is None:
        target = url or get_settings().redis_url
        _pool = ConnectionPool.from_url(target, decode_responses=False)
        _client = Redis(connection_pool=_pool)
    return _client


def set_redis(client: Redis) -> None:
    """Override the client (used by tests against fakeredis)."""
    global _client
    _client = client


async def close_redis() -> None:
    """Close the pool during graceful shutdown."""
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.disconnect()
        _pool = None


__all__ = ["close_redis", "get_redis", "set_redis"]

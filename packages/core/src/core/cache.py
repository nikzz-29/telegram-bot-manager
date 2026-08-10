"""Redis-backed cache facade built on cashews.

Every hot path in the bot (plan lookups, feature gates, module configs, admin
checks) reads through this module, so a settings change in the Mini App has to
invalidate exactly one place.

DECISION: values go through an explicit typed facade rather than cashews'
``@cache`` decorators. The decorators rewrite signatures in a way mypy --strict
cannot follow, and explicit keys keep invalidation auditable — you can grep for
every producer of a key template.
"""

from __future__ import annotations

from typing import Any, Final

from cashews import Cache

from shared.config import get_settings

# --- TTLs ---------------------------------------------------------------------
# DECISION: chat-scoped entries get a generous TTL because writes invalidate
# them explicitly by tag; the TTL is only a backstop against a missed
# invalidation, not the primary freshness mechanism.
TTL_CHAT: Final = 600
TTL_PLAN: Final = 600
TTL_FEATURES: Final = 600
TTL_MODULE_CONFIG: Final = 600
TTL_AI_VERDICT: Final = 86_400
TTL_GLOBAL_BAN: Final = 300
TTL_SHORT: Final = 30

KEY_PREFIX: Final = "tgm"

cache = Cache(name="tgm")

_initialized = False


# --- key builders -------------------------------------------------------------
def chat_key(chat_id: int) -> str:
    return f"{KEY_PREFIX}:chat:{chat_id}"


def plan_key(chat_id: int) -> str:
    return f"{KEY_PREFIX}:plan:{chat_id}"


def features_key(chat_id: int) -> str:
    return f"{KEY_PREFIX}:features:{chat_id}"


def module_config_key(chat_id: int, module: str) -> str:
    return f"{KEY_PREFIX}:module:{chat_id}:{module}"


def enabled_modules_key(chat_id: int) -> str:
    return f"{KEY_PREFIX}:modules:{chat_id}"


def triggers_key(chat_id: int) -> str:
    """Compiled-matcher input for a chat's enabled trigger rules."""
    return f"{KEY_PREFIX}:triggers:{chat_id}"


def admin_key(chat_id: int, tg_user_id: int) -> str:
    """getChatMember result; TTL is `Settings.admin_cache_ttl_seconds` (spec: 5 min)."""
    return f"{KEY_PREFIX}:admin:{chat_id}:{tg_user_id}"


def admin_list_key(chat_id: int) -> str:
    return f"{KEY_PREFIX}:admins:{chat_id}"


def ai_verdict_key(text_hash: str) -> str:
    """Verdicts are keyed by text hash only — identical text costs one call platform-wide."""
    return f"{KEY_PREFIX}:ai:verdict:{text_hash}"


def global_ban_key(tg_user_id: int) -> str:
    return f"{KEY_PREFIX}:gban:{tg_user_id}"


# --- tags ---------------------------------------------------------------------
def subscription_key(chat_id: int, tg_user_id: int) -> str:
    """Forced-subscription verdict; short-lived, see `core.subscription`."""
    return f"{KEY_PREFIX}:sub:{chat_id}:{tg_user_id}"


def chat_tag(chat_id: int) -> str:
    """Tag stamped on every chat-scoped entry so one call drops all of them."""
    return f"{KEY_PREFIX}-chat-{chat_id}"


def user_tag(tg_user_id: int) -> str:
    return f"{KEY_PREFIX}-user-{tg_user_id}"


_TAG_TEMPLATES: Final[tuple[tuple[str, str], ...]] = (
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:chat:{{chat_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:plan:{{chat_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:features:{{chat_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:module:{{chat_id}}:{{module}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:modules:{{chat_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:admin:{{chat_id}}:{{tg_user_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:admins:{{chat_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:triggers:{{chat_id}}"),
    (f"{KEY_PREFIX}-chat-{{chat_id}}", f"{KEY_PREFIX}:sub:{{chat_id}}:{{tg_user_id}}"),
    (f"{KEY_PREFIX}-user-{{tg_user_id}}", f"{KEY_PREFIX}:gban:{{tg_user_id}}"),
)


def setup_cache(url: str | None = None) -> Cache:
    """Wire the cache to Redis. Idempotent, so every entrypoint can call it.

    DECISION: `client_side=False`. Client-side caching would serve stale plan
    data to one process after another process invalidated it, and correctness of
    the paywall matters more than shaving a Redis round-trip.
    """
    global _initialized
    if _initialized:
        return cache
    settings = get_settings()
    cache.setup(url or settings.redis_url, client_side=False)
    for tag_template, key_template in _TAG_TEMPLATES:
        cache.register_tag(tag_template, key_template)
    _initialized = True
    return cache


async def close_cache() -> None:
    global _initialized
    if _initialized:
        await cache.close()
        _initialized = False


def is_initialized() -> bool:
    return _initialized


# --- invalidation -------------------------------------------------------------
async def invalidate_chat(chat_id: int) -> None:
    """Drop every cached entry for one chat (plan, features, configs, admins)."""
    await cache.delete_tags(chat_tag(chat_id))


async def invalidate_chat_plan(chat_id: int) -> None:
    """After a plan change: plan, features and enabled-module set all move."""
    await cache.delete(plan_key(chat_id))
    await cache.delete(features_key(chat_id))
    await cache.delete(enabled_modules_key(chat_id))
    await cache.delete(chat_key(chat_id))


async def invalidate_module_config(chat_id: int, module: str) -> None:
    await cache.delete(module_config_key(chat_id, module))
    await cache.delete(enabled_modules_key(chat_id))


async def invalidate_user(tg_user_id: int) -> None:
    await cache.delete_tags(user_tag(tg_user_id))


async def invalidate_admins(chat_id: int) -> None:
    await cache.delete(admin_list_key(chat_id))
    await cache.delete_match(f"{KEY_PREFIX}:admin:{chat_id}:*")


# --- typed accessors ----------------------------------------------------------
async def get_value(key: str) -> Any:
    return await cache.get(key)


async def set_value(key: str, value: Any, *, ttl: int, tags: tuple[str, ...] = ()) -> None:
    await cache.set(key, value, expire=ttl, tags=tags)


async def ping() -> bool:
    """Readiness probe for /health."""
    try:
        await cache.ping()
    except Exception:
        return False
    return True


__all__ = [
    "TTL_AI_VERDICT",
    "TTL_CHAT",
    "TTL_FEATURES",
    "TTL_GLOBAL_BAN",
    "TTL_MODULE_CONFIG",
    "TTL_PLAN",
    "TTL_SHORT",
    "admin_key",
    "admin_list_key",
    "ai_verdict_key",
    "cache",
    "chat_key",
    "chat_tag",
    "close_cache",
    "enabled_modules_key",
    "features_key",
    "get_value",
    "global_ban_key",
    "invalidate_admins",
    "invalidate_chat",
    "invalidate_chat_plan",
    "invalidate_module_config",
    "invalidate_user",
    "is_initialized",
    "module_config_key",
    "ping",
    "plan_key",
    "set_value",
    "setup_cache",
    "subscription_key",
    "triggers_key",
    "user_tag",
]

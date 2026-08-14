"""HTTP routers. Each one is thin: authorize, delegate, serialize."""

from api.routers import account, auth, chats, modules, posts, reputation, stats, system, triggers

__all__ = [
    "account",
    "auth",
    "chats",
    "modules",
    "posts",
    "reputation",
    "stats",
    "system",
    "triggers",
]

"""HTTP routers. Each one is thin: authorize, delegate, serialize."""

from api.routers import auth, chats, modules, posts, reputation, stats, system, triggers

__all__ = [
    "auth",
    "chats",
    "modules",
    "posts",
    "reputation",
    "stats",
    "system",
    "triggers",
]

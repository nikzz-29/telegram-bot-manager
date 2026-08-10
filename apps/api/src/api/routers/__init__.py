"""HTTP routers. Each one is thin: authorize, delegate, serialize."""

from api.routers import auth, chats, modules, system

__all__ = ["auth", "chats", "modules", "system"]

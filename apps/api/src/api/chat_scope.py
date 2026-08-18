"""Resolve the chats a user may see from live Telegram administrator status."""

from __future__ import annotations

import asyncio

from api.deps import AdminsDep, UowDep
from api.security import Principal
from db.models import Chat


async def _is_live_admin(admins: AdminsDep, chat: Chat, tg_user_id: int) -> bool:
    """Return a fail-closed verdict for one mirrored chat."""
    try:
        return await admins.is_admin(chat.tg_chat_id, tg_user_id)
    except Exception:
        # Telegram outages and an unbound service must never turn a stale mirror
        # into access.  Per-chat authorization follows the same fail-closed rule.
        return False


async def accessible_chats(
    principal: Principal,
    uow: UowDep,
    admins: AdminsDep,
) -> list[Chat]:
    """Return active mirrored chats where Telegram still confirms admin rights.

    ``admin_users`` is intentionally only a candidate index.  Promotions and
    demotions happen outside our database, so every candidate is checked with
    the cached ``getChatMember`` authority before account data is aggregated.
    Checks run concurrently to keep a user's dashboard responsive across many
    chats; ``AdminService`` provides the five-minute Redis cache.
    """
    mirrored = await uow.chats.list_for_admin(principal.tg_user_id)
    candidates = [chat for chat in mirrored if chat.is_active]
    verdicts = await asyncio.gather(
        *(_is_live_admin(admins, chat, principal.tg_user_id) for chat in candidates)
    )
    return [chat for chat, is_admin in zip(candidates, verdicts, strict=True) if is_admin]


__all__ = ["accessible_chats"]

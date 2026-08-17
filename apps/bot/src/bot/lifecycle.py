"""Telegram chat lifecycle for the bot's own membership.

`my_chat_member` is the authoritative signal that the bot was added, promoted,
demoted, or removed.  It is deliberately outside the feature-module routers:
an inactive chat still has to process the update that can reactivate it.
"""

from __future__ import annotations

from typing import Final

from aiogram import Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from core.admins import admins
from core.context import ChatContext
from db.uow import UnitOfWork
from shared.enums import ChatType
from shared.logging import get_logger

logger = get_logger(__name__)

PRESENT_STATUSES: Final = frozenset(
    {
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.RESTRICTED,
    }
)
OPERATIONAL_STATUSES: Final = frozenset({ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR})


async def handle_bot_membership(event: ChatMemberUpdated, ctx: ChatContext) -> None:
    """Persist bot availability and refresh Telegram's administrator authority."""
    status = event.new_chat_member.status
    is_present = status in PRESENT_STATUSES
    is_operational = status in OPERATIONAL_STATUSES

    async with UnitOfWork() as uow:
        await uow.chats.update_fields(
            ctx.chat_id,
            title=event.chat.title or "",
            username=event.chat.username,
            type=ChatType(event.chat.type),
            # Moderation requires administrator rights.  A demoted bot remains
            # in Telegram but is inactive in the product until promoted again.
            is_active=is_operational,
        )
        await uow.commit()

    if is_present:
        count = await admins.sync_to_db(ctx.chat_id, ctx.tg_chat_id)
        member = event.new_chat_member
        is_owner = status == ChatMemberStatus.CREATOR
        missing = [
            permission
            for permission in ("can_delete_messages", "can_restrict_members")
            if not is_owner and not bool(getattr(member, permission, False))
        ]
        logger.info(
            "bot.membership_updated",
            chat_id=ctx.chat_id,
            tg_chat_id=ctx.tg_chat_id,
            status=status.value,
            active=is_operational,
            admins=count,
            missing_permissions=missing,
        )
        if is_operational and missing:
            logger.warning(
                "bot.permissions_incomplete",
                chat_id=ctx.chat_id,
                tg_chat_id=ctx.tg_chat_id,
                missing=missing,
            )
        return

    await admins.invalidate(ctx.tg_chat_id)
    logger.info(
        "bot.removed_from_chat",
        chat_id=ctx.chat_id,
        tg_chat_id=ctx.tg_chat_id,
        status=status.value,
    )


async def sync_administrator_membership(event: ChatMemberUpdated, ctx: ChatContext) -> bool:
    """Refresh the mirror when a human enters or leaves an administrator role."""
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    changed = not event.new_chat_member.user.is_bot and (
        old_status in OPERATIONAL_STATUSES or new_status in OPERATIONAL_STATUSES
    )
    if changed:
        await admins.sync_to_db(ctx.chat_id, ctx.tg_chat_id)
    return changed


def build_router() -> Router:
    router = Router(name="bot_lifecycle")

    @router.my_chat_member()
    async def bot_membership_changed(event: ChatMemberUpdated, ctx: ChatContext | None) -> None:
        if ctx is not None:
            await handle_bot_membership(event, ctx)

    @router.chat_member()
    async def administrator_changed(event: ChatMemberUpdated, ctx: ChatContext | None) -> None:
        """Mirror promotions and demotions without consuming join/leave updates."""
        if ctx is not None:
            await sync_administrator_membership(event, ctx)
        # The entry module owns join/leave side effects and must see the event.
        raise SkipHandler

    return router


__all__ = ["build_router", "handle_bot_membership", "sync_administrator_membership"]

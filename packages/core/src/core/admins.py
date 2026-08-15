"""Who may moderate a chat.

DECISION: Telegram is the authority, not our `admin_users` table. Promotions and
demotions happen in the Telegram client without any update we can rely on, so
`getChatMember` is the check and the table is only a mirror kept for the Mini App
and for "alert the admins" fan-out.

DECISION: results are cached for `admin_cache_ttl_seconds` (spec: 5 minutes).
Every moderation command and every Mini App write would otherwise cost a Bot API
round-trip, and demotions tolerate five minutes of staleness far better than the
rate limit tolerates a call per action.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError

from core import cache
from db.uow import UnitOfWork
from shared.config import get_settings
from shared.enums import AdminRole
from shared.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from aiogram import Bot

logger = get_logger(__name__)

ADMIN_STATUSES = frozenset({ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR})


class MemberFetcher(Protocol):
    """The slice of `Bot` this service needs, so tests need no Bot at all."""

    async def get_chat_member(self, chat_id: int, user_id: int) -> Any: ...

    async def get_chat_administrators(self, chat_id: int) -> Any: ...


class AdminService:
    """Cached `getChatMember` admin checks plus the mirrored admin list."""

    def __init__(self, bot: MemberFetcher | None = None) -> None:
        self._bot = bot

    def bind(self, bot: Bot) -> None:
        self._bot = bot

    @property
    def ttl(self) -> int:
        return get_settings().admin_cache_ttl_seconds

    async def is_admin(self, tg_chat_id: int, tg_user_id: int) -> bool:
        """True when the user administers the chat, or is the platform operator."""
        if tg_user_id in get_settings().superadmin_id_list:
            return True
        key = cache.admin_key(tg_chat_id, tg_user_id)
        cached = await cache.get_value(key)
        if isinstance(cached, bool):
            return cached

        verdict = await self._fetch_is_admin(tg_chat_id, tg_user_id)
        await cache.set_value(key, verdict, ttl=self.ttl, tags=(cache.chat_tag(tg_chat_id),))
        return verdict

    async def _fetch_is_admin(self, tg_chat_id: int, tg_user_id: int) -> bool:
        if self._bot is None:
            raise RuntimeError("AdminService needs a Bot before it can check membership.")
        try:
            member = await self._bot.get_chat_member(tg_chat_id, tg_user_id)
        except TelegramAPIError as exc:
            # DECISION: fail closed. An unreachable Telegram must not hand out
            # moderation rights, and the caller sees a plain "not an admin".
            logger.warning(
                "admins.check_failed", chat_id=tg_chat_id, user_id=tg_user_id, error=str(exc)
            )
            return False
        return bool(member.status in ADMIN_STATUSES)

    async def admin_ids(self, tg_chat_id: int) -> tuple[int, ...]:
        """Every human admin of the chat, cached; used for admin alerts."""
        key = cache.admin_list_key(tg_chat_id)
        cached = await cache.get_value(key)
        if isinstance(cached, list):
            return tuple(int(item) for item in cached)

        if self._bot is None:
            raise RuntimeError("AdminService needs a Bot before it can list administrators.")
        try:
            members = await self._bot.get_chat_administrators(tg_chat_id)
        except TelegramAPIError as exc:
            logger.warning("admins.list_failed", chat_id=tg_chat_id, error=str(exc))
            return ()
        ids = tuple(
            member.user.id
            for member in members
            if member.user is not None and not member.user.is_bot
        )
        await cache.set_value(key, list(ids), ttl=self.ttl, tags=(cache.chat_tag(tg_chat_id),))
        return ids

    async def sync_to_db(self, chat_id: int, tg_chat_id: int) -> int:
        """Mirror Telegram's admin list into `admin_users`. Returns the count."""
        if self._bot is None:
            raise RuntimeError("AdminService needs a Bot before it can sync administrators.")
        try:
            members = await self._bot.get_chat_administrators(tg_chat_id)
        except TelegramAPIError as exc:
            logger.warning("admins.sync_failed", chat_id=tg_chat_id, error=str(exc))
            return 0
        roles: dict[int, AdminRole] = {}
        owner_tg_id: int | None = None
        for member in members:
            if member.user is None or member.user.is_bot:
                continue
            role = AdminRole.OWNER if member.status == ChatMemberStatus.CREATOR else AdminRole.ADMIN
            roles[member.user.id] = role
            if role is AdminRole.OWNER:
                owner_tg_id = member.user.id
        async with UnitOfWork() as uow:
            await uow.admins.replace_for_chat(chat_id, roles)
            await uow.chats.update_fields(chat_id, owner_tg_id=owner_tg_id)
            await uow.commit()
        await cache.invalidate_admins(tg_chat_id)
        return len(roles)

    async def invalidate(self, tg_chat_id: int, tg_user_id: int | None = None) -> None:
        """Drop cached verdicts after a promotion or demotion."""
        if tg_user_id is None:
            await cache.invalidate_admins(tg_chat_id)
            return
        await cache.cache.delete(cache.admin_key(tg_chat_id, tg_user_id))
        await cache.cache.delete(cache.admin_list_key(tg_chat_id))


admins = AdminService()

__all__ = ["ADMIN_STATUSES", "AdminService", "MemberFetcher", "admins"]

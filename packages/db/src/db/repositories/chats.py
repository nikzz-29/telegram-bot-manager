"""Chat and module-config repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Chat, ChatModuleConfig
from shared.enums import ChatType, Plan


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, chat_id: int) -> Chat | None:
        return await self._session.get(Chat, chat_id)

    async def get_by_tg_id(self, tg_chat_id: int) -> Chat | None:
        result = await self._session.execute(select(Chat).where(Chat.tg_chat_id == tg_chat_id))
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        tg_chat_id: int,
        *,
        title: str = "",
        chat_type: ChatType = ChatType.SUPERGROUP,
        owner_tg_id: int | None = None,
        username: str | None = None,
    ) -> Chat:
        """Upsert on tg_chat_id so concurrent updates cannot create duplicates."""
        stmt = (
            pg_insert(Chat)
            .values(
                tg_chat_id=tg_chat_id,
                title=title,
                type=chat_type,
                owner_tg_id=owner_tg_id,
                username=username,
                plan=Plan.FREE,
                settings={},
            )
            .on_conflict_do_update(
                index_elements=[Chat.tg_chat_id],
                set_={"title": title, "updated_at": func.now()},
            )
            .returning(Chat)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def list_for_admin(self, tg_user_id: int) -> list[Chat]:
        """Chats where the user is a recorded admin or the owner."""
        from db.models import AdminUser  # local import avoids a cycle at module load

        stmt: Select[tuple[Chat]] = (
            select(Chat)
            .outerjoin(AdminUser, AdminUser.chat_id == Chat.id)
            .where(
                Chat.is_active.is_(True),
                (AdminUser.tg_user_id == tg_user_id) | (Chat.owner_tg_id == tg_user_id),
            )
            .distinct()
            .order_by(Chat.title)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Chat]:
        result = await self._session.execute(
            select(Chat).order_by(Chat.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_plans(self, plans: list[Plan]) -> list[Chat]:
        result = await self._session.execute(
            select(Chat).where(Chat.plan.in_(plans), Chat.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def count_by_plan(self) -> dict[str, int]:
        result = await self._session.execute(select(Chat.plan, func.count()).group_by(Chat.plan))
        return {str(plan): count for plan, count in result.all()}

    async def count(self, *, active_only: bool = False) -> int:
        stmt = select(func.count()).select_from(Chat)
        if active_only:
            stmt = stmt.where(Chat.is_active.is_(True))
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def set_plan(
        self,
        chat_id: int,
        plan: Plan,
        *,
        expires_at: datetime | None,
        grace_until: datetime | None = None,
    ) -> None:
        await self._session.execute(
            update(Chat)
            .where(Chat.id == chat_id)
            .values(plan=plan, plan_expires_at=expires_at, grace_until=grace_until)
        )

    async def set_active(self, chat_id: int, *, is_active: bool) -> None:
        await self._session.execute(
            update(Chat).where(Chat.id == chat_id).values(is_active=is_active)
        )

    async def update_fields(self, chat_id: int, **fields: Any) -> None:
        if not fields:
            return
        await self._session.execute(update(Chat).where(Chat.id == chat_id).values(**fields))

    async def set_lockdown(self, chat_id: int, until: datetime | None) -> None:
        await self._session.execute(
            update(Chat).where(Chat.id == chat_id).values(lockdown_until=until)
        )

    async def find_expiring(self, before: datetime) -> list[Chat]:
        """Paid chats whose subscription ends before `before` (reminder cron)."""
        result = await self._session.execute(
            select(Chat).where(
                Chat.plan != Plan.FREE,
                Chat.plan_expires_at.is_not(None),
                Chat.plan_expires_at <= before,
            )
        )
        return list(result.scalars().all())


class ModuleConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_chat(self, chat_id: int) -> list[ChatModuleConfig]:
        result = await self._session.execute(
            select(ChatModuleConfig).where(ChatModuleConfig.chat_id == chat_id)
        )
        return list(result.scalars().all())

    async def get(self, chat_id: int, module: str) -> ChatModuleConfig | None:
        result = await self._session.execute(
            select(ChatModuleConfig).where(
                ChatModuleConfig.chat_id == chat_id, ChatModuleConfig.module == module
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        chat_id: int,
        module: str,
        *,
        enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> ChatModuleConfig:
        """Insert or patch a module config, touching only supplied fields."""
        values: dict[str, Any] = {
            "chat_id": chat_id,
            "module": module,
            "enabled": enabled if enabled is not None else False,
            "config": config if config is not None else {},
        }
        updates: dict[str, Any] = {"updated_at": func.now()}
        if enabled is not None:
            updates["enabled"] = enabled
        if config is not None:
            updates["config"] = config

        stmt = (
            pg_insert(ChatModuleConfig)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[ChatModuleConfig.chat_id, ChatModuleConfig.module],
                set_=updates,
            )
            .returning(ChatModuleConfig)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def set_enabled_bulk(self, chat_id: int, modules: list[str], *, enabled: bool) -> None:
        if not modules:
            return
        await self._session.execute(
            update(ChatModuleConfig)
            .where(ChatModuleConfig.chat_id == chat_id, ChatModuleConfig.module.in_(modules))
            .values(enabled=enabled)
        )

    async def list_enabled_chats(self, module: str) -> list[int]:
        """Chat ids with this module switched on (used by cron fan-out)."""
        result = await self._session.execute(
            select(ChatModuleConfig.chat_id).where(
                ChatModuleConfig.module == module, ChatModuleConfig.enabled.is_(True)
            )
        )
        return list(result.scalars().all())

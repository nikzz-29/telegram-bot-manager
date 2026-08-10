"""Chat administrator records."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AdminUser
from shared.enums import AdminRole


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, chat_id: int, tg_user_id: int, role: AdminRole = AdminRole.ADMIN
    ) -> AdminUser:
        stmt = (
            pg_insert(AdminUser)
            .values(chat_id=chat_id, tg_user_id=tg_user_id, role=role)
            .on_conflict_do_update(
                index_elements=[AdminUser.chat_id, AdminUser.tg_user_id],
                set_={"role": role, "updated_at": func.now()},
            )
            .returning(AdminUser)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def replace_for_chat(self, chat_id: int, admins: dict[int, AdminRole]) -> None:
        """Sync the full admin list after a getChatAdministrators refresh."""
        await self._session.execute(delete(AdminUser).where(AdminUser.chat_id == chat_id))
        for tg_user_id, role in admins.items():
            self._session.add(AdminUser(chat_id=chat_id, tg_user_id=tg_user_id, role=role))
        await self._session.flush()

    async def is_admin(self, chat_id: int, tg_user_id: int) -> bool:
        result = await self._session.execute(
            select(func.count())
            .select_from(AdminUser)
            .where(AdminUser.chat_id == chat_id, AdminUser.tg_user_id == tg_user_id)
        )
        return int(result.scalar_one()) > 0

    async def list_for_chat(self, chat_id: int) -> list[AdminUser]:
        result = await self._session.execute(select(AdminUser).where(AdminUser.chat_id == chat_id))
        return list(result.scalars().all())

    async def list_admin_ids(self, chat_id: int) -> list[int]:
        result = await self._session.execute(
            select(AdminUser.tg_user_id).where(AdminUser.chat_id == chat_id)
        )
        return list(result.scalars().all())

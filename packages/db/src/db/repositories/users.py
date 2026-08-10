"""Telegram user profile cache."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TgUser


class TgUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tg_user_id: int) -> TgUser | None:
        return await self._session.get(TgUser, tg_user_id)

    async def upsert(
        self,
        *,
        tg_user_id: int,
        username: str | None = None,
        first_name: str = "",
        last_name: str | None = None,
        language_code: str | None = None,
        is_bot: bool = False,
        has_photo: bool = False,
    ) -> TgUser:
        stmt = (
            pg_insert(TgUser)
            .values(
                tg_user_id=tg_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                is_bot=is_bot,
                has_photo=has_photo,
            )
            .on_conflict_do_update(
                index_elements=[TgUser.tg_user_id],
                set_={
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "language_code": language_code,
                    "updated_at": func.now(),
                },
            )
            .returning(TgUser)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def get_many(self, tg_user_ids: list[int]) -> dict[int, TgUser]:
        if not tg_user_ids:
            return {}
        result = await self._session.execute(
            select(TgUser).where(TgUser.tg_user_id.in_(tg_user_ids))
        )
        return {user.tg_user_id: user for user in result.scalars().all()}

    async def find_by_username(self, username: str) -> TgUser | None:
        """Resolve `@name` targets for moderation commands."""
        normalized = username.lstrip("@").lower()
        result = await self._session.execute(
            select(TgUser).where(func.lower(TgUser.username) == normalized).limit(1)
        )
        return result.scalar_one_or_none()

"""Cross-chat ban blacklist."""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import GlobalBan, GlobalBanReport
from db.repositories._dml import execute_dml
from shared.time_utils import utc_now


class GlobalBanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tg_user_id: int) -> GlobalBan | None:
        result = await self._session.execute(
            select(GlobalBan).where(GlobalBan.tg_user_id == tg_user_id)
        )
        return result.scalar_one_or_none()

    async def is_banned(self, tg_user_id: int) -> bool:
        result = await self._session.execute(
            select(func.count())
            .select_from(GlobalBan)
            .where(GlobalBan.tg_user_id == tg_user_id, GlobalBan.is_active.is_(True))
        )
        return int(result.scalar_one()) > 0

    async def list_active_ids(self) -> list[int]:
        result = await self._session.execute(
            select(GlobalBan.tg_user_id).where(GlobalBan.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def report(
        self, *, chat_id: int, tg_user_id: int, reason: str, reported_by: int | None
    ) -> int:
        """Record one chat's ban and return the distinct-chat count.

        The unique (chat_id, tg_user_id) constraint means a chat that bans the
        same user twice cannot inflate the counter.
        """
        await self._session.execute(
            pg_insert(GlobalBanReport)
            .values(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                reason=reason,
                reported_by=reported_by,
            )
            .on_conflict_do_nothing(constraint="uq_ban_report_chat_user")
        )
        count = await self.report_count(tg_user_id)
        stmt = (
            pg_insert(GlobalBan)
            .values(tg_user_id=tg_user_id, reason=reason, chat_count=count, is_active=False)
            .on_conflict_do_update(
                index_elements=[GlobalBan.tg_user_id],
                set_={"chat_count": count, "updated_at": func.now()},
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return count

    async def report_count(self, tg_user_id: int) -> int:
        result = await self._session.execute(
            select(func.count(func.distinct(GlobalBanReport.chat_id))).where(
                GlobalBanReport.tg_user_id == tg_user_id
            )
        )
        return int(result.scalar_one())

    async def promote(self, *, tg_user_id: int, reason: str, banned_by: int | None) -> GlobalBan:
        """Flip a reported user into an active global ban."""
        stmt = (
            pg_insert(GlobalBan)
            .values(
                tg_user_id=tg_user_id,
                reason=reason,
                is_active=True,
                banned_by=banned_by,
            )
            .on_conflict_do_update(
                index_elements=[GlobalBan.tg_user_id],
                set_={
                    "is_active": True,
                    "reason": reason,
                    "banned_by": banned_by,
                    "updated_at": func.now(),
                },
            )
            .returning(GlobalBan)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def revoke(self, tg_user_id: int) -> bool:
        affected = await execute_dml(
            self._session,
            update(GlobalBan)
            .where(GlobalBan.tg_user_id == tg_user_id)
            .values(is_active=False, appealed_at=utc_now()),
        )
        return bool(affected)

    async def purge(self, tg_user_id: int) -> None:
        await self._session.execute(
            delete(GlobalBanReport).where(GlobalBanReport.tg_user_id == tg_user_id)
        )
        await self._session.execute(delete(GlobalBan).where(GlobalBan.tg_user_id == tg_user_id))

    async def list_all(self, *, active_only: bool = True, limit: int = 200) -> list[GlobalBan]:
        stmt = select(GlobalBan)
        if active_only:
            stmt = stmt.where(GlobalBan.is_active.is_(True))
        result = await self._session.execute(
            stmt.order_by(GlobalBan.chat_count.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def count_active(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(GlobalBan).where(GlobalBan.is_active.is_(True))
        )
        return int(result.scalar_one())

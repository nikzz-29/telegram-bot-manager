"""Reputation and level repository."""

from __future__ import annotations

from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Reputation


class ReputationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, chat_id: int, tg_user_id: int) -> Reputation | None:
        result = await self._session.execute(
            select(Reputation).where(
                Reputation.chat_id == chat_id, Reputation.tg_user_id == tg_user_id
            )
        )
        return result.scalar_one_or_none()

    async def add_points(self, *, chat_id: int, tg_user_id: int, delta: int) -> Reputation:
        """Upsert-and-increment so concurrent +rep never loses a vote."""
        stmt = (
            pg_insert(Reputation)
            .values(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                points=delta,
                weekly_points=delta,
                monthly_points=delta,
            )
            .on_conflict_do_update(
                constraint="uq_reputation_chat_user",
                set_={
                    "points": Reputation.points + delta,
                    "weekly_points": Reputation.weekly_points + delta,
                    "monthly_points": Reputation.monthly_points + delta,
                    "updated_at": func.now(),
                },
            )
            .returning(Reputation)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def add_experience(
        self, *, chat_id: int, tg_user_id: int, delta: int, level: int
    ) -> Reputation:
        stmt = (
            pg_insert(Reputation)
            .values(chat_id=chat_id, tg_user_id=tg_user_id, experience=delta, level=level)
            .on_conflict_do_update(
                constraint="uq_reputation_chat_user",
                set_={
                    "experience": Reputation.experience + delta,
                    "updated_at": func.now(),
                },
            )
            .returning(Reputation)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def set_level(self, *, chat_id: int, tg_user_id: int, level: int) -> None:
        await self._session.execute(
            update(Reputation)
            .where(Reputation.chat_id == chat_id, Reputation.tg_user_id == tg_user_id)
            .values(level=level)
        )

    async def top(
        self, chat_id: int, *, limit: int = 10, field: str = "points"
    ) -> list[Reputation]:
        column = {
            "points": Reputation.points,
            "experience": Reputation.experience,
            "weekly_points": Reputation.weekly_points,
            "monthly_points": Reputation.monthly_points,
        }.get(field, Reputation.points)
        result = await self._session.execute(
            select(Reputation)
            .where(Reputation.chat_id == chat_id)
            .order_by(desc(column))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def rank(self, chat_id: int, tg_user_id: int) -> int | None:
        """1-based position in the chat leaderboard."""
        entry = await self.get(chat_id, tg_user_id)
        if entry is None:
            return None
        result = await self._session.execute(
            select(func.count())
            .select_from(Reputation)
            .where(Reputation.chat_id == chat_id, Reputation.points > entry.points)
        )
        return int(result.scalar_one()) + 1

    async def reset_weekly(self) -> None:
        await self._session.execute(update(Reputation).values(weekly_points=0))

    async def reset_monthly(self) -> None:
        await self._session.execute(update(Reputation).values(monthly_points=0))

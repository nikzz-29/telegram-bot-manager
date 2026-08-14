"""Statistics: raw event ingest, daily rollups, retention pruning."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import StatDaily, StatEvent, StatUserDaily
from db.repositories._dml import execute_dml
from shared.enums import StatEventType


class StatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_insert_events(self, rows: Sequence[dict[str, Any]]) -> int:
        """Flush a Redis-buffered batch in one statement."""
        if not rows:
            return 0
        await self._session.execute(pg_insert(StatEvent).values(list(rows)))
        return len(rows)

    async def add_event(
        self,
        *,
        chat_id: int,
        event_type: StatEventType,
        tg_user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            StatEvent(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                event_type=event_type,
                payload=payload or {},
            )
        )

    async def aggregate_day(self, *, chat_id: int, day: date) -> StatDaily:
        """Roll raw events for one chat/day into `stat_daily` + `stat_user_daily`."""
        totals = await self._session.execute(
            select(
                StatEvent.event_type,
                func.count().label("total"),
                func.count(func.distinct(StatEvent.tg_user_id)).label("users"),
            )
            .where(
                StatEvent.chat_id == chat_id,
                func.date(StatEvent.created_at) == day,
            )
            .group_by(StatEvent.event_type)
        )
        counts: dict[str, int] = {}
        active_users = 0
        for event_type, total, users in totals.all():
            counts[str(event_type)] = int(total)
            if event_type == StatEventType.MESSAGE:
                active_users = int(users)

        messages = counts.get(StatEventType.MESSAGE, 0)
        joins = counts.get(StatEventType.JOIN, 0)
        leaves = counts.get(StatEventType.LEAVE, 0)
        moderation_actions = counts.get(StatEventType.MODERATION, 0)

        stmt = (
            pg_insert(StatDaily)
            .values(
                chat_id=chat_id,
                date=day,
                messages=messages,
                active_users=active_users,
                joins=joins,
                leaves=leaves,
                moderation_actions=moderation_actions,
                metrics=counts,
            )
            .on_conflict_do_update(
                constraint="uq_stat_daily_chat_date",
                set_={
                    "messages": messages,
                    "active_users": active_users,
                    "joins": joins,
                    "leaves": leaves,
                    "moderation_actions": moderation_actions,
                    "metrics": counts,
                    "updated_at": func.now(),
                },
            )
            .returning(StatDaily)
        )
        result = await self._session.execute(stmt)
        await self._aggregate_user_day(chat_id=chat_id, day=day)
        await self._session.flush()
        return result.scalar_one()

    async def _aggregate_user_day(self, *, chat_id: int, day: date) -> None:
        per_user = await self._session.execute(
            select(StatEvent.tg_user_id, func.count().label("messages"))
            .where(
                StatEvent.chat_id == chat_id,
                StatEvent.event_type == StatEventType.MESSAGE,
                StatEvent.tg_user_id.is_not(None),
                func.date(StatEvent.created_at) == day,
            )
            .group_by(StatEvent.tg_user_id)
        )
        rows = [
            {"chat_id": chat_id, "date": day, "tg_user_id": int(uid), "messages": int(count)}
            for uid, count in per_user.all()
        ]
        if not rows:
            return
        await self._session.execute(
            pg_insert(StatUserDaily)
            .values(rows)
            .on_conflict_do_update(
                constraint="uq_stat_user_daily",
                set_={"messages": pg_insert(StatUserDaily).excluded.messages},
            )
        )

    async def chats_with_events(self, *, day: date, limit: int = 5000) -> list[int]:
        result = await self._session.execute(
            select(StatEvent.chat_id)
            .where(func.date(StatEvent.created_at) == day)
            .group_by(StatEvent.chat_id)
            .limit(limit)
        )
        return [int(row) for row in result.scalars().all()]

    async def daily_range(self, *, chat_id: int, start: date, end: date) -> list[StatDaily]:
        result = await self._session.execute(
            select(StatDaily)
            .where(StatDaily.chat_id == chat_id, StatDaily.date >= start, StatDaily.date <= end)
            .order_by(StatDaily.date)
        )
        return list(result.scalars().all())

    async def daily_range_many(
        self, *, chat_ids: Sequence[int], start: date, end: date
    ) -> list[dict[str, int | date]]:
        """Daily totals for several chats in one grouped query."""
        if not chat_ids:
            return []
        result = await self._session.execute(
            select(
                StatDaily.date,
                func.coalesce(func.sum(StatDaily.messages), 0),
                func.coalesce(func.sum(StatDaily.active_users), 0),
                func.coalesce(func.sum(StatDaily.joins), 0),
                func.coalesce(func.sum(StatDaily.leaves), 0),
                func.coalesce(func.sum(StatDaily.moderation_actions), 0),
            )
            .where(
                StatDaily.chat_id.in_(chat_ids),
                StatDaily.date >= start,
                StatDaily.date <= end,
            )
            .group_by(StatDaily.date)
            .order_by(StatDaily.date)
        )
        return [
            {
                "date": day,
                "messages": int(messages),
                "active_users": int(active_users),
                "joins": int(joins),
                "leaves": int(leaves),
                "moderation_actions": int(actions),
            }
            for day, messages, active_users, joins, leaves, actions in result.all()
        ]

    async def top_users(
        self, *, chat_id: int, start: date, end: date, limit: int = 10
    ) -> list[tuple[int, int]]:
        result = await self._session.execute(
            select(StatUserDaily.tg_user_id, func.sum(StatUserDaily.messages).label("messages"))
            .where(
                StatUserDaily.chat_id == chat_id,
                StatUserDaily.date >= start,
                StatUserDaily.date <= end,
            )
            .group_by(StatUserDaily.tg_user_id)
            .order_by(desc("messages"))
            .limit(limit)
        )
        return [(int(uid), int(messages)) for uid, messages in result.all()]

    async def top_users_many(
        self, *, chat_ids: Sequence[int], start: date, end: date, limit: int = 10
    ) -> list[tuple[int, int]]:
        """Leaderboard across the user's selected chats, without an N+1 loop."""
        if not chat_ids:
            return []
        result = await self._session.execute(
            select(
                StatUserDaily.tg_user_id,
                func.sum(StatUserDaily.messages).label("messages"),
            )
            .where(
                StatUserDaily.chat_id.in_(chat_ids),
                StatUserDaily.date >= start,
                StatUserDaily.date <= end,
            )
            .group_by(StatUserDaily.tg_user_id)
            .order_by(desc("messages"), StatUserDaily.tg_user_id)
            .limit(limit)
        )
        return [(int(uid), int(messages)) for uid, messages in result.all()]

    async def totals_since(
        self, *, chat_id: int, start: date, end: date | None = None
    ) -> dict[str, int]:
        stmt = select(
            func.coalesce(func.sum(StatDaily.messages), 0),
            func.coalesce(func.sum(StatDaily.joins), 0),
            func.coalesce(func.sum(StatDaily.leaves), 0),
            func.coalesce(func.sum(StatDaily.moderation_actions), 0),
            func.coalesce(func.max(StatDaily.active_users), 0),
        ).where(StatDaily.chat_id == chat_id, StatDaily.date >= start)
        if end is not None:
            stmt = stmt.where(StatDaily.date <= end)
        result = await self._session.execute(stmt)
        messages, joins, leaves, actions, peak_active = result.one()
        return {
            "messages": int(messages),
            "joins": int(joins),
            "leaves": int(leaves),
            "moderation_actions": int(actions),
            "peak_active_users": int(peak_active),
        }

    async def prune_events(self, *, before: datetime, chat_ids: Sequence[int] | None = None) -> int:
        """Drop raw events older than `before`, optionally for one set of chats.

        Retention is a plan quota, so the prune job passes the chats that share a
        retention window and issues one statement per window instead of one per
        chat. `chat_ids=None` means every chat — the platform-wide floor sweep.
        """
        if chat_ids is not None and not chat_ids:
            return 0
        stmt = delete(StatEvent).where(StatEvent.created_at < before)
        if chat_ids is not None:
            stmt = stmt.where(StatEvent.chat_id.in_(chat_ids))
        return await execute_dml(self._session, stmt)

    async def prune_daily(self, *, before: date, chat_ids: Sequence[int] | None = None) -> int:
        if chat_ids is not None and not chat_ids:
            return 0
        daily_stmt = delete(StatDaily).where(StatDaily.date < before)
        user_stmt = delete(StatUserDaily).where(StatUserDaily.date < before)
        if chat_ids is not None:
            daily_stmt = daily_stmt.where(StatDaily.chat_id.in_(chat_ids))
            user_stmt = user_stmt.where(StatUserDaily.chat_id.in_(chat_ids))
        daily = await execute_dml(self._session, daily_stmt)
        per_user = await execute_dml(self._session, user_stmt)
        return daily + per_user

    async def reset_period(self, *, chat_id: int) -> None:
        await self._session.execute(delete(StatEvent).where(StatEvent.chat_id == chat_id))

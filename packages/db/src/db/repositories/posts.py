"""Scheduled post repository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ScheduledPost
from db.repositories._dml import execute_dml


class ScheduledPostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_chat(
        self, chat_id: int, *, enabled_only: bool = False
    ) -> list[ScheduledPost]:
        stmt = select(ScheduledPost).where(ScheduledPost.chat_id == chat_id)
        if enabled_only:
            stmt = stmt.where(ScheduledPost.enabled.is_(True))
        result = await self._session.execute(stmt.order_by(ScheduledPost.id))
        return list(result.scalars().all())

    async def get(self, chat_id: int, post_id: int) -> ScheduledPost | None:
        result = await self._session.execute(
            select(ScheduledPost).where(
                ScheduledPost.id == post_id, ScheduledPost.chat_id == chat_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, post_id: int) -> ScheduledPost | None:
        return await self._session.get(ScheduledPost, post_id)

    async def count(self, chat_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(ScheduledPost).where(ScheduledPost.chat_id == chat_id)
        )
        return int(result.scalar_one())

    async def create(self, chat_id: int, **fields: Any) -> ScheduledPost:
        post = ScheduledPost(chat_id=chat_id, **fields)
        self._session.add(post)
        await self._session.flush()
        return post

    async def update(self, chat_id: int, post_id: int, **fields: Any) -> ScheduledPost | None:
        if fields:
            await self._session.execute(
                update(ScheduledPost)
                .where(ScheduledPost.id == post_id, ScheduledPost.chat_id == chat_id)
                .values(**fields)
            )
        return await self.get(chat_id, post_id)

    async def delete(self, chat_id: int, post_id: int) -> bool:
        affected = await execute_dml(
            self._session,
            delete(ScheduledPost).where(
                ScheduledPost.id == post_id, ScheduledPost.chat_id == chat_id
            ),
        )
        return bool(affected)

    async def mark_ran(
        self, post_id: int, *, message_id: int | None, next_run_at: datetime | None
    ) -> None:
        from shared.time_utils import utc_now

        await self._session.execute(
            update(ScheduledPost)
            .where(ScheduledPost.id == post_id)
            .values(last_run_at=utc_now(), last_message_id=message_id, next_run_at=next_run_at)
        )

    async def list_due(self, *, now: datetime, limit: int = 200) -> list[ScheduledPost]:
        """Posts whose next run has passed — the cron safety net."""
        result = await self._session.execute(
            select(ScheduledPost)
            .where(
                ScheduledPost.enabled.is_(True),
                ScheduledPost.next_run_at.is_not(None),
                ScheduledPost.next_run_at <= now,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all_enabled(self) -> list[ScheduledPost]:
        result = await self._session.execute(
            select(ScheduledPost).where(ScheduledPost.enabled.is_(True))
        )
        return list(result.scalars().all())

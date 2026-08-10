"""Trigger rule repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TriggerRule
from db.repositories._dml import execute_dml


class TriggerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_chat(self, chat_id: int, *, enabled_only: bool = False) -> list[TriggerRule]:
        stmt = select(TriggerRule).where(TriggerRule.chat_id == chat_id)
        if enabled_only:
            stmt = stmt.where(TriggerRule.enabled.is_(True))
        result = await self._session.execute(stmt.order_by(TriggerRule.id))
        return list(result.scalars().all())

    async def get(self, chat_id: int, trigger_id: int) -> TriggerRule | None:
        result = await self._session.execute(
            select(TriggerRule).where(TriggerRule.id == trigger_id, TriggerRule.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def count(self, chat_id: int) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(TriggerRule).where(TriggerRule.chat_id == chat_id)
        )
        return int(result.scalar_one())

    async def create(self, chat_id: int, **fields: Any) -> TriggerRule:
        trigger = TriggerRule(chat_id=chat_id, **fields)
        self._session.add(trigger)
        await self._session.flush()
        return trigger

    async def update(self, chat_id: int, trigger_id: int, **fields: Any) -> TriggerRule | None:
        if fields:
            await self._session.execute(
                update(TriggerRule)
                .where(TriggerRule.id == trigger_id, TriggerRule.chat_id == chat_id)
                .values(**fields)
            )
        return await self.get(chat_id, trigger_id)

    async def delete(self, chat_id: int, trigger_id: int) -> bool:
        affected = await execute_dml(
            self._session,
            delete(TriggerRule).where(TriggerRule.id == trigger_id, TriggerRule.chat_id == chat_id),
        )
        return bool(affected)

    async def increment_hits(self, trigger_id: int) -> None:
        await self._session.execute(
            update(TriggerRule)
            .where(TriggerRule.id == trigger_id)
            .values(hits=TriggerRule.hits + 1)
        )

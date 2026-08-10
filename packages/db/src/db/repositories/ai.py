"""AI moderation audit log — also the source of the per-chat daily budget."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AiCheckLog
from db.repositories._dml import execute_dml
from shared.enums import AiVerdictLabel


class AiCheckLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        chat_id: int,
        tg_user_id: int | None,
        label: AiVerdictLabel,
        confidence: float,
        action: str,
        text_hash: str,
    ) -> None:
        self._session.add(
            AiCheckLog(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                label=label,
                confidence=Decimal(str(round(confidence, 3))),
                action=action,
                text_hash=text_hash,
            )
        )

    async def count_since(self, *, chat_id: int, since: datetime) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(AiCheckLog)
            .where(AiCheckLog.chat_id == chat_id, AiCheckLog.created_at >= since)
        )
        return int(result.scalar_one())

    async def list_for_chat(self, chat_id: int, *, limit: int = 100) -> list[AiCheckLog]:
        result = await self._session.execute(
            select(AiCheckLog)
            .where(AiCheckLog.chat_id == chat_id)
            .order_by(AiCheckLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def prune(self, *, before: datetime) -> int:
        return await execute_dml(
            self._session, delete(AiCheckLog).where(AiCheckLog.created_at < before)
        )

"""Pending captcha challenges."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CaptchaChallenge
from shared.time_utils import utc_now


class CaptchaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        chat_id: int,
        tg_user_id: int,
        kind: str,
        answer: str,
        expires_at: datetime,
        message_id: int | None = None,
        arq_job_id: str | None = None,
    ) -> CaptchaChallenge:
        """One pending challenge per (chat, user); a rejoin replaces the old one."""
        stmt = (
            pg_insert(CaptchaChallenge)
            .values(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                kind=kind,
                answer=answer,
                expires_at=expires_at,
                message_id=message_id,
                arq_job_id=arq_job_id,
                attempts=0,
            )
            .on_conflict_do_update(
                index_elements=[CaptchaChallenge.chat_id, CaptchaChallenge.tg_user_id],
                set_={
                    "kind": kind,
                    "answer": answer,
                    "expires_at": expires_at,
                    "message_id": message_id,
                    "arq_job_id": arq_job_id,
                    "attempts": 0,
                    "solved_at": None,
                    "updated_at": func.now(),
                },
            )
            .returning(CaptchaChallenge)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()

    async def get_pending(self, chat_id: int, tg_user_id: int) -> CaptchaChallenge | None:
        result = await self._session.execute(
            select(CaptchaChallenge).where(
                CaptchaChallenge.chat_id == chat_id,
                CaptchaChallenge.tg_user_id == tg_user_id,
                CaptchaChallenge.solved_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def has_pending(self, chat_id: int, tg_user_id: int) -> bool:
        result = await self._session.execute(
            select(func.count())
            .select_from(CaptchaChallenge)
            .where(
                CaptchaChallenge.chat_id == chat_id,
                CaptchaChallenge.tg_user_id == tg_user_id,
                CaptchaChallenge.solved_at.is_(None),
            )
        )
        return int(result.scalar_one()) > 0

    async def mark_solved(self, challenge_id: int) -> None:
        await self._session.execute(
            update(CaptchaChallenge)
            .where(CaptchaChallenge.id == challenge_id)
            .values(solved_at=utc_now())
        )

    async def increment_attempts(self, challenge_id: int) -> int:
        result = await self._session.execute(
            update(CaptchaChallenge)
            .where(CaptchaChallenge.id == challenge_id)
            .values(attempts=CaptchaChallenge.attempts + 1)
            .returning(CaptchaChallenge.attempts)
        )
        return int(result.scalar_one())

    async def delete(self, chat_id: int, tg_user_id: int) -> None:
        await self._session.execute(
            delete(CaptchaChallenge).where(
                CaptchaChallenge.chat_id == chat_id,
                CaptchaChallenge.tg_user_id == tg_user_id,
            )
        )

    async def list_expired(
        self, *, now: datetime | None = None, limit: int = 500
    ) -> list[CaptchaChallenge]:
        moment = now or utc_now()
        result = await self._session.execute(
            select(CaptchaChallenge)
            .where(
                CaptchaChallenge.solved_at.is_(None),
                CaptchaChallenge.expires_at <= moment,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

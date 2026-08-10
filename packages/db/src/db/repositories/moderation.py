"""Warn, punishment and moderation-log repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ModerationLog, Punishment, Warn
from db.repositories._dml import execute_dml
from shared.enums import PunishmentType
from shared.time_utils import utc_now


class WarnRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        chat_id: int,
        tg_user_id: int,
        moderator_tg_id: int,
        reason: str,
        expires_at: datetime | None,
    ) -> Warn:
        warn = Warn(
            chat_id=chat_id,
            tg_user_id=tg_user_id,
            moderator_tg_id=moderator_tg_id,
            reason=reason,
            expires_at=expires_at,
        )
        self._session.add(warn)
        await self._session.flush()
        return warn

    async def count_active(
        self, chat_id: int, tg_user_id: int, *, now: datetime | None = None
    ) -> int:
        moment = now or utc_now()
        result = await self._session.execute(
            select(func.count())
            .select_from(Warn)
            .where(
                Warn.chat_id == chat_id,
                Warn.tg_user_id == tg_user_id,
                Warn.revoked_at.is_(None),
                (Warn.expires_at.is_(None)) | (Warn.expires_at > moment),
            )
        )
        return int(result.scalar_one())

    async def list_active(
        self, chat_id: int, tg_user_id: int, *, now: datetime | None = None
    ) -> list[Warn]:
        moment = now or utc_now()
        result = await self._session.execute(
            select(Warn)
            .where(
                Warn.chat_id == chat_id,
                Warn.tg_user_id == tg_user_id,
                Warn.revoked_at.is_(None),
                (Warn.expires_at.is_(None)) | (Warn.expires_at > moment),
            )
            .order_by(Warn.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_last(
        self, chat_id: int, tg_user_id: int, *, moderator_tg_id: int
    ) -> Warn | None:
        """Revoke the most recent active warn; returns None when there is none."""
        warns = await self.list_active(chat_id, tg_user_id)
        if not warns:
            return None
        warn = warns[0]
        warn.revoked_at = utc_now()
        warn.revoked_by = moderator_tg_id
        await self._session.flush()
        return warn

    async def revoke_all(self, chat_id: int, tg_user_id: int, *, moderator_tg_id: int) -> int:
        return await execute_dml(
            self._session,
            update(Warn)
            .where(
                Warn.chat_id == chat_id,
                Warn.tg_user_id == tg_user_id,
                Warn.revoked_at.is_(None),
            )
            .values(revoked_at=utc_now(), revoked_by=moderator_tg_id),
        )

    async def list_for_chat(self, chat_id: int, *, limit: int = 100) -> list[Warn]:
        result = await self._session.execute(
            select(Warn)
            .where(Warn.chat_id == chat_id, Warn.revoked_at.is_(None))
            .order_by(Warn.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class PunishmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        chat_id: int,
        tg_user_id: int,
        moderator_tg_id: int,
        punishment_type: PunishmentType,
        reason: str = "",
        expires_at: datetime | None = None,
        arq_job_id: str | None = None,
    ) -> Punishment:
        punishment = Punishment(
            chat_id=chat_id,
            tg_user_id=tg_user_id,
            moderator_tg_id=moderator_tg_id,
            type=punishment_type,
            reason=reason,
            expires_at=expires_at,
            arq_job_id=arq_job_id,
            active=True,
        )
        self._session.add(punishment)
        await self._session.flush()
        return punishment

    async def get_active(
        self, chat_id: int, tg_user_id: int, punishment_type: PunishmentType | None = None
    ) -> Punishment | None:
        stmt = select(Punishment).where(
            Punishment.chat_id == chat_id,
            Punishment.tg_user_id == tg_user_id,
            Punishment.active.is_(True),
        )
        if punishment_type is not None:
            stmt = stmt.where(Punishment.type == punishment_type)
        result = await self._session.execute(stmt.order_by(Punishment.created_at.desc()).limit(1))
        return result.scalar_one_or_none()

    async def deactivate(self, punishment_id: int) -> None:
        await self._session.execute(
            update(Punishment)
            .where(Punishment.id == punishment_id)
            .values(active=False, lifted_at=utc_now())
        )

    async def deactivate_for_user(
        self, chat_id: int, tg_user_id: int, punishment_type: PunishmentType | None = None
    ) -> int:
        stmt = update(Punishment).where(
            Punishment.chat_id == chat_id,
            Punishment.tg_user_id == tg_user_id,
            Punishment.active.is_(True),
        )
        if punishment_type is not None:
            stmt = stmt.where(Punishment.type == punishment_type)
        return await execute_dml(self._session, stmt.values(active=False, lifted_at=utc_now()))

    async def list_expired(
        self, *, now: datetime | None = None, limit: int = 500
    ) -> list[Punishment]:
        """Safety net for jobs lost to a Redis flush."""
        moment = now or utc_now()
        result = await self._session.execute(
            select(Punishment)
            .where(
                Punishment.active.is_(True),
                Punishment.expires_at.is_not(None),
                Punishment.expires_at <= moment,
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_chat(self, chat_id: int, *, limit: int = 100) -> list[Punishment]:
        result = await self._session.execute(
            select(Punishment)
            .where(Punishment.chat_id == chat_id)
            .order_by(Punishment.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_scam_bans(self, tg_user_id: int) -> int:
        """How many distinct chats banned this user — feeds the cross-ban rule."""
        result = await self._session.execute(
            select(func.count(func.distinct(Punishment.chat_id))).where(
                Punishment.tg_user_id == tg_user_id,
                Punishment.type == PunishmentType.BAN,
                Punishment.active.is_(True),
            )
        )
        return int(result.scalar_one())


class ModerationLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        chat_id: int,
        action: str,
        tg_user_id: int | None,
        moderator_tg_id: int | None,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> ModerationLog:
        entry = ModerationLog(
            chat_id=chat_id,
            action=action,
            tg_user_id=tg_user_id,
            moderator_tg_id=moderator_tg_id,
            reason=reason,
            details=details or {},
        )
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def list_for_chat(self, chat_id: int, *, limit: int = 100) -> list[ModerationLog]:
        result = await self._session.execute(
            select(ModerationLog)
            .where(ModerationLog.chat_id == chat_id)
            .order_by(ModerationLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_since(self, chat_id: int, since: datetime) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ModerationLog)
            .where(ModerationLog.chat_id == chat_id, ModerationLog.created_at >= since)
        )
        return int(result.scalar_one())

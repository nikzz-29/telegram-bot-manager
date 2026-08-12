"""Warn, punishment and moderation-log repositories."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ModerationLog, Punishment, Warn
from db.repositories._dml import execute_dml
from shared.enums import PunishmentType
from shared.time_utils import utc_now

# `ModerationLog.moderator_tg_id` carries two shapes of "no human did this": a
# NULL, written by the expiry job and by `ModerationService.log_action`, and the
# `0` sentinel that `bot.enforcement.AUTOMATIC_MODERATOR` puts on an automatic
# warn or mute. The constant is repeated here rather than imported because the
# database layer must not depend on the bot process; both halves say why 0 is
# safe — no Telegram account has a non-positive id.
AUTOMATED_MODERATOR_ID: Final = 0


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

    async def count_issued(self, chat_id: int, since: datetime) -> int:
        """Warns handed out in a window, whether or not they still stand.

        Deliberately not `count_active`: the personal report says what the
        moderators did, and a warn that has since expired or been revoked was
        still work someone did. Served by `ix_warns_chat_user` on its `chat_id`
        prefix — one chat's rows, filtered by date in place.
        """
        result = await self._session.execute(
            select(func.count())
            .select_from(Warn)
            .where(Warn.chat_id == chat_id, Warn.created_at >= since)
        )
        return int(result.scalar_one())


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

    async def count_issued_by_type(self, chat_id: int, since: datetime) -> dict[str, int]:
        """Punishments handed out in a window, keyed by `PunishmentType` value.

        Counts rows as issued rather than as currently in force: a mute that was
        lifted early, and a re-mute that superseded an earlier one, are two
        separate things a moderator did. Keys are plain strings so the caller can
        look them up with either the enum member or its value.
        """
        result = await self._session.execute(
            select(Punishment.type, func.count())
            .where(Punishment.chat_id == chat_id, Punishment.created_at >= since)
            .group_by(Punishment.type)
        )
        return {str(punishment_type): int(total) for punishment_type, total in result.all()}


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

    async def count_since(
        self, chat_id: int, since: datetime, *, until: datetime | None = None
    ) -> int:
        """Actions logged for a chat in a window.

        `until` closes the window at the far end, which is what lets the personal
        report compare this period against the one immediately before it.
        """
        stmt = (
            select(func.count())
            .select_from(ModerationLog)
            .where(ModerationLog.chat_id == chat_id, ModerationLog.created_at >= since)
        )
        if until is not None:
            stmt = stmt.where(ModerationLog.created_at < until)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def count_by_action(
        self, chat_id: int, since: datetime, *, limit: int = 20
    ) -> list[tuple[str, int]]:
        """Action → how many, largest group first: *what* the moderation was.

        Grouping happens on the raw action string rather than on a fixed list of
        kinds, so an action a later module starts writing shows up here instead of
        quietly vanishing from the totals. Ties break on the name so the same
        window renders the same way twice.
        """
        result = await self._session.execute(
            select(ModerationLog.action, func.count().label("total"))
            .where(ModerationLog.chat_id == chat_id, ModerationLog.created_at >= since)
            .group_by(ModerationLog.action)
            .order_by(desc("total"), ModerationLog.action)
            .limit(limit)
        )
        return [(str(action), int(total)) for action, total in result.all()]

    async def count_for_moderator(self, chat_id: int, moderator_tg_id: int, since: datetime) -> int:
        """How much of a chat's moderation one person did in a window.

        Runs on `ix_moderation_logs_moderator` — `(chat_id, moderator_tg_id,
        created_at)`.

        The automated sentinel is refused instead of queried: rows the bot wrote
        by itself carry `moderator_tg_id` NULL or `0` (see
        `AUTOMATED_MODERATOR_ID`), so answering for id 0 would credit a person
        with every autoban, flood mute and expiry the software handled alone.
        """
        if moderator_tg_id <= AUTOMATED_MODERATOR_ID:
            return 0
        result = await self._session.execute(
            select(func.count())
            .select_from(ModerationLog)
            .where(
                ModerationLog.chat_id == chat_id,
                ModerationLog.moderator_tg_id == moderator_tg_id,
                ModerationLog.created_at >= since,
            )
        )
        return int(result.scalar_one())

    async def moderator_split(self, chat_id: int, since: datetime) -> dict[str, int]:
        """Split a window's actions into the bot's own work and the humans'.

        Both shapes of `AUTOMATED_MODERATOR_ID` count as automated, and neither
        may enter the distinct-moderator count — a chat where the bot handled
        everything has zero moderators at work, not one called "0". Two aggregates
        over one index scan, because the report always prints them together.
        """
        automated = ModerationLog.moderator_tg_id.is_(None) | (
            ModerationLog.moderator_tg_id <= AUTOMATED_MODERATOR_ID
        )
        by_human = ModerationLog.moderator_tg_id > AUTOMATED_MODERATOR_ID
        result = await self._session.execute(
            select(
                func.count().filter(automated),
                func.count(func.distinct(ModerationLog.moderator_tg_id)).filter(by_human),
            ).where(ModerationLog.chat_id == chat_id, ModerationLog.created_at >= since)
        )
        automated_total, moderators = result.one()
        return {"automated": int(automated_total), "moderators": int(moderators)}

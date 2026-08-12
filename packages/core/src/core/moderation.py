"""Moderation domain service.

This layer knows about warns, punishments and their expiry; it does not know
aiogram exists. Handlers translate a Telegram message into a `ModerationTarget`,
call one of these methods, and render the returned outcome. That keeps every
moderation rule testable without a Bot API.

DECISION: an expiring punishment schedules its own ARQ job here and stores the
`_job_id` on the row. Lifting early cancels that job by id, so a re-mute followed
by an early unmute cannot leave a stray job that unmutes someone hours later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from core import jobs
from core.durations import clamp_restriction, expiry_from
from core.jobs import JobName, job_id
from db.uow import UnitOfWork
from shared.enums import ModerationAction, PunishmentType, StatEventType, WarnPunishment
from shared.logging import get_logger
from shared.schemas.module_configs import ModerationConfig
from shared.time_utils import utc_now

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ModerationTarget:
    """Who is being acted on, and by whom."""

    chat_id: int
    tg_chat_id: int
    tg_user_id: int
    moderator_tg_id: int
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class WarnOutcome:
    """Result of a warn: how many are active and what it triggered."""

    count: int
    limit: int
    limit_reached: bool
    punishment: WarnPunishment | None = None
    punishment_until: str = ""


@dataclass(frozen=True, slots=True)
class PunishmentOutcome:
    """Result of a mute/ban/kick."""

    type: PunishmentType
    until: str = ""
    job: str | None = None


class ModerationService:
    """Warns, punishments and their scheduled expiry."""

    def __init__(self, uow_factory: type[UnitOfWork] = UnitOfWork) -> None:
        self._uow_factory = uow_factory

    async def _log(
        self,
        uow: UnitOfWork,
        *,
        chat_id: int,
        action: str,
        tg_user_id: int | None,
        moderator_tg_id: int | None,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Persist one moderation action in the two places that read it back.

        `moderation_logs` is the row the private report counts directly; a
        `StatEventType.MODERATION` event is what the daily rollup folds into the
        group `/stats` moderation-load chart. Both are written here, inside the
        caller's transaction, so the two views of "how much moderation happened"
        cannot drift — every logged action is one point on the chart, human or
        automatic alike.
        """
        await uow.moderation_logs.add(
            chat_id=chat_id,
            action=action,
            tg_user_id=tg_user_id,
            moderator_tg_id=moderator_tg_id,
            reason=reason,
            details=details,
        )
        await uow.stats.add_event(
            chat_id=chat_id, event_type=StatEventType.MODERATION, tg_user_id=tg_user_id
        )

    # --- warns ----------------------------------------------------------------
    async def warn(
        self, target: ModerationTarget, *, reason: str, config: ModerationConfig
    ) -> WarnOutcome:
        """Add a warn and report whether it tripped the configured punishment."""
        expires_at = expiry_from(timedelta(days=config.warn_lifetime_days))
        async with self._uow_factory() as uow:
            await uow.warns.add(
                chat_id=target.chat_id,
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
                reason=reason,
                expires_at=expires_at,
            )
            count = await uow.warns.count_active(target.chat_id, target.tg_user_id)
            await self._log(
                uow,
                chat_id=target.chat_id,
                action="warn",
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
                reason=reason,
                details={"count": count, "limit": config.warn_limit},
            )
            await uow.commit()

        if count < config.warn_limit:
            return WarnOutcome(count=count, limit=config.warn_limit, limit_reached=False)

        punishment = await self._apply_warn_punishment(target, config=config, reason=reason)
        return WarnOutcome(
            count=count,
            limit=config.warn_limit,
            limit_reached=True,
            punishment=config.warn_punishment,
            punishment_until=punishment.until,
        )

    async def _apply_warn_punishment(
        self, target: ModerationTarget, *, config: ModerationConfig, reason: str
    ) -> PunishmentOutcome:
        """DECISION: hitting the warn limit clears the warns. Otherwise every
        further message would re-trigger the punishment while the warns stand."""
        limit_reason = f"warn limit ({config.warn_limit})"
        if config.warn_punishment == WarnPunishment.BAN:
            outcome = await self.ban(target, reason=limit_reason)
        elif config.warn_punishment == WarnPunishment.KICK:
            outcome = await self.kick(target, reason=limit_reason)
        else:
            outcome = await self.mute(
                target,
                duration=timedelta(hours=config.warn_punishment_hours),
                reason=limit_reason,
            )
        async with self._uow_factory() as uow:
            await uow.warns.revoke_all(
                target.chat_id, target.tg_user_id, moderator_tg_id=target.moderator_tg_id
            )
            await uow.commit()
        logger.info(
            "moderation.warn_limit_reached",
            chat_id=target.chat_id,
            user_id=target.tg_user_id,
            punishment=config.warn_punishment.value,
            reason=reason,
        )
        return outcome

    async def unwarn(self, target: ModerationTarget) -> int:
        """Revoke the most recent warn; returns the remaining active count."""
        async with self._uow_factory() as uow:
            revoked = await uow.warns.revoke_last(
                target.chat_id, target.tg_user_id, moderator_tg_id=target.moderator_tg_id
            )
            if revoked is not None:
                await self._log(
                    uow,
                    chat_id=target.chat_id,
                    action="unwarn",
                    tg_user_id=target.tg_user_id,
                    moderator_tg_id=target.moderator_tg_id,
                )
            count = await uow.warns.count_active(target.chat_id, target.tg_user_id)
            await uow.commit()
        return count

    async def warn_count(self, chat_id: int, tg_user_id: int) -> int:
        async with self._uow_factory() as uow:
            return await uow.warns.count_active(chat_id, tg_user_id)

    # --- punishments ----------------------------------------------------------
    async def mute(
        self,
        target: ModerationTarget,
        *,
        duration: timedelta | None,
        reason: str = "",
    ) -> PunishmentOutcome:
        return await self._punish(
            target, PunishmentType.MUTE, duration=clamp_restriction(duration), reason=reason
        )

    async def ban(
        self,
        target: ModerationTarget,
        *,
        duration: timedelta | None = None,
        reason: str = "",
    ) -> PunishmentOutcome:
        return await self._punish(target, PunishmentType.BAN, duration=duration, reason=reason)

    async def kick(self, target: ModerationTarget, *, reason: str = "") -> PunishmentOutcome:
        """A kick leaves no restriction to lift, so it is logged, not scheduled."""
        async with self._uow_factory() as uow:
            await uow.punishments.add(
                chat_id=target.chat_id,
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
                punishment_type=PunishmentType.KICK,
                reason=reason,
            )
            await uow.punishments.deactivate_for_user(
                target.chat_id, target.tg_user_id, PunishmentType.KICK
            )
            await self._log(
                uow,
                chat_id=target.chat_id,
                action="kick",
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
                reason=reason,
            )
            await uow.commit()
        return PunishmentOutcome(type=PunishmentType.KICK)

    async def _punish(
        self,
        target: ModerationTarget,
        punishment_type: PunishmentType,
        *,
        duration: timedelta | None,
        reason: str,
    ) -> PunishmentOutcome:
        expires_at = expiry_from(duration)
        identifier = (
            job_id(JobName.LIFT_RESTRICTION, target.chat_id, target.tg_user_id)
            if expires_at is not None
            else None
        )

        async with self._uow_factory() as uow:
            # Supersede any live punishment of the same kind so the row set stays
            # honest and its pending lift job is not left pointing at nothing.
            previous = await uow.punishments.get_active(
                target.chat_id, target.tg_user_id, punishment_type
            )
            await uow.punishments.deactivate_for_user(
                target.chat_id, target.tg_user_id, punishment_type
            )
            await uow.punishments.add(
                chat_id=target.chat_id,
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
                punishment_type=punishment_type,
                reason=reason,
                expires_at=expires_at,
                arq_job_id=identifier,
            )
            await self._log(
                uow,
                chat_id=target.chat_id,
                action=punishment_type.value,
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
                reason=reason,
                details={"until": expires_at.isoformat() if expires_at else None},
            )
            await uow.commit()

        if previous is not None and previous.arq_job_id and previous.arq_job_id != identifier:
            await jobs.cancel(previous.arq_job_id)

        if expires_at is not None and identifier is not None:
            await jobs.schedule_at(
                JobName.LIFT_RESTRICTION,
                expires_at,
                target.tg_chat_id,
                target.tg_user_id,
                punishment_type.value,
                _id=identifier,
            )

        return PunishmentOutcome(
            type=punishment_type,
            until=expires_at.isoformat() if expires_at else "",
            job=identifier,
        )

    async def lift(self, target: ModerationTarget, punishment_type: PunishmentType) -> bool:
        """Lift a restriction early and cancel its pending expiry job."""
        async with self._uow_factory() as uow:
            active = await uow.punishments.get_active(
                target.chat_id, target.tg_user_id, punishment_type
            )
            lifted = await uow.punishments.deactivate_for_user(
                target.chat_id, target.tg_user_id, punishment_type
            )
            await self._log(
                uow,
                chat_id=target.chat_id,
                action=f"un{punishment_type.value}",
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id,
            )
            await uow.commit()
        if active is not None and active.arq_job_id:
            await jobs.cancel(active.arq_job_id)
        return bool(lifted)

    async def is_muted(self, chat_id: int, tg_user_id: int) -> bool:
        async with self._uow_factory() as uow:
            active = await uow.punishments.get_active(chat_id, tg_user_id, PunishmentType.MUTE)
        if active is None:
            return False
        return active.expires_at is None or active.expires_at > utc_now()

    # --- automatic actions ----------------------------------------------------
    async def apply_auto_action(
        self,
        target: ModerationTarget,
        action: ModerationAction,
        *,
        reason: str,
        config: ModerationConfig,
        mute_hours: int | None = None,
        mute_duration: timedelta | None = None,
    ) -> WarnOutcome | PunishmentOutcome | None:
        """Run the action a filter or stop-word rule asked for.

        Returns whatever the action produced, or `None` for delete-only, so the
        caller can report "deleted + warned 2/3" without re-deriving it.

        DECISION: `mute_duration` exists alongside `mute_hours` because anti-flood
        is configured in *minutes*. Rounding a ten-minute flood mute up to the
        nearest hour would silently punish six times harder than the admin asked.
        """
        if action == ModerationAction.DELETE:
            await self.log_action(target, action="auto_delete", reason=reason)
            return None
        if action == ModerationAction.DELETE_WARN:
            return await self.warn(target, reason=reason, config=config)
        if action == ModerationAction.DELETE_MUTE:
            duration = mute_duration or timedelta(hours=mute_hours or config.stop_word_mute_hours)
            return await self.mute(target, duration=duration, reason=reason)
        # NOTHING and ALERT_ADMINS: nothing to persist beyond the log line.
        await self.log_action(target, action=action.value, reason=reason)
        return None

    async def log_action(
        self,
        target: ModerationTarget,
        *,
        action: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            await self._log(
                uow,
                chat_id=target.chat_id,
                action=action,
                tg_user_id=target.tg_user_id,
                moderator_tg_id=target.moderator_tg_id or None,
                reason=reason,
                details=dict(details or {}),
            )
            await uow.commit()


moderation = ModerationService()

__all__ = [
    "ModerationService",
    "ModerationTarget",
    "PunishmentOutcome",
    "WarnOutcome",
    "moderation",
]

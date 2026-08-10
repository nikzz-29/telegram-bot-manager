"""Cross-ban network: one chat's scam ban becomes every chat's warning.

Spec §5.6. A user banned for scam in `global_ban_chat_threshold` distinct chats is
promoted to the platform blacklist, and chats that opted in either ban them on
sight or just hear about it.

DECISION: reports are recorded but promotion is automatic only at the threshold,
and un-banning is never automatic — an appeal goes through the operator panel.
The asymmetry is deliberate: three independent chats agreeing is decent evidence,
while one chat's opinion reversing is not evidence of innocence.

DECISION: only bans whose reason is scam-ish feed the network. A chat that bans
someone for arguing has made a local decision, and letting that propagate would
turn one moderator's grudge into a platform-wide ban. `SCAM_REASONS` is the
allow-list, and `/gban` states its reason explicitly.

DECISION: promotion invalidates the user's cached verdict immediately. The gate
middleware caches for five minutes, and a scammer working through a list of
chats does most of their damage inside that window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from core import cache, jobs
from core.jobs import JobName
from db.uow import UnitOfWork
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.module_configs import CrossbanConfig

logger = get_logger(__name__)

# Reasons that count as network evidence. Matched as substrings, lower-cased, so
# "scam:fake support" and "ai:scam" both qualify.
SCAM_REASONS: Final[tuple[str, ...]] = ("scam", "phish", "fraud", "скам", "мошен", "фишинг")


def is_network_reason(reason: str) -> bool:
    """Whether a local ban reason is the kind the network should learn from."""
    lowered = reason.lower()
    return any(token in lowered for token in SCAM_REASONS)


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    """What happened when a chat reported a ban to the network."""

    recorded: bool
    chat_count: int
    promoted: bool

    @property
    def threshold_reached(self) -> bool:
        return self.promoted


class CrossbanService:
    """Records local scam bans, promotes repeat offenders, answers the gate."""

    async def report(
        self,
        *,
        chat_id: int,
        tg_user_id: int,
        reason: str,
        reported_by: int | None = None,
        config: CrossbanConfig | None = None,
        force: bool = False,
    ) -> ReportOutcome:
        """Feed one local ban into the network, promoting it if it tips over.

        `force` is the operator path: `/gban` and the superadmin panel promote
        regardless of reason wording or contribution setting.
        """
        if config is not None and not config.contribute_bans and not force:
            return ReportOutcome(recorded=False, chat_count=0, promoted=False)
        if not force and not is_network_reason(reason):
            return ReportOutcome(recorded=False, chat_count=0, promoted=False)

        threshold = get_settings().global_ban_chat_threshold
        async with UnitOfWork() as uow:
            count = await uow.global_bans.report(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                reason=reason,
                reported_by=reported_by,
            )
            promote = force or count >= threshold
            if promote:
                await uow.global_bans.promote(
                    tg_user_id=tg_user_id, reason=reason, banned_by=reported_by
                )
            await uow.commit()

        # The gate caches its answer; a promotion that is not visible for five
        # minutes is five minutes of open door.
        await cache.invalidate_user(tg_user_id)
        if promote:
            await self._propagate(tg_user_id, reason)
            logger.info(
                "crossban.promoted",
                tg_user_id=tg_user_id,
                chat_count=count,
                threshold=threshold,
                forced=force,
            )
        else:
            logger.info("crossban.reported", tg_user_id=tg_user_id, chat_count=count)
        return ReportOutcome(recorded=True, chat_count=count, promoted=promote)

    async def _propagate(self, tg_user_id: int, reason: str) -> None:
        """Hand the fan-out to the worker.

        DECISION: enqueued, not sent inline. A promotion can happen inside a
        `/ban` handler, and banning one user across every opted-in chat is an
        unbounded number of API calls; the moderator's command must return now.
        Best-effort on purpose — the blacklist row is already written, so the
        join gate stops this user even if the fan-out never runs.
        """
        try:
            await jobs.enqueue(JobName.PROPAGATE_GLOBAL_BAN, tg_user_id, reason)
        except Exception:
            logger.exception("crossban.propagate_enqueue_failed", tg_user_id=tg_user_id)

    async def revoke(self, tg_user_id: int) -> bool:
        """Operator-only global unban (spec §5.6: appeals)."""
        async with UnitOfWork() as uow:
            revoked = await uow.global_bans.revoke(tg_user_id)
            await uow.commit()
        await cache.invalidate_user(tg_user_id)
        if revoked:
            logger.info("crossban.revoked", tg_user_id=tg_user_id)
        return revoked

    async def promote(self, *, tg_user_id: int, reason: str, banned_by: int | None = None) -> None:
        """Blacklist a user outright, without waiting for the threshold."""
        async with UnitOfWork() as uow:
            await uow.global_bans.promote(tg_user_id=tg_user_id, reason=reason, banned_by=banned_by)
            await uow.commit()
        await cache.invalidate_user(tg_user_id)
        await self._propagate(tg_user_id, reason)
        logger.info("crossban.promoted_directly", tg_user_id=tg_user_id)

    async def status(self, tg_user_id: int) -> tuple[bool, int]:
        """(is on the blacklist, how many chats have reported them)."""
        async with UnitOfWork() as uow:
            entry = await uow.global_bans.get(tg_user_id)
        if entry is None:
            return False, 0
        return entry.is_active, entry.chat_count

    def enforcement_for(self, config: CrossbanConfig) -> str:
        """What a chat wants done about a blacklisted joiner: ban, alert, off."""
        if not config.enabled:
            return "off"
        if config.alert_only or not config.autoban_on_join:
            return "alert"
        return "ban"


crossban = CrossbanService()

__all__ = [
    "SCAM_REASONS",
    "CrossbanService",
    "ReportOutcome",
    "crossban",
    "is_network_reason",
]

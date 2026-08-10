"""Join screening: raid detection and new-account heuristics.

Spec §5.2 asks for two independent defences at the door.

*Anti-raid*: N joins inside M seconds flips the chat into a lockdown — new
members are held read-only and the admins get an alert. The counter is the same
Redis sliding window the anti-flood rules use, keyed by chat instead of by user,
so it is atomic across bot processes and expires on its own.

*New-account autoban*: an account with no username, no avatar, or an id that
looks freshly minted is either bounced or pushed onto a captcha, at the admin's
choice.

DECISION: nothing here talks to Telegram. Screening takes the facts the bot
already has (username, photo count, numeric id) and returns reasons; the bot
module decides what to do with them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Final

from core import jobs
from core.anti_flood import RedisSlidingWindow
from core.jobs import JobName, job_id
from db.uow import UnitOfWork
from shared.logging import get_logger
from shared.schemas.module_configs import EntryConfig
from shared.time_utils import utc_now

logger = get_logger(__name__)

# --- account age ---------------------------------------------------------------
# DECISION: the Bot API exposes no registration date, so age can only be
# *estimated*. Telegram hands out user ids in roughly ascending order, which
# makes linear interpolation between known (id, date) pairs a serviceable
# approximation — good to a few weeks in the middle of the range, worse at the
# edges. That is why this only ever feeds an admin-enabled heuristic and never
# an automatic ban on its own: `autoban_min_account_age_days` defaults to 0.
_ANCHORS: Final[tuple[tuple[int, datetime], ...]] = (
    (2_768_409, datetime(2013, 8, 1, tzinfo=UTC)),
    (11_538_514, datetime(2014, 6, 1, tzinfo=UTC)),
    (101_260_938, datetime(2016, 1, 1, tzinfo=UTC)),
    (253_000_000, datetime(2017, 12, 1, tzinfo=UTC)),
    (427_000_000, datetime(2019, 1, 1, tzinfo=UTC)),
    (610_000_000, datetime(2019, 12, 1, tzinfo=UTC)),
    (903_000_000, datetime(2020, 8, 1, tzinfo=UTC)),
    (1_100_000_000, datetime(2020, 12, 1, tzinfo=UTC)),
    (1_500_000_000, datetime(2021, 5, 1, tzinfo=UTC)),
    (1_800_000_000, datetime(2021, 11, 1, tzinfo=UTC)),
    (2_000_000_000, datetime(2022, 4, 1, tzinfo=UTC)),
    (5_000_000_000, datetime(2022, 12, 1, tzinfo=UTC)),
    (6_000_000_000, datetime(2023, 8, 1, tzinfo=UTC)),
    (7_000_000_000, datetime(2024, 3, 1, tzinfo=UTC)),
    (7_600_000_000, datetime(2025, 2, 1, tzinfo=UTC)),
)


def estimate_registration(tg_user_id: int) -> datetime | None:
    """Approximate when an account was created, or `None` if it cannot be placed.

    Ids below the first anchor belong to accounts older than every threshold this
    feature can express, so they are reported as the first anchor's date rather
    than extrapolated backwards into nonsense.
    """
    if tg_user_id <= 0:
        return None
    if tg_user_id <= _ANCHORS[0][0]:
        return _ANCHORS[0][1]

    for (low_id, low_date), (high_id, high_date) in pairwise(_ANCHORS):
        if tg_user_id <= high_id:
            span = high_id - low_id
            ratio = (tg_user_id - low_id) / span if span else 0.0
            return low_date + (high_date - low_date) * ratio

    # Past the last anchor: extrapolate along the final segment's slope. The
    # answer drifts as the table ages, but it always says "newer than the last
    # anchor", which is the only claim the heuristic acts on.
    (prev_id, prev_date), (last_id, last_date) = _ANCHORS[-2], _ANCHORS[-1]
    per_id = (last_date - prev_date) / max(last_id - prev_id, 1)
    return last_date + per_id * (tg_user_id - last_id)


def estimate_account_age(tg_user_id: int, *, now: datetime | None = None) -> timedelta | None:
    """How old the account probably is. `None` when it cannot be estimated."""
    registered = estimate_registration(tg_user_id)
    if registered is None:
        return None
    return max((now or utc_now()) - registered, timedelta())


# --- screening -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Screening:
    """Why a joining account looks suspicious. Reasons are Fluent keys."""

    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.reasons)


def screen_account(
    *,
    tg_user_id: int,
    username: str | None,
    has_photo: bool,
    is_bot: bool = False,
    config: EntryConfig,
    now: datetime | None = None,
) -> Screening:
    """Apply the admin's new-account rules to one joining member.

    Only checks the admin switched on are evaluated: a chat that wants avatars
    but not usernames must not have anonymous-but-photographed members flagged.
    """
    if is_bot or not config.autoban_new_accounts:
        return Screening()

    reasons: list[str] = []
    if config.autoban_require_username and not username:
        reasons.append("entry-reason-no-username")
    if config.autoban_require_photo and not has_photo:
        reasons.append("entry-reason-no-photo")
    if config.autoban_min_account_age_days > 0:
        age = estimate_account_age(tg_user_id, now=now)
        if age is not None and age < timedelta(days=config.autoban_min_account_age_days):
            reasons.append("entry-reason-fresh-account")
    return Screening(tuple(reasons))


# --- anti-raid -----------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RaidVerdict:
    """The join burst that tripped the threshold."""

    joins: int
    limit: int
    window_seconds: int
    lockdown_until: datetime


class AntiRaidService:
    """Counts joins per chat and drives the lockdown window."""

    def __init__(self, window: RedisSlidingWindow | None = None) -> None:
        self._window = window or RedisSlidingWindow()

    @staticmethod
    def _key(chat_id: int) -> str:
        return f"join:{chat_id}"

    @staticmethod
    def lockdown_job_id(tg_chat_id: int) -> str:
        return job_id(JobName.END_LOCKDOWN, tg_chat_id)

    async def record_join(
        self,
        chat_id: int,
        *,
        config: EntryConfig,
        now: datetime | None = None,
    ) -> RaidVerdict | None:
        """Count one join; return a verdict when the burst is over the threshold.

        Returns `None` when anti-raid is off or the chat is still inside its
        limit. The caller is expected to skip this entirely while a lockdown is
        already running — re-alerting every join during a raid is noise.
        """
        if not config.anti_raid_enabled:
            return None

        window = timedelta(seconds=config.anti_raid_seconds)
        joins = await self._window.hit(self._key(chat_id), window=window)
        if joins < config.anti_raid_joins:
            return None

        until = (now or utc_now()) + timedelta(minutes=config.anti_raid_lockdown_minutes)
        return RaidVerdict(
            joins=joins,
            limit=config.anti_raid_joins,
            window_seconds=config.anti_raid_seconds,
            lockdown_until=until,
        )

    async def begin_lockdown(self, chat_id: int, tg_chat_id: int, *, until: datetime) -> None:
        """Persist the lockdown and arm the job that ends it.

        DECISION: the window lives on the chat row rather than in Redis. Every
        update already reads that row to build its `ChatContext`, so the gate
        costs nothing extra, and a Redis flush cannot silently unlock a chat
        mid-raid.
        """
        async with UnitOfWork() as uow:
            await uow.chats.set_lockdown(chat_id, until)

        ident = self.lockdown_job_id(tg_chat_id)
        await jobs.cancel(ident)
        await jobs.schedule_at(JobName.END_LOCKDOWN, until, tg_chat_id, _id=ident)
        # A fresh window: the joins that triggered this are dealt with, and the
        # counter should measure the *next* burst, not keep re-firing on this one.
        await self._window.reset(self._key(chat_id))
        logger.warning(
            "entry.lockdown_started",
            chat_id=chat_id,
            tg_chat_id=tg_chat_id,
            until=until.isoformat(),
        )

    async def end_lockdown(self, chat_id: int, tg_chat_id: int) -> None:
        """Lift a lockdown — from the job, or from `/lockdown off`.

        DECISION: accounts held during the lockdown are *not* released here. They
        were restricted with a Telegram `until_date`, so Telegram lifts each one
        at its own expiry; unmuting them early would hand a raider the floor the
        moment the window closed. An admin can still `/unmute` a specific person.
        """
        async with UnitOfWork() as uow:
            await uow.chats.set_lockdown(chat_id, None)
        await jobs.cancel(self.lockdown_job_id(tg_chat_id))
        logger.info("entry.lockdown_ended", chat_id=chat_id, tg_chat_id=tg_chat_id)

    async def joins_in_window(self, chat_id: int) -> int:
        """Current occupancy of the join window — diagnostics and `/lockdown`."""
        return await self._window.count(self._key(chat_id))


anti_raid = AntiRaidService()

__all__ = [
    "AntiRaidService",
    "RaidVerdict",
    "Screening",
    "anti_raid",
    "estimate_account_age",
    "estimate_registration",
    "screen_account",
]

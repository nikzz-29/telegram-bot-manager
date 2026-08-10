"""Reputation and activity levels.

Spec §5.6 — members thank each other with `+`, `спасибо`, `thanks` (or whatever
the admin configures) and the recipient gains a point; messages accumulate
experience, and experience buys levels with admin-nameable titles.

DECISION: the anti-farm guards live in Redis, not in the database. A cooldown and
a daily cap are read on every candidate message, and a Postgres round-trip per
`+` in a busy chat is exactly the cost this design exists to avoid. Both keys
expire on their own, so nothing has to be cleaned up.

DECISION: giving reputation to yourself, to a bot, or twice to the same person
inside the cooldown is silently ignored rather than answered. A chat where every
blocked `+` produces a bot message is worse than one where the point simply does
not land, and an answer would also confirm the cooldown's length to a farmer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import re
from typing import Final

from redis.asyncio import Redis

from core.redis_client import get_redis
from core.stop_words import normalize
from db.uow import UnitOfWork
from shared.logging import get_logger
from shared.schemas.module_configs import EngagementConfig

logger = get_logger(__name__)

KEY_PREFIX: Final = "tgm:rep"

# Experience needed to reach level N, as a quadratic curve: 100, 300, 600, 1000…
# DECISION: a formula rather than a table. Admins name the levels they care
# about (`level_titles`) and the curve keeps producing sensible thresholds past
# the last name instead of capping progression at whatever the table holds.
LEVEL_STEP: Final = 100
MAX_LEVEL: Final = 100


class RepOutcome(StrEnum):
    """Why a reputation attempt did or did not land."""

    GRANTED = "granted"
    SELF = "self"
    BOT = "bot"
    COOLDOWN = "cooldown"
    DAILY_LIMIT = "daily_limit"


@dataclass(frozen=True, slots=True)
class RepResult:
    """What happened, and the recipient's standing afterwards."""

    outcome: RepOutcome
    points: int = 0
    level: int = 1
    level_up: bool = False

    @property
    def granted(self) -> bool:
        return self.outcome is RepOutcome.GRANTED


def level_threshold(level: int) -> int:
    """Total experience required to *be* at `level`. Level 1 starts at zero."""
    if level <= 1:
        return 0
    return LEVEL_STEP * (level - 1) * level // 2


def level_for(experience: int) -> int:
    """The level a given amount of experience buys."""
    if experience < LEVEL_STEP:
        return 1
    level = 1
    while level < MAX_LEVEL and experience >= level_threshold(level + 1):
        level += 1
    return level


def level_title(level: int, config: EngagementConfig) -> str:
    """The admin's name for a level, or an empty string when unnamed.

    Titles are keyed by level number as a string, because JSONB object keys are
    strings and the config round-trips through JSON.
    """
    return config.level_titles.get(str(level), "").strip()


@lru_cache(maxsize=512)
def _keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str] | None:
    """One alternation matching any thanks keyword at the start of a message.

    DECISION: anchored at the start. `+` mid-sentence is punctuation far more
    often than praise, and requiring the message to *begin* with the token is
    what every established reputation bot does — it is the convention users
    already know.
    """
    parts: list[str] = []
    for keyword in keywords:
        cleaned = normalize(keyword).strip()
        if not cleaned:
            continue
        escaped = re.escape(cleaned)
        # Word-boundary only where the keyword ends in a letter or digit: `+`
        # must still match when followed by nothing at all.
        suffix = r"\b" if cleaned[-1:].isalnum() else ""
        parts.append(f"{escaped}{suffix}")
    if not parts:
        return None
    return re.compile(rf"\A\s*(?:{'|'.join(parts)})", re.IGNORECASE)


def is_thanks(text: str, config: EngagementConfig) -> bool:
    """Whether this message reads as giving reputation."""
    if not text:
        return False
    pattern = _keyword_pattern(tuple(sorted(config.reputation_keywords)))
    if pattern is None:
        return False
    return pattern.search(normalize(text)) is not None


class ReputationService:
    """Grants points under a cooldown and a daily cap, and tracks levels."""

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    def _client(self) -> Redis:
        return self._redis if self._redis is not None else get_redis()

    @staticmethod
    def _cooldown_key(chat_id: int, giver_id: int, receiver_id: int) -> str:
        return f"{KEY_PREFIX}:cd:{chat_id}:{giver_id}:{receiver_id}"

    @staticmethod
    def _daily_key(chat_id: int, giver_id: int) -> str:
        return f"{KEY_PREFIX}:day:{chat_id}:{giver_id}"

    async def _within_cooldown(
        self, chat_id: int, giver_id: int, receiver_id: int, *, seconds: int
    ) -> bool:
        """Claim the giver→receiver pair for `seconds`. True when already claimed."""
        if seconds <= 0:
            return False
        key = self._cooldown_key(chat_id, giver_id, receiver_id)
        claimed = await self._client().set(key, b"1", ex=seconds, nx=True)
        return not bool(claimed)

    async def _over_daily_limit(self, chat_id: int, giver_id: int, *, limit: int) -> bool:
        """Count one grant against the giver's daily allowance.

        The key expires 24h after the *first* grant of the run, which is a
        rolling day rather than a calendar one — simpler, and it cannot be gamed
        by waiting for midnight in an unknown timezone.
        """
        key = self._daily_key(chat_id, giver_id)
        client = self._client()
        used = int(await client.incr(key))
        if used == 1:
            await client.expire(key, 86_400)
        return used > limit

    async def grant(
        self,
        *,
        chat_id: int,
        giver_id: int,
        receiver_id: int,
        receiver_is_bot: bool,
        config: EngagementConfig,
    ) -> RepResult:
        """Give one reputation point, if every guard allows it."""
        if giver_id == receiver_id:
            return RepResult(RepOutcome.SELF)
        if receiver_is_bot:
            return RepResult(RepOutcome.BOT)
        if await self._within_cooldown(
            chat_id, giver_id, receiver_id, seconds=config.reputation_cooldown_seconds
        ):
            return RepResult(RepOutcome.COOLDOWN)
        if await self._over_daily_limit(chat_id, giver_id, limit=config.reputation_daily_limit):
            return RepResult(RepOutcome.DAILY_LIMIT)

        # DECISION: a point does not move the level. Levels are bought with
        # experience, which messages earn; keeping the two ledgers separate means
        # a popular member cannot skip the activity requirement and a quiet one
        # cannot be levelled up by friends.
        async with UnitOfWork() as uow:
            row = await uow.reputation.add_points(chat_id=chat_id, tg_user_id=receiver_id, delta=1)
            await uow.commit()

        logger.debug("reputation.granted", chat_id=chat_id, giver=giver_id, receiver=receiver_id)
        return RepResult(RepOutcome.GRANTED, points=row.points, level=row.level)

    async def add_activity(
        self, *, chat_id: int, tg_user_id: int, config: EngagementConfig
    ) -> RepResult | None:
        """Award experience for a message. Returns a result only on a level-up.

        DECISION: only level-ups come back. The caller wants to know when to
        congratulate someone; returning a result for every message would invite a
        database write on the hot path to be *read*, which is the one thing this
        must not encourage.
        """
        if not config.levels_enabled or config.points_per_message < 1:
            return None

        async with UnitOfWork() as uow:
            current = await uow.reputation.get(chat_id, tg_user_id)
            before = current.level if current is not None else 1
            row = await uow.reputation.add_experience(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                delta=config.points_per_message,
                level=before,
            )
            after = level_for(row.experience)
            if after == before:
                await uow.commit()
                return None
            await uow.reputation.set_level(chat_id=chat_id, tg_user_id=tg_user_id, level=after)
            await uow.commit()

        logger.info("reputation.level_up", chat_id=chat_id, user_id=tg_user_id, level=after)
        return RepResult(RepOutcome.GRANTED, points=row.points, level=after, level_up=True)

    async def standing(self, chat_id: int, tg_user_id: int) -> tuple[int, int, int, int | None]:
        """`(points, experience, level, rank)` for `/rep`."""
        async with UnitOfWork() as uow:
            row = await uow.reputation.get(chat_id, tg_user_id)
            if row is None:
                return 0, 0, 1, None
            rank = await uow.reputation.rank(chat_id, tg_user_id)
        return row.points, row.experience, row.level, rank

    async def leaderboard(
        self, chat_id: int, *, limit: int = 10, field: str = "points"
    ) -> list[tuple[int, int, int]]:
        """`(tg_user_id, points, level)` rows for `/top`, best first."""
        async with UnitOfWork() as uow:
            rows = await uow.reputation.top(chat_id, limit=limit, field=field)
        return [(row.tg_user_id, row.points, row.level) for row in rows]


def next_level_progress(experience: int) -> tuple[int, int]:
    """`(earned, needed)` inside the current level — the `/rep` progress line."""
    level = level_for(experience)
    if level >= MAX_LEVEL:
        return 0, 0
    floor = level_threshold(level)
    ceiling = level_threshold(level + 1)
    return experience - floor, ceiling - floor


reputation = ReputationService()

__all__ = [
    "LEVEL_STEP",
    "MAX_LEVEL",
    "RepOutcome",
    "RepResult",
    "ReputationService",
    "is_thanks",
    "level_for",
    "level_threshold",
    "level_title",
    "next_level_progress",
    "reputation",
]

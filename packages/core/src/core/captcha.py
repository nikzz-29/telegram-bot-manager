"""Captcha challenges — the join gate's brain.

Spec §5.2: a joining member is read-only until they prove they are human, with a
timeout that kicks them (an ARQ job, never a sleeping task). Three kinds: a plain
button, "press this emoji", and a small sum.

DECISION: this layer generates and grades challenges but never speaks Telegram.
It hands back a `Challenge` describing the question and its buttons; the bot
module renders it. That makes every rule here — how many attempts, what counts as
a correct answer, when a challenge stops existing — testable without a Bot API.

DECISION: the pending-challenge marker lives in Redis with a TTL alongside the
row. The captcha gate consults it on every message in a chat with captcha on, and
that has to be one cheap round-trip rather than a query. The row stays the record
of truth; the marker is a cache that expires on its own if a job is ever lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import secrets
from typing import Any, Final

from redis.asyncio import Redis

from core import jobs
from core.jobs import JobName, job_id
from core.redis_client import get_redis
from db.models import CaptchaChallenge
from db.uow import UnitOfWork
from shared.enums import CaptchaKind
from shared.logging import get_logger
from shared.time_utils import utc_now

logger = get_logger(__name__)

MARKER_PREFIX: Final = "tgm:captcha"

# Three strikes. With four visible options a fourth guess is a coin flip, which
# would make the whole gate decorative.
MAX_ATTEMPTS: Final = 3

# Deliberately unmistakable at thumbnail size — the point is that a human reads
# the prompt, not that the pictures are hard to tell apart.
EMOJI_POOL: Final[tuple[str, ...]] = (
    "🐱",
    "🐶",
    "🐘",
    "🦊",
    "🐼",
    "🐧",
    "🦁",
    "🐸",
    "🐨",
    "🐷",
)
EMOJI_CHOICES: Final = 5
MATH_CHOICES: Final = 4

_rng: Final = secrets.SystemRandom()


@dataclass(frozen=True, slots=True)
class CaptchaOption:
    """One button. `label_is_key` marks a label that needs translating.

    Emoji and numbers are the same in every language and travel as-is; the plain
    button's wording is a Fluent key the bot resolves in the chat's language.
    """

    label: str
    token: str
    label_is_key: bool = False


@dataclass(frozen=True, slots=True)
class Challenge:
    """A question, its buttons, the expected token and when it stops counting."""

    kind: CaptchaKind
    prompt_key: str
    answer: str
    expires_at: datetime
    options: tuple[CaptchaOption, ...] = ()
    prompt_args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CaptchaResult:
    """The outcome of one button press."""

    solved: bool = False
    exhausted: bool = False
    unknown: bool = False
    attempts: int = 0
    remaining: int = 0
    message_id: int | None = None

    @property
    def retry(self) -> bool:
        """Wrong answer, but the user still has attempts left."""
        return not self.solved and not self.exhausted and not self.unknown


def _button(expires_at: datetime) -> Challenge:
    token = secrets.token_hex(4)
    return Challenge(
        kind=CaptchaKind.BUTTON,
        prompt_key="captcha-prompt-button",
        answer=token,
        expires_at=expires_at,
        options=(CaptchaOption(label="captcha-button-confirm", token=token, label_is_key=True),),
    )


def _emoji(expires_at: datetime) -> Challenge:
    shown = _rng.sample(EMOJI_POOL, EMOJI_CHOICES)
    target = _rng.choice(shown)
    return Challenge(
        kind=CaptchaKind.EMOJI,
        prompt_key="captcha-prompt-emoji",
        answer=target,
        expires_at=expires_at,
        options=tuple(CaptchaOption(label=emoji, token=emoji) for emoji in shown),
        prompt_args={"emoji": target},
    )


def _math(expires_at: datetime) -> Challenge:
    left, right = _rng.randrange(2, 10), _rng.randrange(2, 10)
    total = left + right
    # Distractors sit next to the answer so the right button cannot be guessed
    # by picking the largest or smallest number on screen.
    nearby = [total + offset for offset in (-4, -3, -2, -1, 1, 2, 3, 4) if total + offset > 0]
    options = [total, *_rng.sample(nearby, MATH_CHOICES - 1)]
    _rng.shuffle(options)
    return Challenge(
        kind=CaptchaKind.MATH,
        prompt_key="captcha-prompt-math",
        answer=str(total),
        expires_at=expires_at,
        options=tuple(CaptchaOption(label=str(value), token=str(value)) for value in options),
        prompt_args={"left": left, "right": right},
    )


def build(kind: CaptchaKind, *, timeout: timedelta, now: datetime | None = None) -> Challenge:
    """Generate a fresh challenge of the requested kind."""
    expires_at = (now or utc_now()) + timeout
    if kind is CaptchaKind.EMOJI:
        return _emoji(expires_at)
    if kind is CaptchaKind.MATH:
        return _math(expires_at)
    return _button(expires_at)


class CaptchaService:
    """Issues, grades and retires challenges.

    DECISION: the caller sends the prompt *before* calling `start`, because the
    row wants the prompt's `message_id` and Telegram only gives it once the
    message exists. A row without its message id would leave the timeout job
    unable to clean the prompt up. The window this opens — a user pressing the
    button in the milliseconds before the row lands — resolves as `unknown`,
    which is the same answer a stranger's press gets, and the prompt is still
    on screen to press again.
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self._redis = redis

    def _client(self) -> Redis:
        return self._redis if self._redis is not None else get_redis()

    @staticmethod
    def _marker(chat_id: int, tg_user_id: int) -> str:
        return f"{MARKER_PREFIX}:{chat_id}:{tg_user_id}"

    @staticmethod
    def timeout_job_id(tg_chat_id: int, tg_user_id: int) -> str:
        """Deterministic, so a rejoin cancels the previous timeout exactly."""
        return job_id(JobName.CAPTCHA_TIMEOUT, tg_chat_id, tg_user_id)

    async def is_pending(self, chat_id: int, tg_user_id: int) -> bool:
        """One Redis round-trip, called for every message in a captcha chat.

        DECISION: fails *open*. A Redis outage must not turn into a chat where
        nobody can speak — and a pending user is already muted in Telegram, so
        this gate is the second lock, not the only one.
        """
        try:
            return bool(await self._client().exists(self._marker(chat_id, tg_user_id)))
        except Exception as exc:
            # Availability beats strictness here; see the docstring.
            logger.warning("captcha.marker_unavailable", error=str(exc))
            return False

    async def _mark(self, chat_id: int, tg_user_id: int, *, ttl: timedelta) -> None:
        seconds = max(int(ttl.total_seconds()), 1)
        try:
            await self._client().setex(self._marker(chat_id, tg_user_id), seconds, b"1")
        except Exception as exc:
            logger.warning("captcha.marker_write_failed", error=str(exc))

    async def _unmark(self, chat_id: int, tg_user_id: int) -> None:
        try:
            await self._client().delete(self._marker(chat_id, tg_user_id))
        except Exception as exc:
            logger.warning("captcha.marker_clear_failed", error=str(exc))

    async def unmark(self, chat_id: int, tg_user_id: int) -> None:
        """Clear the gate marker — the timeout job settles the row itself."""
        await self._unmark(chat_id, tg_user_id)

    async def start(
        self,
        *,
        chat_id: int,
        tg_chat_id: int,
        tg_user_id: int,
        challenge: Challenge,
        message_id: int | None,
        ttl: timedelta,
    ) -> CaptchaChallenge:
        """Persist a challenge, arm its timeout job and set the pending marker.

        `ttl` is the challenge's own lifetime, not a call deadline — it decides
        when the timeout job fires and how long the Redis marker survives.
        """
        ident = self.timeout_job_id(tg_chat_id, tg_user_id)
        # A rejoin reuses the id, and ARQ refuses to queue a duplicate: without
        # this the *old* deferral would stand and the new timeout never fire.
        await jobs.cancel(ident)

        async with UnitOfWork() as uow:
            row = await uow.captcha.create(
                chat_id=chat_id,
                tg_user_id=tg_user_id,
                kind=challenge.kind.value,
                answer=challenge.answer,
                expires_at=challenge.expires_at,
                message_id=message_id,
                arq_job_id=ident,
            )

        # The marker outlives the challenge slightly: the timeout job clears it,
        # and the TTL is only the backstop for a job Redis lost.
        await self._mark(chat_id, tg_user_id, ttl=ttl + timedelta(minutes=1))
        await jobs.schedule_at(
            JobName.CAPTCHA_TIMEOUT,
            challenge.expires_at,
            tg_chat_id,
            tg_user_id,
            _id=ident,
        )
        logger.info(
            "captcha.issued",
            chat_id=chat_id,
            user_id=tg_user_id,
            kind=challenge.kind.value,
            expires_at=challenge.expires_at.isoformat(),
        )
        return row

    async def verify(
        self,
        *,
        chat_id: int,
        tg_chat_id: int,
        tg_user_id: int,
        token: str,
    ) -> CaptchaResult:
        """Grade one press.

        `unknown` covers both "no challenge here" and "already solved" — from the
        presser's side they are the same situation, and telling the two apart
        would leak whether a given account is pending.
        """
        async with UnitOfWork() as uow:
            row = await uow.captcha.get_pending(chat_id, tg_user_id)
            if row is None:
                return CaptchaResult(unknown=True)

            message_id = row.message_id
            if row.answer == token:
                await uow.captcha.mark_solved(row.id)
                solved = True
                attempts = row.attempts
            else:
                attempts = await uow.captcha.increment_attempts(row.id)
                solved = False

        exhausted = not solved and attempts >= MAX_ATTEMPTS
        if solved or exhausted:
            # Either way the challenge is over: retire the timeout job so it does
            # not kick someone who has just passed, and drop the gate marker.
            await jobs.cancel(self.timeout_job_id(tg_chat_id, tg_user_id))
            await self._unmark(chat_id, tg_user_id)
        if exhausted:
            async with UnitOfWork() as uow:
                await uow.captcha.delete(chat_id, tg_user_id)

        logger.info(
            "captcha.verified",
            chat_id=chat_id,
            user_id=tg_user_id,
            solved=solved,
            attempts=attempts,
        )
        return CaptchaResult(
            solved=solved,
            exhausted=exhausted,
            attempts=attempts,
            remaining=max(MAX_ATTEMPTS - attempts, 0),
            message_id=message_id,
        )

    async def discard(self, *, chat_id: int, tg_chat_id: int, tg_user_id: int) -> int | None:
        """Drop a challenge without grading it — timeout, kick, or an admin pass.

        Returns the prompt's message id so the caller can delete it.
        """
        async with UnitOfWork() as uow:
            row = await uow.captcha.get_pending(chat_id, tg_user_id)
            message_id = row.message_id if row is not None else None
            await uow.captcha.delete(chat_id, tg_user_id)

        await jobs.cancel(self.timeout_job_id(tg_chat_id, tg_user_id))
        await self._unmark(chat_id, tg_user_id)
        return message_id

    async def pending_for(self, chat_id: int, tg_user_id: int) -> CaptchaChallenge | None:
        """The authoritative check, for the paths that can afford a query."""
        async with UnitOfWork() as uow:
            return await uow.captcha.get_pending(chat_id, tg_user_id)


captcha = CaptchaService()

__all__ = [
    "EMOJI_POOL",
    "MARKER_PREFIX",
    "MAX_ATTEMPTS",
    "CaptchaOption",
    "CaptchaResult",
    "CaptchaService",
    "Challenge",
    "build",
    "captcha",
]

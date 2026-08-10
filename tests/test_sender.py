"""Sender, rate-limit and job-helper unit tests.

The Bot API and Redis are both faked here: these assert the sender's *policy*
(ordering, retry classification, backoff, dead-lettering), which is the part
that must not drift. The Redis Lua path is exercised in the integration suite.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage
import pytest

from core.jobs import JobName, job_id
from core.rate_limit import BucketResult, BucketSpec, chat_bucket, global_bucket
from core.sender import MAX_ATTEMPTS, MessageSender, SendPriority, SendResult

CHAT = -1001999888777
USER_CHAT = 424242


class FakeBucket:
    """In-memory stand-in for the Redis token bucket."""

    def __init__(self, *, allow: bool = True, retry_after: float = 0.01) -> None:
        self.allow = allow
        self.retry_after = retry_after
        self.consumed: list[tuple[str, int]] = []
        self.returned: list[str] = []

    async def consume(self, spec: BucketSpec, tokens: int = 1) -> BucketResult:
        self.consumed.append((spec.key, tokens))
        return BucketResult(allowed=self.allow, retry_after=self.retry_after)

    async def consume_all(self, specs: tuple[BucketSpec, ...], tokens: int = 1) -> BucketResult:
        for spec in specs:
            result = await self.consume(spec, tokens)
            if not result.allowed:
                return result
        return BucketResult(allowed=True, retry_after=0.0)

    async def give_back(self, spec: BucketSpec, tokens: int = 1) -> None:
        self.returned.append(spec.key)


class FakeBot:
    """Records calls; `script` queues exceptions to raise per message text."""

    def __init__(self, script: dict[str, list[Exception]] | None = None) -> None:
        self.calls: list[str] = []
        self.script = script or {}

    async def __call__(self, method: Any) -> str:
        text = getattr(method, "text", type(method).__name__)
        queued = self.script.get(text)
        if queued:
            raise queued.pop(0)
        self.calls.append(text)
        return f"sent::{text}"


def _sender(bot: FakeBot, **kwargs: Any) -> MessageSender:
    # One worker keeps ordering deterministic and observable.
    return MessageSender(bot, workers=1, buckets=FakeBucket(), **kwargs)  # type: ignore[arg-type]


def _msg(text: str, chat_id: int = CHAT) -> SendMessage:
    return SendMessage(chat_id=chat_id, text=text)


async def _drain(sender: MessageSender, limit: float = 3.0) -> None:
    """Wait until the sender has nothing queued, parked or in flight."""
    async with asyncio.timeout(limit):
        await sender.join()


# --- priority -----------------------------------------------------------------
async def test_moderation_outranks_broadcast_regardless_of_arrival_order() -> None:
    bot = FakeBot()
    sender = _sender(bot)
    sender.enqueue(_msg("broadcast"), chat_id=CHAT, priority=SendPriority.BROADCAST)
    sender.enqueue(_msg("trigger"), chat_id=CHAT, priority=SendPriority.TRIGGER)
    sender.enqueue(_msg("ban"), chat_id=CHAT, priority=SendPriority.MODERATION)
    sender.enqueue(_msg("system"), chat_id=CHAT, priority=SendPriority.SYSTEM)

    await sender.start()
    await _drain(sender)
    await sender.stop()

    assert bot.calls == ["ban", "system", "trigger", "broadcast"]


async def test_same_priority_keeps_arrival_order() -> None:
    bot = FakeBot()
    sender = _sender(bot)
    for index in range(5):
        sender.enqueue(_msg(f"m{index}"), chat_id=CHAT, priority=SendPriority.REPLY)

    await sender.start()
    await _drain(sender)
    await sender.stop()

    assert bot.calls == ["m0", "m1", "m2", "m3", "m4"]


async def test_call_returns_the_api_result() -> None:
    bot = FakeBot()
    sender = _sender(bot)
    await sender.start()
    assert await sender.call(_msg("needs-id"), chat_id=CHAT) == "sent::needs-id"
    await sender.stop()


async def test_broadcast_queues_one_call_per_chat() -> None:
    bot = FakeBot()
    sender = _sender(bot)
    targets = [(-100 - index, _msg(f"news{index}", -100 - index)) for index in range(3)]
    assert sender.broadcast(targets) == 3

    await sender.start()
    await _drain(sender)
    await sender.stop()

    assert sorted(bot.calls) == ["news0", "news1", "news2"]


# --- error classification -----------------------------------------------------
@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(method=None, message="bot was kicked"),  # type: ignore[arg-type]
        TelegramBadRequest(method=None, message="message to delete not found"),  # type: ignore[arg-type]
    ],
)
async def test_permanent_errors_are_dropped_without_retrying(error: Exception) -> None:
    bot = FakeBot({"gone": [error]})
    sender = _sender(bot)
    await sender.start()

    assert await sender.call(_msg("gone"), chat_id=CHAT) is None
    await sender.stop()

    assert bot.calls == []  # never attempted a second time
    assert sender.dropped == 1


@pytest.mark.parametrize(
    "error",
    [
        TelegramServerError(method=None, message="502 Bad Gateway"),  # type: ignore[arg-type]
        TelegramNetworkError(method=None, message="connection reset"),  # type: ignore[arg-type]
    ],
)
async def test_transient_errors_are_retried_then_succeed(error: Exception) -> None:
    bot = FakeBot({"flaky": [error]})
    sender = _sender(bot)
    await sender.start()

    assert await sender.call(_msg("flaky"), chat_id=CHAT) == "sent::flaky"
    await sender.stop()

    assert bot.calls == ["flaky"]
    assert sender.sent == 1


async def test_flood_control_waits_and_then_delivers() -> None:
    bot = FakeBot({"hot": [TelegramRetryAfter(method=None, message="429", retry_after=1)]})  # type: ignore[arg-type]
    sender = _sender(bot)
    await sender.start()

    assert await sender.call(_msg("hot"), chat_id=CHAT) == "sent::hot"
    await sender.stop()

    assert bot.calls == ["hot"]


async def test_repeated_failures_end_in_a_dead_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    """After MAX_ATTEMPTS the envelope is abandoned and the caller is unblocked."""
    recorded: list[tuple[str, int, str]] = []
    original = MessageSender._dead_letter

    async def spy(self: MessageSender, envelope: Any, reason: str) -> None:
        recorded.append((envelope.name, envelope.attempts, reason))
        # Skip the Redis write; keep the drop accounting and future resolution.
        self.dropped += 1
        MessageSender._finish(envelope, SendResult(ok=False, error=reason))

    monkeypatch.setattr(MessageSender, "_dead_letter", spy)
    assert original is not MessageSender._dead_letter

    bot = FakeBot({"doomed": [TelegramServerError(method=None, message="500")] * 8})  # type: ignore[arg-type]
    sender = _sender(bot)
    await sender.start()

    assert await sender.call(_msg("doomed"), chat_id=CHAT) is None
    await sender.stop()

    assert len(recorded) == 1
    name, attempts, reason = recorded[0]
    assert name == "SendMessage"
    assert attempts == MAX_ATTEMPTS
    assert "500" in reason
    assert bot.calls == []
    assert sender.dropped == 1


async def test_join_waits_for_deferred_work_not_just_the_queue() -> None:
    """A parked (rate-limited) envelope must keep the sender from reading idle."""
    bot = FakeBot()
    buckets = FakeBucket(allow=False, retry_after=0.2)
    sender = MessageSender(bot, workers=1, buckets=buckets)  # type: ignore[arg-type]
    sender.enqueue(_msg("deferred"), chat_id=CHAT)

    await sender.start()
    await asyncio.sleep(0.05)  # long enough for the worker to park it
    assert sender.pending == 1
    assert bot.calls == []

    buckets.allow = True
    await _drain(sender)
    await sender.stop()

    assert bot.calls == ["deferred"]
    assert sender.pending == 0


# --- rate limiting ------------------------------------------------------------
async def test_private_chats_skip_the_per_group_bucket() -> None:
    """The 20/min ceiling is a group rule; DMs must not inherit it."""
    bot = FakeBot()
    buckets = FakeBucket()
    sender = MessageSender(bot, workers=1, buckets=buckets)  # type: ignore[arg-type]
    sender.enqueue(_msg("dm", USER_CHAT), chat_id=USER_CHAT)
    sender.enqueue(_msg("group", CHAT), chat_id=CHAT)

    await sender.start()
    await _drain(sender)
    await sender.stop()

    keys = [key for key, _ in buckets.consumed]
    assert keys.count("global") == 2
    assert keys.count(f"chat:{CHAT}") == 1
    assert f"chat:{USER_CHAT}" not in keys


def test_bucket_specs_encode_the_documented_telegram_limits() -> None:
    assert global_bucket(30) == BucketSpec(key="global", capacity=30, refill_per_second=30.0)
    per_chat = chat_bucket(CHAT, 20)
    assert per_chat.capacity == 20
    assert per_chat.refill_per_second == pytest.approx(1 / 3)


@pytest.mark.parametrize(("capacity", "rate"), [(0, 1.0), (-1, 1.0), (10, 0.0), (10, -2.0)])
def test_bucket_spec_rejects_nonsense(capacity: int, rate: float) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        BucketSpec(key="x", capacity=capacity, refill_per_second=rate)


# --- jobs ---------------------------------------------------------------------
def test_job_ids_are_deterministic_per_subject() -> None:
    """Same subject → same id → ARQ dedupes the second schedule."""
    first = job_id(JobName.LIFT_RESTRICTION, CHAT, 555)
    assert first == job_id(JobName.LIFT_RESTRICTION, CHAT, 555)
    assert first != job_id(JobName.LIFT_RESTRICTION, CHAT, 556)
    assert first.startswith("lift_restriction:")


def test_job_id_without_parts_is_the_bare_name() -> None:
    assert job_id(JobName.EXPIRE_SUBSCRIPTIONS) == "expire_subscriptions"


def test_every_job_name_is_unique() -> None:
    values = [member.value for member in JobName]
    assert len(values) == len(set(values))

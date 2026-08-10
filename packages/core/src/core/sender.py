"""MessageSender — the single way anything leaves this bot.

Every outgoing Telegram call is queued here rather than awaited at the call site.
That buys four things no scattered `message.answer()` can:

* **Priority.** A ban confirmation must not queue behind a 5000-chat broadcast.
* **Rate limiting.** One shared Redis token bucket keeps every process inside
  Telegram's ~30 msg/s global and ~20 msg/min per-group ceilings.
* **Retries.** `TelegramRetryAfter`, network blips and 5xx are retried with
  backoff; permanent errors are dropped once, not hammered.
* **Observability.** One place that knows what was sent, dropped and why.

DECISION: work is described by aiogram `TelegramMethod` objects (`SendMessage`,
`RestrictChatMember`, …) rather than a wrapper per call. Any Bot API method works
without touching this file, and `await bot(method)` is the only call site.

DECISION: the delay queue is a heap drained by one scheduler loop, not a task per
deferred item. A rate-limited chat parks its message and frees the worker
instead of blocking it, and a raid cannot spawn thousands of timers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from enum import IntEnum
import heapq
import json
import time
from typing import Any, Final, TypeVar

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import TelegramMethod
import structlog

from core.rate_limit import BucketSpec, TokenBucket, chat_bucket, global_bucket, token_bucket
from core.redis_client import get_redis
from shared.config import get_settings

logger = structlog.get_logger(__name__)

T = TypeVar("T")

DEAD_LETTER_KEY: Final = "tgm:sender:dead"
DEAD_LETTER_MAX: Final = 1000
MAX_ATTEMPTS: Final = 4
BASE_BACKOFF: Final = 0.5
MAX_BACKOFF: Final = 30.0
# Below this, waiting in the worker is cheaper than a heap round-trip.
INLINE_WAIT_CEILING: Final = 0.05


class SendPriority(IntEnum):
    """Lower value ships first.

    Moderation outranks everything: a mute notice is worthless if it arrives
    after the flood it was answering.
    """

    MODERATION = 0
    SYSTEM = 1
    REPLY = 2
    TRIGGER = 3
    BROADCAST = 4


@dataclass(slots=True)
class SendResult:
    """What became of one queued call."""

    ok: bool
    value: Any = None
    error: str | None = None


@dataclass(slots=True)
class _Envelope:
    """One queued Telegram call and its retry state."""

    method: TelegramMethod[Any]
    chat_id: int
    priority: SendPriority
    attempts: int = 0
    future: asyncio.Future[Any] | None = None
    ready_at: float = 0.0

    @property
    def name(self) -> str:
        return type(self.method).__name__


@dataclass(order=True, slots=True)
class _QueueItem:
    """Priority tuple; `seq` keeps FIFO order inside one priority band."""

    priority: int
    seq: int
    envelope: _Envelope = field(compare=False)


class MessageSender:
    """Priority queue in front of the Bot API, rate-limited across processes."""

    def __init__(
        self,
        bot: Bot | None = None,
        *,
        workers: int | None = None,
        buckets: TokenBucket | None = None,
    ) -> None:
        settings = get_settings()
        self._bot = bot
        self._workers_count = workers or settings.sender_workers
        self._buckets = buckets or token_bucket
        self._global = global_bucket(settings.global_send_rate)
        self._chat_rate = settings.group_send_rate_per_minute
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
        self._delayed: list[tuple[float, int, _Envelope]] = []
        self._wake = asyncio.Event()
        # Set whenever nothing is queued *or* parked, so `join()` covers both.
        self._idle = asyncio.Event()
        self._idle.set()
        self._tasks: list[asyncio.Task[None]] = []
        self._seq = 0
        self._inflight = 0
        self._running = False
        self.sent = 0
        self.dropped = 0

    # --- lifecycle ------------------------------------------------------------
    def bind(self, bot: Bot) -> None:
        """Attach the Bot instance (the bot process owns it, not this module)."""
        self._bot = bot

    async def start(self, bot: Bot | None = None) -> None:
        if bot is not None:
            self._bot = bot
        if self._bot is None:
            raise RuntimeError("MessageSender needs a Bot before it can start.")
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._worker(index), name=f"sender-worker-{index}")
            for index in range(self._workers_count)
        ]
        self._tasks.append(asyncio.create_task(self._scheduler(), name="sender-scheduler"))
        logger.info("sender.started", workers=self._workers_count)

    async def stop(self, *, drain: bool = True, drain_timeout: float = 10.0) -> None:
        """Stop accepting work; optionally finish what is already queued."""
        if not self._running:
            return
        self._running = False
        if drain:
            try:
                await asyncio.wait_for(self.join(), timeout=drain_timeout)
            except TimeoutError:
                logger.warning("sender.drain_timeout", pending=self.pending)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("sender.stopped", sent=self.sent, dropped=self.dropped)

    @property
    def pending(self) -> int:
        return self._queue.qsize() + len(self._delayed) + self._inflight

    # --- submission -----------------------------------------------------------
    def enqueue(
        self,
        method: TelegramMethod[Any],
        *,
        chat_id: int,
        priority: SendPriority = SendPriority.REPLY,
    ) -> None:
        """Fire and forget. Use for anything whose result nobody reads."""
        self._push(_Envelope(method=method, chat_id=chat_id, priority=priority))

    async def call(
        self,
        method: TelegramMethod[T],
        *,
        chat_id: int,
        priority: SendPriority = SendPriority.REPLY,
    ) -> T | None:
        """Queue a call and await its result — needed when the message id matters.

        Returns `None` when the call was dropped (chat gone, permanent error).
        """
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._push(_Envelope(method=method, chat_id=chat_id, priority=priority, future=future))
        result: T | None = await future
        return result

    def broadcast(
        self,
        methods: Iterable[tuple[int, TelegramMethod[Any]]],
        *,
        priority: SendPriority = SendPriority.BROADCAST,
    ) -> int:
        """Queue one call per chat at broadcast priority. Returns the count."""
        queued = 0
        for chat_id, method in methods:
            self.enqueue(method, chat_id=chat_id, priority=priority)
            queued += 1
        return queued

    def _push(self, envelope: _Envelope) -> None:
        self._seq += 1
        self._idle.clear()
        self._queue.put_nowait(_QueueItem(int(envelope.priority), self._seq, envelope))

    def _defer(self, envelope: _Envelope, delay: float) -> None:
        """Park an envelope until `delay` has passed, without holding a worker."""
        self._seq += 1
        self._idle.clear()
        envelope.ready_at = time.monotonic() + delay
        heapq.heappush(self._delayed, (envelope.ready_at, self._seq, envelope))
        self._wake.set()

    def _mark_idle_if_drained(self) -> None:
        """Signal `join()` once nothing is queued, parked, or in flight."""
        if not self._delayed and self._queue.empty() and self._inflight == 0:
            self._idle.set()

    async def join(self) -> None:
        """Wait until every queued *and* deferred call has been handled.

        DECISION: `PriorityQueue.join()` alone is not enough — a worker calls
        `task_done()` when it parks a rate-limited envelope, so the queue reads
        as empty while the heap still holds work.
        """
        await self._idle.wait()

    # --- execution ------------------------------------------------------------
    async def _scheduler(self) -> None:
        """Move deferred envelopes back onto the queue when their time comes."""
        while True:
            try:
                if not self._delayed:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                ready_at, _, _ = self._delayed[0]
                sleep_for = ready_at - time.monotonic()
                if sleep_for > 0:
                    self._wake.clear()
                    with suppress(TimeoutError):
                        await asyncio.wait_for(self._wake.wait(), timeout=sleep_for)
                    continue
                _, _, envelope = heapq.heappop(self._delayed)
                self._push(envelope)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the loop must never die
                logger.exception("sender.scheduler_error")
                await asyncio.sleep(0.1)

    async def _worker(self, index: int) -> None:
        while True:
            item = await self._queue.get()
            self._inflight += 1
            try:
                await self._process(item.envelope)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - a worker must never die
                logger.exception("sender.worker_error", worker=index)
            finally:
                self._inflight -= 1
                self._queue.task_done()
                self._mark_idle_if_drained()

    def _bucket_specs(self, chat_id: int) -> tuple[BucketSpec, ...]:
        """DECISION: private chats skip the per-group bucket. The 20/min ceiling
        is a group rule; applying it to 1:1 chats would throttle captcha DMs and
        payment receipts for no reason."""
        if chat_id > 0:
            return (self._global,)
        return (self._global, chat_bucket(chat_id, self._chat_rate))

    async def _process(self, envelope: _Envelope) -> None:
        assert self._bot is not None
        specs = self._bucket_specs(envelope.chat_id)
        allowance = await self._buckets.consume_all(specs)
        if not allowance.allowed:
            wait = max(allowance.retry_after, 0.01)
            if wait <= INLINE_WAIT_CEILING:
                await asyncio.sleep(wait)
            else:
                self._defer(envelope, wait)
                return
            allowance = await self._buckets.consume_all(specs)
            if not allowance.allowed:
                self._defer(envelope, max(allowance.retry_after, 0.05))
                return

        envelope.attempts += 1
        try:
            result = await self._bot(envelope.method)
        except TelegramRetryAfter as exc:
            # Telegram's own number wins over our backoff curve.
            await self._on_flood(envelope, float(exc.retry_after), specs)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            # Bot kicked, chat deleted, message already gone: retrying cannot help.
            self._finish(envelope, SendResult(ok=False, error=str(exc)))
            self.dropped += 1
            logger.info(
                "sender.dropped",
                method=envelope.name,
                chat_id=envelope.chat_id,
                reason=type(exc).__name__,
                error=str(exc),
            )
        except (TelegramNetworkError, TelegramServerError) as exc:
            await self._retry_or_fail(envelope, exc, specs)
        except TelegramAPIError as exc:
            await self._retry_or_fail(envelope, exc, specs)
        else:
            self.sent += 1
            self._finish(envelope, SendResult(ok=True, value=result))

    async def _on_flood(
        self, envelope: _Envelope, retry_after: float, specs: tuple[BucketSpec, ...]
    ) -> None:
        """429 handling: the bucket was too generous, so drain it to match."""
        logger.warning(
            "sender.flood_control",
            method=envelope.name,
            chat_id=envelope.chat_id,
            retry_after=retry_after,
            attempts=envelope.attempts,
        )
        if envelope.attempts >= MAX_ATTEMPTS:
            await self._dead_letter(envelope, f"flood control after {envelope.attempts} attempts")
            return
        # Burn the tokens Telegram says we do not really have.
        for spec in specs:
            await self._buckets.consume(spec, tokens=spec.capacity)
        self._defer(envelope, retry_after + 0.25)

    async def _retry_or_fail(
        self, envelope: _Envelope, exc: Exception, specs: tuple[BucketSpec, ...]
    ) -> None:
        if envelope.attempts >= MAX_ATTEMPTS:
            await self._dead_letter(envelope, str(exc))
            return
        for spec in specs:
            await self._buckets.give_back(spec)
        delay = min(BASE_BACKOFF * (2 ** (envelope.attempts - 1)), MAX_BACKOFF)
        logger.warning(
            "sender.retry",
            method=envelope.name,
            chat_id=envelope.chat_id,
            attempt=envelope.attempts,
            delay=delay,
            error=str(exc),
        )
        self._defer(envelope, delay)

    async def _dead_letter(self, envelope: _Envelope, reason: str) -> None:
        """Give up on an envelope, but keep the evidence.

        DECISION: a capped Redis list rather than a table. This is an operational
        breadcrumb trail, not tenant data, and it must not grow without bound or
        add a write to the failure path of every send.
        """
        self.dropped += 1
        payload = json.dumps(
            {
                "method": envelope.name,
                "chat_id": envelope.chat_id,
                "priority": int(envelope.priority),
                "attempts": envelope.attempts,
                "reason": reason,
                "ts": time.time(),
            },
            ensure_ascii=False,
        )
        try:
            client = get_redis()
            await client.lpush(DEAD_LETTER_KEY, payload)  # type: ignore[misc]
            await client.ltrim(DEAD_LETTER_KEY, 0, DEAD_LETTER_MAX - 1)  # type: ignore[misc]
        except Exception:  # pragma: no cover - never fail a send over telemetry
            logger.exception("sender.dead_letter_write_failed")
        logger.error(
            "sender.dead_letter",
            method=envelope.name,
            chat_id=envelope.chat_id,
            attempts=envelope.attempts,
            reason=reason,
        )
        self._finish(envelope, SendResult(ok=False, error=reason))

    @staticmethod
    def _finish(envelope: _Envelope, result: SendResult) -> None:
        """Resolve the caller's future, if anyone is waiting."""
        if envelope.future is None or envelope.future.done():
            return
        envelope.future.set_result(result.value if result.ok else None)

    # --- diagnostics ----------------------------------------------------------
    async def dead_letters(self, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent give-ups, newest first (superadmin diagnostics)."""
        raw: Sequence[bytes] = await get_redis().lrange(DEAD_LETTER_KEY, 0, limit - 1)  # type: ignore[misc]
        items: list[dict[str, Any]] = []
        for entry in raw:
            try:
                items.append(json.loads(entry))
            except json.JSONDecodeError:
                continue
        return items

    def stats(self) -> dict[str, int]:
        return {
            "sent": self.sent,
            "dropped": self.dropped,
            "queued": self._queue.qsize(),
            "delayed": len(self._delayed),
        }


sender = MessageSender()

__all__ = [
    "DEAD_LETTER_KEY",
    "MAX_ATTEMPTS",
    "MessageSender",
    "SendPriority",
    "SendResult",
    "sender",
]

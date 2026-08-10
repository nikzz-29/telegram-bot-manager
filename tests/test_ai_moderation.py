"""AI moderation: the gates, the budget, and every way the provider can fail.

Spec §5.5. No test here opens a socket — `ai_moderation.use()` swaps in a fake
provider, which is the whole reason that seam exists. The parser tests do go
through the real reply-handling path, because that is where a live model actually
surprises us.
"""

from __future__ import annotations

from typing import Any

import pytest

from core import ai_moderation as ai_module
from core import cache
from core.ai_moderation import ai_moderation, text_hash
from core.ai_provider import (
    CircuitBreaker,
    ModerationContext,
    OpenAiCompatibleProvider,
    Verdict,
    parse_verdict,
)
from shared.enums import AiVerdictLabel, ModerationAction
from shared.errors import ProviderUnavailableError
from shared.schemas.module_configs import AiModerationConfig


class FakeProvider:
    """Returns a scripted verdict and counts the calls it was asked to make."""

    def __init__(self, verdict: Verdict | None = None, error: Exception | None = None) -> None:
        self.verdict = verdict or Verdict(label=AiVerdictLabel.SCAM, confidence=0.95, reason="bait")
        self.error = error
        self.calls: list[str] = []

    async def classify(self, text: str, ctx: ModerationContext) -> Verdict:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.verdict


def context(chat_id: int = 1) -> ModerationContext:
    return ModerationContext(chat_id=chat_id, chat_title="Chat", language="en", tg_user_id=7)


def config(**overrides: Any) -> AiModerationConfig:
    """An always-check config: sampling and length gates open unless overridden."""
    base: dict[str, Any] = {
        "enabled": True,
        "sample_rate": 1.0,
        "min_text_length": 1,
        "thresholds": {AiVerdictLabel.SCAM: 0.7, AiVerdictLabel.TOXIC: 0.9},
        "actions": {AiVerdictLabel.SCAM: ModerationAction.DELETE},
    }
    base.update(overrides)
    return AiModerationConfig.model_validate(base)


@pytest.fixture(autouse=True)
def _restore_provider() -> Any:
    yield
    ai_moderation.use(None)


# --- the parser: what a real model actually sends back ------------------------


def test_parse_verdict_reads_a_clean_object() -> None:
    verdict = parse_verdict('{"label": "scam", "confidence": 0.91, "reason": "fake support"}')
    assert verdict.label is AiVerdictLabel.SCAM
    assert verdict.confidence == pytest.approx(0.91)
    assert verdict.reason == "fake support"


def test_parse_verdict_digs_the_object_out_of_prose_and_fences() -> None:
    """Models add commentary and ```json fences no matter what the prompt says."""
    wrapped = 'Sure!\n```json\n{"label": "toxic", "confidence": 0.8}\n```\nHope that helps.'
    assert parse_verdict(wrapped).label is AiVerdictLabel.TOXIC


@pytest.mark.parametrize(
    "content",
    [
        "",
        "no json here at all",
        "{not valid json",
        '{"label": "definitely_not_a_label", "confidence": 0.9}',
        '{"label": "scam", "confidence": "very high"}',
        '["scam", 0.9]',
    ],
)
def test_parse_verdict_treats_anything_unexpected_as_ok(content: str) -> None:
    """A reply we cannot read must never become a deletion."""
    verdict = parse_verdict(content)
    assert verdict.label is AiVerdictLabel.OK
    assert verdict.confidence == 0.0
    assert not verdict.is_actionable


def test_parse_verdict_clamps_confidence_into_range() -> None:
    assert parse_verdict('{"label": "scam", "confidence": 7.5}').confidence == 1.0
    assert parse_verdict('{"label": "scam", "confidence": -2}').confidence == 0.0


# --- the circuit breaker ------------------------------------------------------


def test_breaker_opens_on_the_threshold_failure() -> None:
    breaker = CircuitBreaker(threshold=3, reset_seconds=60)
    for _ in range(2):
        breaker.record_failure()
    assert not breaker.is_open
    breaker.record_failure()
    assert breaker.is_open


def test_breaker_success_clears_the_streak() -> None:
    breaker = CircuitBreaker(threshold=2, reset_seconds=60)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert not breaker.is_open


def test_breaker_probes_again_once_the_cooldown_elapses() -> None:
    """Half-open is implicit: after the cool-down the next call is let through."""
    breaker = CircuitBreaker(threshold=1, reset_seconds=0.0)
    breaker.record_failure()
    assert not breaker.is_open


async def test_unconfigured_provider_is_unavailable_not_a_verdict() -> None:
    """No API key must degrade, never classify — and never touch the network."""
    provider = OpenAiCompatibleProvider(api_key="")
    assert not provider.configured
    with pytest.raises(ProviderUnavailableError):
        await provider.classify("anything", context())


# --- the service: sampling, cache, budget, degradation ------------------------


class FakeCache:
    """`cache.get_value` / `set_value` over a dict, with no TTL semantics."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get_value(self, key: str) -> Any:
        return self.store.get(key)

    async def set_value(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        self.store[key] = value


class FakeRedis:
    """Just the three commands the budget counter uses."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.expires: list[str] = []

    async def get(self, key: str) -> str | None:
        value = self.counters.get(key)
        return str(value) if value is not None else None

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, ttl: Any) -> bool:
        self.expires.append(key)
        return True


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeProvider, FakeCache, FakeRedis]:
    """Wire the service to in-memory cache, Redis and provider."""
    provider = FakeProvider()
    verdict_cache = FakeCache()
    redis = FakeRedis()
    ai_moderation.use(provider)
    monkeypatch.setattr(cache, "get_value", verdict_cache.get_value)
    monkeypatch.setattr(cache, "set_value", verdict_cache.set_value)
    monkeypatch.setattr(ai_module, "get_redis", lambda: redis)
    return provider, verdict_cache, redis


async def test_actionable_verdict_becomes_the_configured_action(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    provider, _, _ = service
    decision = await ai_moderation.inspect("free crypto, dm me", ctx=context(), config=config())
    assert decision.checked and not decision.cached
    assert decision.action is ModerationAction.DELETE
    assert decision.should_act
    assert provider.calls == ["free crypto, dm me"]


async def test_verdict_below_the_threshold_is_recorded_but_not_acted_on(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """A 0.72 scam under a 0.9 bar is a log line, not a deletion."""
    provider, _, _ = service
    provider.verdict = Verdict(label=AiVerdictLabel.SCAM, confidence=0.72, reason="maybe")
    decision = await ai_moderation.inspect(
        "borderline", ctx=context(), config=config(thresholds={AiVerdictLabel.SCAM: 0.9})
    )
    assert decision.checked
    assert decision.action is ModerationAction.NOTHING
    assert not decision.should_act


async def test_short_text_never_reaches_the_provider(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    provider, _, _ = service
    decision = await ai_moderation.inspect("ok", ctx=context(), config=config(min_text_length=10))
    assert not decision.checked
    assert provider.calls == []


async def test_disabled_config_never_reaches_the_provider(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    provider, _, _ = service
    decision = await ai_moderation.inspect("anything", ctx=context(), config=config(enabled=False))
    assert not decision.checked
    assert provider.calls == []


async def test_sampling_is_decided_by_the_text_not_the_clock(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """The point of hashing: resending the same message cannot reroll the dice.

    A rate of 0.5 puts roughly half the corpus on each side, so the assertion is
    not "this text is sampled" but "this text always lands the same way".
    """
    provider, verdict_cache, _ = service
    sampled = config(sample_rate=0.5)
    first = await ai_moderation.inspect("try your luck", ctx=context(), config=sampled)
    verdict_cache.store.clear()  # a cache hit would fake the determinism we want
    second = await ai_moderation.inspect("try your luck", ctx=context(), config=sampled)
    assert first.checked == second.checked
    assert len(provider.calls) == (2 if first.checked else 0)


@pytest.mark.parametrize(("rate", "expected"), [(0.0, False), (1.0, True)])
async def test_sampling_endpoints_are_absolute(
    service: tuple[FakeProvider, FakeCache, FakeRedis], rate: float, expected: bool
) -> None:
    """0.0 checks nothing and 1.0 checks everything, whatever the hash says."""
    provider, _, _ = service
    decision = await ai_moderation.inspect(
        "some message body", ctx=context(), config=config(sample_rate=rate)
    )
    assert decision.checked is expected
    assert bool(provider.calls) is expected


async def test_a_cached_verdict_skips_the_provider_and_the_budget(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """Spec §5.5: the same scam text pasted twice is one classification.

    The budget assertion is the load-bearing half — a cache that still charged
    for its hits would burn a Pro chat's daily allowance on one copy-paste run.
    """
    provider, verdict_cache, redis = service
    text = "join my signals channel"

    first = await ai_moderation.inspect(text, ctx=context(), config=config())
    assert first.checked and not first.cached
    assert verdict_cache.store  # the miss populated it
    spent_after_first = dict(redis.counters)

    second = await ai_moderation.inspect(text, ctx=context(), config=config())
    assert second.checked and second.cached
    assert second.action is ModerationAction.DELETE  # the threshold still applies
    assert second.text_hash == text_hash(text)
    assert provider.calls == [text], "the second call must not reach the provider"
    assert redis.counters == spent_after_first, "a cache hit must not spend budget"


async def test_a_cached_verdict_is_re_judged_against_this_chats_threshold(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """The cache holds the verdict, not the decision — chats disagree on bars."""
    _, verdict_cache, _ = service
    text = "borderline pitch"
    await ai_moderation.inspect(text, ctx=context(), config=config())
    assert verdict_cache.store

    strict = await ai_moderation.inspect(
        text, ctx=context(chat_id=2), config=config(thresholds={AiVerdictLabel.SCAM: 0.99})
    )
    assert strict.cached
    assert strict.action is ModerationAction.NOTHING


async def test_budget_exhaustion_skips_the_check_without_failing_the_message(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """Over the daily allowance the message is allowed, not held or dropped."""
    provider, _, _ = service
    await ai_moderation.inspect("first message", ctx=context(), config=config(), plan_limit=1)
    assert len(provider.calls) == 1

    decision = await ai_moderation.inspect(
        "second message", ctx=context(), config=config(), plan_limit=1
    )
    assert decision is ai_module.SKIPPED
    assert not decision.should_act
    assert len(provider.calls) == 1
    assert await ai_moderation.budget_used(1) == 1


async def test_an_unmetered_plan_never_hits_the_budget_gate(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """`ai_checks_per_day = -1` is Business's unmetered marker, not a zero limit."""
    provider, _, _ = service
    for index in range(3):
        await ai_moderation.inspect(
            f"message {index}", ctx=context(), config=config(), plan_limit=-1
        )
    assert len(provider.calls) == 3


async def test_a_provider_outage_degrades_instead_of_raising(
    service: tuple[FakeProvider, FakeCache, FakeRedis],
) -> None:
    """Spec §5.5: losing a message to a timeout is worse than missing one scam."""
    provider, verdict_cache, redis = service
    provider.error = ProviderUnavailableError("circuit is open")

    decision = await ai_moderation.inspect("free crypto, dm me", ctx=context(), config=config())
    assert decision is ai_module.SKIPPED
    assert not decision.should_act
    assert not verdict_cache.store, "a failure must not be cached as a verdict"
    assert not redis.counters, "a failed call must not be charged for"

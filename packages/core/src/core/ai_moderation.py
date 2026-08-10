"""AI moderation: sampling, caching, the daily budget, and what to do about it.

Spec §5.5. The provider decides *what a message is*; this module decides whether
to ask at all, what the answer costs, and what happens to the message — and it is
built so that every one of those can fail without a message going missing.

DECISION: three gates run before the network, cheapest first — sampling, then the
verdict cache, then the daily budget. Sampling is a modulus over the text hash
rather than a random draw, so the same text in the same chat is always either
checked or skipped: a spammer cannot reroll their way past by resending, and a
sampled-out message stays sampled out on edit.

DECISION: the cache is keyed by the text hash alone, not by chat. A scam script
pasted into forty chats is the same text and deserves one classification; the
per-chat part of the decision is the threshold and the action, both applied after
the lookup. Cached verdicts do not consume budget — the chat already paid once.

DECISION: on any provider failure the message is *allowed*, and the cheap filters
that already ran keep their verdicts. Losing a message to a timeout is a worse
outcome than missing one scam, and the spec asks for it in as many words.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import hashlib
from typing import Final

from core import cache
from core.ai_provider import (
    AiProvider,
    ModerationContext,
    OpenAiCompatibleProvider,
    Verdict,
)
from core.redis_client import get_redis
from db.uow import UnitOfWork
from shared.config import get_settings
from shared.enums import AiVerdictLabel, ModerationAction, Plan
from shared.errors import ProviderUnavailableError
from shared.logging import get_logger
from shared.plans import limits_for_plan
from shared.schemas.module_configs import AiModerationConfig
from shared.time_utils import utc_now

logger = get_logger(__name__)

# Budget counters are per chat per UTC day and expire on their own, so nothing
# has to sweep them. The date is in the key, which is also what makes a rollover
# free.
BUDGET_KEY: Final = "tgm:ai:budget:{chat_id}:{day}"
BUDGET_TTL: Final = timedelta(days=2)
DAY_FORMAT: Final = "%Y%m%d"

# `sample_rate` is compared against this many buckets. 1000 gives a rate of
# 0.001 a real meaning, which is finer than any panel slider will offer.
SAMPLE_BUCKETS: Final = 1_000


def text_hash(text: str) -> str:
    """Stable identity for a message body: same text, same key, any process."""
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AiDecision:
    """What the service concluded, and why it is safe to act on."""

    verdict: Verdict
    action: ModerationAction = ModerationAction.NOTHING
    checked: bool = False
    cached: bool = False
    text_hash: str = ""

    @property
    def should_act(self) -> bool:
        return self.action is not ModerationAction.NOTHING


SKIPPED: Final = AiDecision(verdict=Verdict())


class AiModerationService:
    """Decides whether to classify a message, and what its verdict means here."""

    def __init__(self, provider: AiProvider | None = None) -> None:
        self._provider = provider
        self._own_provider: OpenAiCompatibleProvider | None = None

    @property
    def provider(self) -> AiProvider:
        """The configured provider, built on first use.

        Lazy so that a Free-only deployment with no API key never constructs an
        HTTP client, and so tests can swap the provider before anything is built.
        """
        if self._provider is not None:
            return self._provider
        if self._own_provider is None:
            self._own_provider = OpenAiCompatibleProvider()
        return self._own_provider

    def use(self, provider: AiProvider | None) -> None:
        """Swap the provider — the seam the fake in tests goes through."""
        self._provider = provider

    # --- gates ----------------------------------------------------------------
    def _sampled(self, digest: str, config: AiModerationConfig) -> bool:
        """Deterministic sampling: the text decides, not the clock."""
        if config.sample_rate >= 1.0:
            return True
        if config.sample_rate <= 0.0:
            return False
        bucket = int(digest[:8], 16) % SAMPLE_BUCKETS
        return bucket < int(config.sample_rate * SAMPLE_BUCKETS)

    async def budget_used(self, chat_id: int) -> int:
        """How many paid checks this chat has spent today."""
        key = BUDGET_KEY.format(chat_id=chat_id, day=utc_now().strftime(DAY_FORMAT))
        raw = await get_redis().get(key)
        return int(raw) if raw else 0

    async def _spend(self, chat_id: int) -> int:
        """Consume one check and return the new total."""
        key = BUDGET_KEY.format(chat_id=chat_id, day=utc_now().strftime(DAY_FORMAT))
        client = get_redis()
        used = int(await client.incr(key))
        if used == 1:
            await client.expire(key, BUDGET_TTL)
        return used

    def _action_for(self, verdict: Verdict, config: AiModerationConfig) -> ModerationAction:
        """Apply this chat's threshold and action table to a verdict."""
        if not verdict.is_actionable:
            return ModerationAction.NOTHING
        threshold = config.thresholds.get(verdict.label)
        if threshold is None or verdict.confidence < threshold:
            return ModerationAction.NOTHING
        return config.actions.get(verdict.label, ModerationAction.ALERT_ADMINS)

    # --- the decision ---------------------------------------------------------
    async def inspect(
        self,
        text: str,
        *,
        ctx: ModerationContext,
        config: AiModerationConfig,
        plan_limit: int | None = None,
    ) -> AiDecision:
        """Classify one message if it is worth classifying, and price the answer.

        Never raises: a provider that is down, over budget or misconfigured all
        come back as `SKIPPED`, which the caller reads as "the cheap filters had
        the last word".
        """
        settings = get_settings()
        stripped = text.strip()
        if not settings.ai_enabled or not config.enabled or len(stripped) < config.min_text_length:
            return SKIPPED

        digest = text_hash(stripped)
        if not self._sampled(digest, config):
            return SKIPPED

        cached = await cache.get_value(cache.ai_verdict_key(digest))
        if isinstance(cached, dict):
            verdict = Verdict(
                label=AiVerdictLabel(str(cached.get("label", AiVerdictLabel.OK.value))),
                confidence=float(cached.get("confidence", 0.0)),
                reason=str(cached.get("reason", "")),
            )
            return AiDecision(
                verdict=verdict,
                action=self._action_for(verdict, config),
                checked=True,
                cached=True,
                text_hash=digest,
            )

        if plan_limit is not None and plan_limit >= 0:
            used = await self.budget_used(ctx.chat_id)
            if used >= plan_limit:
                logger.info("ai.budget_exhausted", chat_id=ctx.chat_id, limit=plan_limit)
                return SKIPPED

        try:
            verdict = await self.provider.classify(stripped, ctx)
        except ProviderUnavailableError as error:
            # Degradation, not failure: the message goes through, and the rules
            # that already ran stand.
            logger.info("ai.degraded", chat_id=ctx.chat_id, error=str(error))
            return SKIPPED

        await self._spend(ctx.chat_id)
        await cache.set_value(
            cache.ai_verdict_key(digest),
            {
                "label": verdict.label.value,
                "confidence": verdict.confidence,
                "reason": verdict.reason,
            },
            ttl=settings.ai_cache_ttl_seconds,
        )
        return AiDecision(
            verdict=verdict,
            action=self._action_for(verdict, config),
            checked=True,
            cached=False,
            text_hash=digest,
        )

    async def record(self, decision: AiDecision, *, ctx: ModerationContext) -> None:
        """Write the verdict to the audit log. Best-effort by design.

        The message has already been dealt with by the time this runs, and a
        logging failure must not undo a moderation action.
        """
        if not decision.checked:
            return
        try:
            async with UnitOfWork() as uow:
                await uow.ai_logs.add(
                    chat_id=ctx.chat_id,
                    tg_user_id=ctx.tg_user_id,
                    label=decision.verdict.label,
                    confidence=decision.verdict.confidence,
                    action=decision.action.value,
                    text_hash=decision.text_hash,
                )
                await uow.commit()
        except Exception:
            logger.exception("ai.log_failed", chat_id=ctx.chat_id)

    async def remaining_budget(self, chat_id: int, *, plan: Plan) -> int:
        """Checks left today for a chat on `plan`. `-1` means unmetered."""
        allowance = limits_for_plan(plan).ai_checks_per_day
        if allowance < 0:
            return -1
        return max(0, allowance - await self.budget_used(chat_id))

    async def close(self) -> None:
        if self._own_provider is not None:
            await self._own_provider.close()
            self._own_provider = None


ai_moderation = AiModerationService()

__all__ = [
    "BUDGET_KEY",
    "SKIPPED",
    "AiDecision",
    "AiModerationService",
    "ai_moderation",
    "text_hash",
]

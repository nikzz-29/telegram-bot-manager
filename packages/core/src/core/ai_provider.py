"""The classifier behind AI moderation, and the parts that keep it optional.

Spec §5.5. The provider sits behind a `Protocol` so the bot never imports an SDK
and the tests never open a socket. One implementation ships: an OpenAI-compatible
chat-completions call over `httpx`, pointed at whatever `AI_BASE_URL` names.

DECISION: OpenAI-compatible HTTP over `httpx`, not the `openai` SDK. The call is
one POST with a JSON body, the SDK would add a dependency and a second retry
policy on top of ours, and `base_url` from config is exactly what lets a
self-hosted or third-party endpoint drop in without a code change.

DECISION: the model is asked for strict JSON and its answer is parsed
defensively — an unparseable reply becomes `ok`, never an action. A classifier
that returns garbage must not be able to delete anyone's messages, so every
uncertain path fails open and the cheap rule-based filters upstream stay in
force.

DECISION: the circuit breaker is per-process and in memory. Its job is to stop a
worker hammering a dead endpoint for eight seconds per message; sharing that
state across replicas through Redis would add a round-trip to the very path the
breaker exists to make fast.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Final, Protocol

import httpx

from shared.config import get_settings
from shared.enums import AiVerdictLabel
from shared.errors import ProviderUnavailableError
from shared.logging import get_logger
from shared.time_utils import utc_now

logger = get_logger(__name__)

# The labels the model may return. Anything else is read as `ok`.
LABELS: Final[frozenset[str]] = frozenset(label.value for label in AiVerdictLabel)

# Long enough to judge, short enough that a runaway generation cannot stall the
# message pipeline: the answer is three short fields.
MAX_TOKENS: Final = 120
TEMPERATURE: Final = 0.0

# Text longer than this is truncated before it is sent. Scam and hidden-ad copy
# makes its pitch early, and the tail is mostly padding that costs tokens.
MAX_INPUT_CHARS: Final = 2_000

SYSTEM_PROMPT: Final = (
    "You are a moderation classifier for Telegram group chats. "
    "Classify the message into exactly one label:\n"
    "- toxic: insults, harassment, hate speech, threats.\n"
    "- hidden_ad: promotion disguised as a normal message — referral links, "
    "channel plugs, 'DM me for details' offers.\n"
    "- scam: fraud, phishing, fake giveaways, fake technical support, "
    "crypto doubling schemes, impersonation of admins or support staff.\n"
    "- ok: anything else, including rude but harmless banter.\n"
    "Judge the message as written, in any language. Reply with JSON only: "
    '{"label": "...", "confidence": 0.0-1.0, "reason": "short phrase"}'
)


@dataclass(frozen=True, slots=True)
class ModerationContext:
    """What the classifier is told about where the message came from."""

    chat_id: int
    chat_title: str = ""
    language: str = "ru"
    tg_user_id: int | None = None
    is_new_member: bool = False


@dataclass(frozen=True, slots=True)
class Verdict:
    """One classification. `ok` with zero confidence is the safe default."""

    label: AiVerdictLabel = AiVerdictLabel.OK
    confidence: float = 0.0
    reason: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.label is not AiVerdictLabel.OK


class AiProvider(Protocol):
    """Spec §5.5: the whole surface the moderation service depends on."""

    async def classify(self, text: str, ctx: ModerationContext) -> Verdict: ...


def parse_verdict(content: str) -> Verdict:
    """Read a model reply into a `Verdict`, treating anything odd as `ok`.

    Models wrap JSON in prose and fences more often than they should, so the
    outermost braces are located rather than the string being parsed whole.
    """
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return Verdict()
    try:
        payload = json.loads(content[start : end + 1])
    except ValueError:
        return Verdict()
    if not isinstance(payload, dict):
        return Verdict()

    raw_label = str(payload.get("label", "")).strip().lower()
    if raw_label not in LABELS:
        return Verdict()
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        # A label we can read next to a confidence we cannot is not half a
        # verdict, it is a malformed one. Keeping the label at 0.0 would clear
        # every threshold check anyway, but it would also put a scam label in the
        # audit log that the model never actually justified.
        return Verdict()
    return Verdict(
        label=AiVerdictLabel(raw_label),
        confidence=min(1.0, max(0.0, confidence)),
        reason=str(payload.get("reason", ""))[:200],
    )


class CircuitBreaker:
    """Opens after N consecutive failures, closes again after a cool-down.

    Half-open is implicit: the first call after the reset window is let through,
    and it either succeeds (closing the breaker) or trips it for another window.
    """

    def __init__(self, *, threshold: int, reset_seconds: float) -> None:
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if utc_now().timestamp() - self._opened_at >= self._reset_seconds:
            # Cool-down elapsed: let exactly one call through to probe.
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold and self._opened_at is None:
            self._opened_at = utc_now().timestamp()
            logger.warning("ai.circuit_opened", failures=self._failures)


class OpenAiCompatibleProvider:
    """Chat-completions classifier against any OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.ai_base_url).rstrip("/")
        self._api_key = api_key or settings.ai_api_key
        self._model = model or settings.ai_model
        self._timeout = timeout or settings.ai_timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._breaker = CircuitBreaker(
            threshold=settings.ai_circuit_failure_threshold,
            reset_seconds=settings.ai_circuit_reset_seconds,
        )

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _http(self) -> httpx.AsyncClient:
        """One keep-alive client per process — TLS handshakes are not free."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    def _body(self, text: str, ctx: ModerationContext) -> dict[str, Any]:
        hint = f"Chat language: {ctx.language}."
        if ctx.is_new_member:
            hint += " The author joined this chat recently."
        return {
            "model": self._model,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{hint}\n\nMessage:\n{text[:MAX_INPUT_CHARS]}"},
            ],
        }

    async def classify(self, text: str, ctx: ModerationContext) -> Verdict:
        """Classify one message, or raise `ProviderUnavailableError` trying.

        The caller treats that exception as "fall back to the cheap filters",
        which is why every transport-level problem is normalized into it.
        """
        if not self.configured:
            raise ProviderUnavailableError("AI moderation has no API key configured.")
        if self._breaker.is_open:
            raise ProviderUnavailableError("AI provider circuit is open.")

        try:
            response = await self._http().post("/chat/completions", json=self._body(text, ctx))
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            self._breaker.record_failure()
            logger.warning("ai.request_failed", error=str(error), chat_id=ctx.chat_id)
            raise ProviderUnavailableError("AI provider request failed.") from error

        self._breaker.record_success()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            logger.warning("ai.malformed_response", chat_id=ctx.chat_id)
            return Verdict()
        return parse_verdict(str(content))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = [
    "LABELS",
    "MAX_INPUT_CHARS",
    "SYSTEM_PROMPT",
    "AiProvider",
    "CircuitBreaker",
    "ModerationContext",
    "OpenAiCompatibleProvider",
    "Verdict",
    "parse_verdict",
]

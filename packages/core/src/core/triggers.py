"""Trigger rules: phrase → canned response.

Spec §5.6 — an admin defines a phrase and the answer the bot gives when it
appears. Three matching modes: exact, substring, regular expression.

DECISION: matchers are compiled once per distinct rule set and memoized, exactly
like `core.stop_words`. A chat with thirty triggers would otherwise recompile
thirty regexes on every message; here the whole set collapses into one
alternation compiled the first time it is seen and shared by every process-local
lookup afterwards.

DECISION: admin-supplied regular expressions are checked for catastrophic
backtracking at write time and matched against a length-capped copy of the
message at read time. Python's `re` has no timeout, so an unbounded `(a+)+$`
against a long message would pin a bot worker; both guards together make the
worst case linear in a constant.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Final

from core import cache
from db.uow import UnitOfWork
from shared.enums import TriggerMatch
from shared.errors import InvalidPatternError
from shared.logging import get_logger

logger = get_logger(__name__)

# Longest slice of a message a trigger is matched against. Well past any real
# phrase, and short enough that even a pathological pattern finishes instantly.
MAX_SCAN_CHARS: Final = 1_000

# Nested quantifiers — `(x+)+`, `(x*)*`, `(x+)*` — are the classic ReDoS shape.
_NESTED_QUANTIFIER: Final = re.compile(r"\([^()]*[+*][^()]*\)\s*[+*{]")
# A bounded repetition big enough to be used as an amplifier instead of a limit.
_HUGE_REPEAT: Final = re.compile(r"\{\s*\d{4,}")


@dataclass(frozen=True, slots=True)
class TriggerDef:
    """The matching half of a `TriggerRule` row — hashable, so it can be memoized."""

    id: int
    pattern: str
    match: TriggerMatch = TriggerMatch.CONTAINS
    case_sensitive: bool = False


def validate_pattern(pattern: str, match: TriggerMatch, *, case_sensitive: bool = False) -> str:
    """Check a pattern is usable and return it stripped.

    Raises:
        InvalidPatternError: empty, or a regular expression that either does not
            compile or carries a backtracking shape we refuse to run.
    """
    cleaned = (pattern or "").strip()
    if not cleaned:
        raise InvalidPatternError("Trigger pattern must not be empty.")
    if match is not TriggerMatch.REGEX:
        return cleaned

    if _NESTED_QUANTIFIER.search(cleaned) or _HUGE_REPEAT.search(cleaned):
        raise InvalidPatternError(
            "Regular expression uses a nested or oversized quantifier.", pattern=cleaned
        )
    try:
        re.compile(cleaned, 0 if case_sensitive else re.IGNORECASE)
    except re.error as exc:
        raise InvalidPatternError(f"Invalid regular expression: {exc}", pattern=cleaned) from exc
    return cleaned


def _to_regex(definition: TriggerDef) -> str:
    """One rule as a regex fragment, ready to join into the alternation."""
    if definition.match is TriggerMatch.REGEX:
        return f"(?:{definition.pattern})"
    escaped = re.escape(definition.pattern)
    if definition.match is TriggerMatch.EXACT:
        return rf"\A{escaped}\Z"
    # CONTAINS: bounded by word edges where the phrase has them, so "ok" does not
    # fire inside "booking" while "?!" still matches on its own.
    prefix = r"\b" if definition.pattern[:1].isalnum() else ""
    suffix = r"\b" if definition.pattern[-1:].isalnum() else ""
    return f"{prefix}{escaped}{suffix}"


class TriggerMatcher:
    """Compiled rule set for one chat.

    DECISION: two compiled groups, case-sensitive and case-insensitive, rather
    than one regex per rule. Most chats use a single sensitivity, so in practice
    a message is scanned once; ordering inside each group follows the rule ids,
    which makes "which trigger fired" stable and explainable to an admin.
    """

    __slots__ = ("_groups", "_size")

    def __init__(self, definitions: Iterable[TriggerDef]) -> None:
        buckets: dict[bool, list[TriggerDef]] = {True: [], False: []}
        for definition in definitions:
            if definition.pattern.strip():
                buckets[definition.case_sensitive].append(definition)

        self._size = sum(len(items) for items in buckets.values())
        self._groups: list[tuple[re.Pattern[str], tuple[TriggerDef, ...]]] = []
        for case_sensitive, items in buckets.items():
            if not items:
                continue
            compiled = self._compile(items, case_sensitive=case_sensitive)
            if compiled is not None:
                self._groups.append((compiled, tuple(items)))

    @staticmethod
    def _compile(items: Sequence[TriggerDef], *, case_sensitive: bool) -> re.Pattern[str] | None:
        """Join rules into one alternation with a named group per rule id."""
        flags = re.MULTILINE if case_sensitive else re.MULTILINE | re.IGNORECASE
        parts: list[str] = []
        for index, definition in enumerate(items):
            try:
                parts.append(f"(?P<t{index}>{_to_regex(definition)})")
            except re.error:
                logger.warning("triggers.pattern_skipped", trigger_id=definition.id)
        if not parts:
            return None
        try:
            return re.compile("|".join(parts), flags)
        except re.error as error:
            # One bad rule must not silence the rest: fall back to compiling the
            # rules individually and dropping only the offender.
            logger.warning("triggers.group_compile_failed", error=str(error))
            survivors: list[str] = []
            for part in parts:
                try:
                    re.compile(part, flags)
                except re.error:
                    continue
                survivors.append(part)
            return re.compile("|".join(survivors), flags) if survivors else None

    def find(self, text: str) -> TriggerDef | None:
        """The first rule this text satisfies, or `None`."""
        if not self._size or not text:
            return None
        scanned = text[:MAX_SCAN_CHARS]
        for compiled, items in self._groups:
            match = compiled.search(scanned)
            if match is None:
                continue
            for index, definition in enumerate(items):
                if match.group(f"t{index}") is not None:
                    return definition
        return None

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0


@lru_cache(maxsize=2048)
def _cached_matcher(definitions: tuple[TriggerDef, ...]) -> TriggerMatcher:
    return TriggerMatcher(definitions)


def matcher_for(definitions: Iterable[TriggerDef]) -> TriggerMatcher:
    """Memoized matcher — identical rule sets share one compiled instance."""
    return _cached_matcher(tuple(sorted(definitions, key=lambda item: item.id)))


class TriggerService:
    """Loads a chat's enabled rules, cached, and matches messages against them."""

    async def definitions(self, chat_id: int) -> tuple[TriggerDef, ...]:
        """Enabled rules for a chat, cached until the chat's settings change."""
        key = cache.triggers_key(chat_id)
        cached = await cache.get_value(key)
        if isinstance(cached, list):
            return tuple(
                TriggerDef(
                    id=int(item["id"]),
                    pattern=str(item["pattern"]),
                    match=TriggerMatch(item["match"]),
                    case_sensitive=bool(item["case_sensitive"]),
                )
                for item in cached
            )

        async with UnitOfWork() as uow:
            rows = await uow.triggers.list_for_chat(chat_id, enabled_only=True)
        payload = [
            {
                "id": row.id,
                "pattern": row.pattern,
                "match": row.match.value,
                "case_sensitive": row.case_sensitive,
            }
            for row in rows
        ]
        await cache.set_value(
            key, payload, ttl=cache.TTL_MODULE_CONFIG, tags=(cache.chat_tag(chat_id),)
        )
        return tuple(
            TriggerDef(
                id=int(item["id"]),
                pattern=str(item["pattern"]),
                match=TriggerMatch(str(item["match"])),
                case_sensitive=bool(item["case_sensitive"]),
            )
            for item in payload
        )

    async def match(self, chat_id: int, text: str) -> TriggerDef | None:
        """Which rule this message fires, if any."""
        definitions = await self.definitions(chat_id)
        if not definitions:
            return None
        return matcher_for(definitions).find(text)

    @staticmethod
    async def invalidate(chat_id: int) -> None:
        """Called after any write so the next message sees the new rule set."""
        await cache.cache.delete(cache.triggers_key(chat_id))


triggers = TriggerService()

__all__ = [
    "MAX_SCAN_CHARS",
    "TriggerDef",
    "TriggerMatcher",
    "TriggerService",
    "matcher_for",
    "triggers",
    "validate_pattern",
]

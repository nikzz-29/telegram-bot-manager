"""Stop-word matching.

Spam filters lose to trivial obfuscation (`с у к а`, `sсam` with a Cyrillic
`с`, `f-u-c-k`), so matching runs against a normalized copy of the text:
homoglyphs folded to Latin, separators between letters removed, case dropped.

DECISION: normalization is applied to the *pattern* too, so an admin who types
a stop word with a Cyrillic `а` gets the same matcher as one who types Latin.
Matchers are memoized by word list — identical lists across chats share one
compiled instance, because building one per message would dominate the hot path.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
import re

from shared.plans import STOP_WORD_PRESETS

# Cyrillic/Greek lookalikes folded onto their Latin twins.
_HOMOGLYPHS = str.maketrans(
    {
        "а": "a",
        "А": "a",
        "α": "a",
        "@": "a",
        "4": "a",
        "в": "b",
        "В": "b",
        "β": "b",
        "с": "c",
        "С": "c",
        "е": "e",
        "Е": "e",
        "ε": "e",
        "3": "e",
        "н": "h",
        "Н": "h",
        "к": "k",
        "К": "k",
        "κ": "k",
        "м": "m",
        "М": "m",
        "о": "o",
        "О": "o",
        "ο": "o",
        "0": "o",
        "р": "p",
        "Р": "p",
        "ρ": "p",
        "ѕ": "s",
        "Ѕ": "s",
        "$": "s",
        "5": "s",
        "т": "t",
        "Т": "t",
        "τ": "t",
        "7": "t",
        "у": "y",
        "У": "y",
        "γ": "y",
        "х": "x",
        "Х": "x",
        "χ": "x",
        "і": "i",
        "І": "i",
        "1": "i",
        "!": "i",
        "|": "i",
        "ј": "j",
        "Ј": "j",
    }
)

# Zero-width and formatting characters used to break up words.
_INVISIBLE = re.compile("[​-‏‪-‮⁠﻿­]")
# Separators inserted between letters: `с.у.к.а`, `f-u-c-k`, `s p a m`.
_SEPARATORS = re.compile(r"[\s.\-_*+~`'\"^()\[\]{}<>/\\|]+")
_REPEATS = re.compile(r"(.)\1{2,}")


def normalize(text: str) -> str:
    """Fold a message into the form stop words are matched against."""
    folded = _INVISIBLE.sub("", text).translate(_HOMOGLYPHS).lower()
    # Collapse runs of the same character (`sooooo`) down to two.
    return _REPEATS.sub(r"\1\1", folded)


def strip_separators(text: str) -> str:
    """Second pass that also removes intra-word separators."""
    return _SEPARATORS.sub("", text)


class StopWordMatcher:
    """Compiled matcher for one chat's word list.

    Words containing `*` act as wildcards (`казин*` matches `казино`); every
    other word matches as a substring of the normalized text.
    """

    __slots__ = ("_dense", "_pattern", "_size")

    def __init__(self, words: Iterable[str], presets: Iterable[str] = ()) -> None:
        collected: set[str] = set()
        for word in words:
            cleaned = normalize(word).strip()
            if cleaned:
                collected.add(cleaned)
        for preset in presets:
            for preset_word in STOP_WORD_PRESETS.get(preset, ()):
                cleaned = normalize(preset_word).strip()
                if cleaned:
                    collected.add(cleaned)

        self._size = len(collected)
        if not collected:
            self._pattern: re.Pattern[str] | None = None
            self._dense: re.Pattern[str] | None = None
            return

        # Longest first, so `долбоеб` wins over `еб` and the report names the
        # most specific match.
        ordered = sorted(collected, key=len, reverse=True)
        self._pattern = re.compile("|".join(self._to_regex(word) for word in ordered))
        # Separator-stripped variant catches `с.у.к.а`. Multi-word phrases are
        # excluded: stripping their spaces would make them match far too much.
        dense_words = [word for word in ordered if " " not in word and len(word) >= 4]
        self._dense = (
            re.compile("|".join(self._to_regex(strip_separators(w)) for w in dense_words))
            if dense_words
            else None
        )

    @staticmethod
    def _to_regex(word: str) -> str:
        if "*" not in word:
            return re.escape(word)
        return "".join(
            r"\w*" if part == "*" else re.escape(part) for part in re.split(r"(\*)", word) if part
        )

    def find(self, text: str) -> str | None:
        """Return the matched stop word, or None."""
        if self._pattern is None or not text:
            return None
        normalized = normalize(text)
        match = self._pattern.search(normalized)
        if match:
            return match.group(0)
        if self._dense is not None:
            dense_match = self._dense.search(strip_separators(normalized))
            if dense_match:
                return dense_match.group(0)
        return None

    def matches(self, text: str) -> bool:
        return self.find(text) is not None

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0


@lru_cache(maxsize=2048)
def _cached_matcher(words: tuple[str, ...], presets: tuple[str, ...]) -> StopWordMatcher:
    return StopWordMatcher(words, presets)


def matcher_for(words: Iterable[str], presets: Iterable[str] = ()) -> StopWordMatcher:
    """Memoized matcher — identical word lists across chats share one instance."""
    return _cached_matcher(tuple(sorted(words)), tuple(sorted(presets)))


def expand_presets(presets: Iterable[str]) -> list[str]:
    """Flatten preset keys into their word lists (Mini App preview)."""
    return sorted({word for key in presets for word in STOP_WORD_PRESETS.get(key, ())})


__all__ = [
    "StopWordMatcher",
    "expand_presets",
    "matcher_for",
    "normalize",
    "strip_separators",
]

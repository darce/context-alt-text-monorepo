"""Deterministic caption metrics (assessment §6c tiers 1-2, 5-6). Pure, no network.

Tier 1 gates: Must-Right string presence (any miss zeroes the image) and policy
compliance (naming while recognition is disabled zeroes the image). Tier 2:
identity insertion (corpus rate excludes policy-disabled fixtures from the
denominator). Tier 5/6 signals: FKRE, repetition ratio, tag coverage,
first-sentence gist (≤125 chars, Trewin/Williams). No hard length cap —
Williams et al.: longer descriptions score higher; penalize missing content.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_GIST_MAX_CHARS = 125
_WORD_RE = re.compile(r"[A-Za-z']+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def _contains(haystack: str, needle: str) -> bool:
    return needle.lower() in haystack.lower()


def _syllables(word: str) -> int:
    word = word.lower()
    groups = len(_VOWEL_GROUP_RE.findall(word))
    if word.endswith("e") and groups > 1 and not word.endswith(("le", "ee")):
        groups -= 1
    return max(groups, 1)


def _fkre(text: str) -> float:
    words = _WORD_RE.findall(text)
    if not words:
        return 0.0
    sentences = max(len(re.findall(r"[.!?]+", text)), 1)
    syllables = sum(_syllables(w) for w in words)
    score = 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))
    return max(0.0, min(score, 121.22))


@dataclass(frozen=True)
class CaptionScores:
    inserted_identities: list[str] = field(default_factory=list)
    missing_identities: list[str] = field(default_factory=list)
    insertion_eligible: bool = True
    must_right_failures: list[str] = field(default_factory=list)
    policy_violation: bool = False
    fkre: float = 0.0
    repetition_ratio: float = 0.0
    tag_coverage: float | None = None
    word_count: int = 0
    char_count: int = 0
    first_sentence_gist_ok: bool = True

    @property
    def must_right_pass(self) -> bool:
        return not self.must_right_failures

    @property
    def gated_score(self) -> float:
        """Hard gate: any Must-Right miss or policy violation zeroes the image."""
        if self.must_right_failures or self.policy_violation:
            return 0.0
        total = len(self.inserted_identities) + len(self.missing_identities)
        if total == 0:
            return 1.0
        return len(self.inserted_identities) / total


def score_caption(
    caption: str,
    *,
    present_identities: Sequence[str],
    must_right: Sequence[str],
    easy_wrong: Sequence[str],
    recognition_enabled: bool = True,
    objects: Sequence[str] | None = None,
) -> CaptionScores:
    inserted = [n for n in present_identities if _contains(caption, n)]
    missing = [n for n in present_identities if not _contains(caption, n)]

    must_right_failures = [s for s in must_right if not _contains(caption, s)] if recognition_enabled else []
    policy_violation = not recognition_enabled and bool(inserted)

    tokens = [w.lower() for w in _WORD_RE.findall(caption)]
    repetition = 1.0 - (len(set(tokens)) / len(tokens)) if tokens else 0.0

    tag_coverage: float | None = None
    if objects:
        hit = sum(1 for obj in objects if _contains(caption, obj))
        tag_coverage = hit / len(objects)

    first_sentence = re.split(r"(?<=[.!?])\s", caption.strip(), maxsplit=1)[0]
    gist_ok = len(first_sentence) <= _GIST_MAX_CHARS

    # easy_wrong traps are LLM-judge tier (flag + stub only in this MVP);
    # accepted here so golden entries pass through unchanged.
    _ = easy_wrong

    return CaptionScores(
        inserted_identities=inserted,
        missing_identities=missing,
        insertion_eligible=recognition_enabled,
        must_right_failures=must_right_failures,
        policy_violation=policy_violation,
        fkre=_fkre(caption),
        repetition_ratio=repetition,
        tag_coverage=tag_coverage,
        word_count=len(tokens),
        char_count=len(caption),
        first_sentence_gist_ok=gist_ok,
    )


def insertion_rate(scores: Sequence[CaptionScores]) -> float | None:
    """Corpus insertion rate: inserted / (inserted + missing) over policy-eligible images."""
    inserted = sum(len(s.inserted_identities) for s in scores if s.insertion_eligible)
    total = inserted + sum(len(s.missing_identities) for s in scores if s.insertion_eligible)
    if total == 0:
        return None
    return inserted / total

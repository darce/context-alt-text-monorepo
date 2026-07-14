"""Deterministic caption metrics (assessment §6c tiers 1-2, 5-6). Pure, no network.

Tier 1 gates: Must-Right string presence (any miss zeroes the image), policy
compliance (naming while recognition is disabled zeroes the image), and the
wrong-name trap (an easy_wrong or non-present roster name in the caption zeroes
the image — ALTQ-1 activation of the previously inert easy_wrong stub). Tier 2:
identity insertion (corpus rate excludes policy-disabled fixtures from the
denominator). Tier 5/6 signals: FKRE, repetition ratio, tag coverage,
first-sentence gist (≤125 chars, Trewin/Williams). No hard length cap —
Williams et al.: longer descriptions score higher; penalize missing content.

ALTQ-1 style axes (report-only signals, not gates — see
docs/tasks/altq/ALTQ-1-alt-text-quality-research-findings.md §5): meta-framing
detector, context-duplication ratio, sentence-count band, name-front-loading.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_GIST_MAX_CHARS = 125
_WORD_RE = re.compile(r"[A-Za-z']+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")

# Sentence-count bands per surface (findings §3/§4): the short surface (alt
# attribute) is 1-4 sentences; the long surface (extended description) is 2-8.
SHORT_SENTENCE_BAND = (1, 4)
LONG_SENTENCE_BAND = (2, 8)

# Meta-framing phrases (findings §3): alt text is read as replacement content,
# so prose about the artifact ("the image shows...") is banned style. Detection
# is report-only because a photo can legitimately depict a picture-in-picture
# ("holding a framed picture of her mother") — a gate would false-positive there.
_META_FRAMING_PHRASES = (
    "image of",
    "photo of",
    "picture of",
    "the image",
    "this image",
    "the photo",
    "this photo",
    "the picture",
    "this picture",
    "the scene captures",
    "the scene shows",
    "captures a moment",
    "in this shot",
)
_META_FRAMING_RES = tuple(
    re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE) for phrase in _META_FRAMING_PHRASES
)


def _contains(haystack: str, needle: str) -> bool:
    """Case-insensitive, word-boundary match (S2-06).

    Raw substring matching over-counted: object tag ``cat`` hit ``scattered``,
    a name matched inside a longer token (``Cristina`` in ``Cristinas``),
    inflating insertion/tag coverage and flipping policy violations on
    coincidental hits. Anchor on non-word boundaries so only whole tokens match.
    """
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, re.IGNORECASE) is not None


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
    wrong_name_hits: list[str] = field(default_factory=list)
    hallucinated_names: list[str] = field(default_factory=list)
    fkre: float = 0.0
    repetition_ratio: float = 0.0
    tag_coverage: float | None = None
    word_count: int = 0
    char_count: int = 0
    first_sentence_gist_ok: bool = True
    meta_framing_hits: list[str] = field(default_factory=list)
    context_duplication_ratio: float | None = None
    sentence_count: int = 0
    name_front_loaded: bool | None = None

    @property
    def must_right_pass(self) -> bool:
        return not self.must_right_failures

    @property
    def named_wrong_person(self) -> bool:
        """Any name in the caption that does not belong to a present identity."""
        return bool(self.wrong_name_hits or self.hallucinated_names)

    @property
    def gated_score(self) -> float | None:
        """Hard gate: a Must-Right miss, policy violation, or wrong name zeroes the image.

        Recognition-disabled images (``insertion_eligible=False``) are excluded
        from the mean_gated_score denominator (like insertion_rate) rather than
        injecting 1.0 which diluted the headline metric (VLMFIX-S3-04). Returns
        ``None`` when not eligible so callers can skip them.
        """
        # Policy / must-right / wrong-name failures always score 0 (including
        # recognition-disabled images that illegally named someone). Only clean
        # ineligible rows are excluded from the mean denominator (VLMFIX-S3-04).
        if self.must_right_failures or self.policy_violation or self.named_wrong_person:
            return 0.0
        if not self.insertion_eligible:
            return None
        total = len(self.inserted_identities) + len(self.missing_identities)
        if total == 0:
            return 1.0
        return len(self.inserted_identities) / total


def _sentences(caption: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", caption.strip()) if s]


def _context_trigram_overlap(caption: str, context_text: str) -> float | None:
    """Share of the caption's word trigrams that also appear in the context text.

    High overlap = the caption restates the caption/title instead of describing
    pixels (Williams: alt text must complement, not duplicate, surrounding
    context). ``None`` when either side has fewer than 3 word tokens.
    """

    def trigrams(text: str) -> set[tuple[str, str, str]]:
        tokens = [w.lower() for w in _WORD_RE.findall(text)]
        return {(tokens[i], tokens[i + 1], tokens[i + 2]) for i in range(len(tokens) - 2)}

    caption_tris = trigrams(caption)
    context_tris = trigrams(context_text)
    if not caption_tris or not context_tris:
        return None
    return len(caption_tris & context_tris) / len(caption_tris)


def score_caption(
    caption: str,
    *,
    present_identities: Sequence[str],
    must_right: Sequence[str],
    easy_wrong: Sequence[str],
    recognition_enabled: bool = True,
    objects: Sequence[str] | None = None,
    roster: Sequence[str] | None = None,
    context_text: str | None = None,
) -> CaptionScores:
    inserted = [n for n in present_identities if _contains(caption, n)]
    missing = [n for n in present_identities if not _contains(caption, n)]

    must_right_failures = [s for s in must_right if not _contains(caption, s)] if recognition_enabled else []
    policy_violation = not recognition_enabled and bool(inserted)

    # Wrong-name trap (ALTQ-1, was an inert stub): easy_wrong lists believable
    # roster confusions NOT in the scene — any of them appearing in the caption
    # is a wrong-name insertion, the top product risk. ``roster`` widens the trap
    # to every known identity beyond present/easy_wrong (closed-roster
    # hallucination check); present identities are never counted against it.
    wrong_name_hits = [n for n in easy_wrong if _contains(caption, n)]
    trap_names = set(present_identities) | set(easy_wrong)
    hallucinated = [n for n in (roster or []) if n not in trap_names and _contains(caption, n)]

    tokens = [w.lower() for w in _WORD_RE.findall(caption)]
    repetition = 1.0 - (len(set(tokens)) / len(tokens)) if tokens else 0.0

    tag_coverage: float | None = None
    if objects:
        hit = sum(1 for obj in objects if _contains(caption, obj))
        tag_coverage = hit / len(objects)

    sentences = _sentences(caption)
    first_sentence = sentences[0] if sentences else ""
    gist_ok = len(first_sentence) <= _GIST_MAX_CHARS

    meta_hits = [phrase for phrase, rx in zip(_META_FRAMING_PHRASES, _META_FRAMING_RES, strict=True) if rx.search(caption)]

    duplication = _context_trigram_overlap(caption, context_text) if context_text else None

    # Front-loading (Watson via Matuzovic): a present identity should appear in
    # the first gist window. Only meaningful when identities exist and naming is
    # allowed; ``None`` otherwise.
    front_loaded: bool | None = None
    if present_identities and recognition_enabled:
        head = caption[:_GIST_MAX_CHARS]
        front_loaded = any(_contains(head, n) for n in present_identities)

    return CaptionScores(
        inserted_identities=inserted,
        missing_identities=missing,
        insertion_eligible=recognition_enabled,
        must_right_failures=must_right_failures,
        policy_violation=policy_violation,
        wrong_name_hits=wrong_name_hits,
        hallucinated_names=hallucinated,
        fkre=_fkre(caption),
        repetition_ratio=repetition,
        tag_coverage=tag_coverage,
        word_count=len(tokens),
        char_count=len(caption),
        first_sentence_gist_ok=gist_ok,
        meta_framing_hits=meta_hits,
        context_duplication_ratio=duplication,
        sentence_count=len(sentences),
        name_front_loaded=front_loaded,
    )


def insertion_rate(scores: Sequence[CaptionScores]) -> float | None:
    """Corpus insertion rate: inserted / (inserted + missing) over policy-eligible images."""
    inserted = sum(len(s.inserted_identities) for s in scores if s.insertion_eligible)
    total = inserted + sum(len(s.missing_identities) for s in scores if s.insertion_eligible)
    if total == 0:
        return None
    return inserted / total


def name_precision(scores: Sequence[CaptionScores]) -> float | None:
    """Corpus name precision: correct names / all names asserted, eligible images.

    The news-captioning literature's headline metric (GoodNews, EAMA, VACNIC,
    Rule-driven) adapted to a closed roster: asserted = inserted + wrong +
    hallucinated. ``None`` when nothing was asserted.
    """
    inserted = sum(len(s.inserted_identities) for s in scores if s.insertion_eligible)
    wrong = sum(len(s.wrong_name_hits) + len(s.hallucinated_names) for s in scores if s.insertion_eligible)
    asserted = inserted + wrong
    if asserted == 0:
        return None
    return inserted / asserted


def wrong_name_image_rate(scores: Sequence[CaptionScores]) -> float | None:
    """Share of eligible images whose caption names anyone not present."""
    eligible = [s for s in scores if s.insertion_eligible]
    if not eligible:
        return None
    return sum(1 for s in eligible if s.named_wrong_person) / len(eligible)

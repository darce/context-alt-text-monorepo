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

from scripts.eval_harness.manifest import FactKind, FactPolarity, ReferenceFact

_GIST_MAX_CHARS = 125
_WORD_RE = re.compile(r"[A-Za-z']+")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


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


def contains_phrase(haystack: str, needle: str) -> bool:
    """Public word-boundary, case-insensitive phrase match (shared with placement scoring)."""
    return _contains(haystack, needle)


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
    def gated_score(self) -> float | None:
        """Hard gate: any Must-Right miss or policy violation zeroes the image.

        Recognition-disabled images (``insertion_eligible=False``) are excluded
        from the mean_gated_score denominator (like insertion_rate) rather than
        injecting 1.0 which diluted the headline metric (VLMFIX-S3-04). Returns
        ``None`` when not eligible so callers can skip them.
        """
        # Policy / must-right failures always score 0 (including recognition-disabled
        # images that illegally named someone). Only clean ineligible rows are
        # excluded from the mean denominator (VLMFIX-S3-04).
        if self.must_right_failures or self.policy_violation:
            return 0.0
        if not self.insertion_eligible:
            return None
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


# --- Fabricated-fact hallucination metric (VLM-6 S1) -------------------------
# HALLUCINATION-FIRST ranking axis. Precision-first + deterministic (LLM-judge is
# out of MVP scope): the headline fires only on AUTHORED false-polarity reference
# facts (fabrication traps), decomposed by FactKind for attributability [TEST-10].
# `true`-polarity facts give a coverage companion. The automatic count-contradiction
# is ADVISORY only (kept OUT of the headline) because face_count counts faces and
# faces subset people (a back-turned person has no face), so face_count is a LOWER
# bound on people and can't meet the precision bar for a ranking axis.

# Plural people-quantifier → minimum asserted people count, paired with a people
# noun. Conservative on purpose: only high-confidence overcount claims flag.
_PEOPLE_NOUN = r"(?:people|persons?|men|women|man|woman|figures?|individuals?|faces?)"
_COUNT_WORD = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "couple": 2,
    "pair": 2,
    "trio": 3,
    "several": 2,
    "many": 2,
    "multiple": 2,
    "group": 2,
    "crowd": 2,
}
_COUNT_CLAIM_RE = re.compile(
    rf"(?<!\w)(?P<q>{'|'.join(map(re.escape, _COUNT_WORD))}|\d+)\s+(?:of\s+)?(?:\w+\s+){{0,2}}?{_PEOPLE_NOUN}(?!\w)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FabricatedFact:
    kind: FactKind
    text: str
    matched_phrase: str


@dataclass(frozen=True)
class HallucinationScores:
    fabricated_facts: list[FabricatedFact] = field(default_factory=list)
    covered_facts: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    trap_count: int = 0  # number of false-polarity facts evaluated (headline denominator)
    count_advisory: str | None = None  # lower-confidence overcount signal, NOT in headline

    @property
    def fabricated(self) -> bool:
        return bool(self.fabricated_facts)

    @property
    def coverage(self) -> float | None:
        """Fraction of true-polarity facts the caption stated (None if none authored)."""
        total = len(self.covered_facts) + len(self.missing_facts)
        return len(self.covered_facts) / total if total else None


def _claimed_people_min(caption: str) -> int | None:
    """Highest confidently-asserted people count in the caption, or None."""
    best: int | None = None
    for match in _COUNT_CLAIM_RE.finditer(caption):
        token = match.group("q").lower()
        value = _COUNT_WORD.get(token)
        if value is None and token.isdigit():
            value = int(token)
        if value is not None and (best is None or value > best):
            best = value
    return best


def score_hallucination(
    caption: str,
    *,
    reference_facts: Sequence[ReferenceFact],
    face_count: int | None = None,
) -> HallucinationScores:
    """Score fabricated facts (headline) + coverage + advisory overcount.

    Headline fabrication: a caption that asserts any phrase of a ``false``-polarity
    reference fact has fabricated (recorded with the fact's kind). Coverage: the
    ``true``-polarity facts the caption stated. Count advisory: set when the caption
    confidently claims more people than ``face_count`` — reported, never in the
    headline (faces subset people).
    """
    fabricated: list[FabricatedFact] = []
    covered: list[str] = []
    missing: list[str] = []
    trap_count = 0
    seen: set[tuple[str, FactKind, FactPolarity, tuple[str, ...]]] = set()
    for fact in reference_facts:
        identity = (fact.text, fact.kind, fact.polarity, tuple(fact.phrases))
        if identity in seen:
            continue  # a duplicated reference fact must not double-count coverage/fabrication (D-04)
        seen.add(identity)
        targets = fact.match_targets()
        hit = next((t for t in targets if _contains(caption, t)), None)
        if fact.polarity is FactPolarity.FALSE:
            trap_count += 1
            if hit is not None:
                fabricated.append(FabricatedFact(kind=fact.kind, text=fact.text, matched_phrase=hit))
        else:
            (covered if hit is not None else missing).append(fact.text)

    advisory: str | None = None
    if face_count is not None:
        claimed = _claimed_people_min(caption)
        if claimed is not None and claimed > face_count:
            advisory = f"claims >={claimed} people; face_count={face_count} (advisory: faces subset people)"

    return HallucinationScores(
        fabricated_facts=fabricated,
        covered_facts=covered,
        missing_facts=missing,
        trap_count=trap_count,
        count_advisory=advisory,
    )


def fabricated_fact_rate(scores: Sequence[HallucinationScores], *, over: str = "all") -> float | None:
    """Fraction of IMAGES caught fabricating (a lower bound — only authored traps fire).

    Image-level: an image counts once toward ``caught`` if it tripped ANY trap, however
    many it tripped. ``over='all'`` denominates over every scored image (corpus caught-
    rate); ``over='trapped'`` denominates only over images that authored >=1 false-fact
    (caught-rate AMONG trapped images — NOT a per-trap-instance rate: a 3-trap image that
    trips 1 counts as fully caught). Returns None when the denominator is empty.
    """
    if over not in ("all", "trapped"):
        raise ValueError("over must be 'all' or 'trapped'")
    denom = len(scores) if over == "all" else sum(1 for s in scores if s.trap_count)
    if denom == 0:
        return None
    caught = sum(1 for s in scores if s.fabricated)
    return caught / denom


def fabrication_by_kind(scores: Sequence[HallucinationScores]) -> dict[FactKind, int]:
    """Attributability breakdown: fabricated-fact hits per FactKind [TEST-10, OBS-01]."""
    tally: dict[FactKind, int] = {}
    for score in scores:
        for fact in score.fabricated_facts:
            tally[fact.kind] = tally.get(fact.kind, 0) + 1
    return tally

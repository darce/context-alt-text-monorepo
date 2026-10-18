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
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field

from scripts.eval_harness.manifest import FactKind, FactPolarity, ReferenceFact

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
    # NFC-normalize both sides (ALTQ-1-REV-A-10): the wrong-name/hallucination
    # HARD GATE rides on this helper, and an NFD manifest name vs an NFC model
    # caption must not let a wrong name escape (same drift class as S1-07).
    haystack = unicodedata.normalize("NFC", haystack)
    needle = unicodedata.normalize("NFC", needle)
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

        Returns ``None`` when the identity-insertion metric does not apply to this
        image so aggregates can exclude it from the mean denominator rather than
        treating it as a perfect score (UXR-07: a rate needs a denominator).

        Not applicable when:
        - recognition is disabled and the caption is clean (VLMFIX-S3-04), or
        - recognition is enabled but no present identities form a denominator
          (VLM6-R4-01: empty identity set is not a win — vacuous 1.0 is the bug).

        Hard-gate failures (must-right / policy / wrong-name) still score 0.0 even
        on otherwise N/A rows so naming violations remain visible.
        """
        # Policy / must-right / wrong-name failures always score 0 (including
        # recognition-disabled images that illegally named someone). Only clean
        # N/A rows are excluded from the mean denominator.
        if self.must_right_failures or self.policy_violation or self.named_wrong_person:
            return 0.0
        if not self.insertion_eligible:
            return None
        total = len(self.inserted_identities) + len(self.missing_identities)
        if total == 0:
            # Empty identity set: metric undefined, not a perfect score (VLM6-R4-01).
            return None
        return len(self.inserted_identities) / total


_NAME_TOKEN_MIN_CHARS = 3


def _name_tokens(name: str) -> list[str]:
    """Distinctive tokens of a personal name: length >= 3 filters initials and
    particles ('J.', 'de') that would over-trigger the trap."""
    return [t for t in _WORD_RE.findall(name) if len(t) >= _NAME_TOKEN_MIN_CHARS]


def _trap_hit(caption: str, trap_name: str, present_tokens: set[str]) -> bool:
    """True when the caption mentions the trap name fully OR by any distinctive
    token not shared with a present identity (ALTQ-1-REV-B-01)."""
    if _contains(caption, trap_name):
        return True
    return any(t.lower() not in present_tokens and _contains(caption, t) for t in _name_tokens(trap_name))


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
    #
    # Trap matching is TOKEN-level (ALTQ-1-REV-B-01): a caption saying just
    # "Muted" must trip the "Muted Yarrow" trap — full-name-only matching reads
    # as perfect distractor resistance while the model names the wrong person.
    # Tokens shared with a present identity (family surname) are excluded so a
    # correct "Russet Fathom" never trips a "Muted Fathom" trap [GRPH-18].
    # Insertion credit above stays full-name (strict): credit requires the whole
    # name; a violation triggers on any distinctive fragment — asymmetric by
    # design, erring toward the gate.
    present_tokens = {t.lower() for n in present_identities for t in _name_tokens(n)}
    present_set = set(present_identities)
    # A present identity erroneously listed in easy_wrong must never zero a
    # correct caption (ALTQ-1-REV-A-05).
    wrong_name_hits = [n for n in easy_wrong if n not in present_set and _trap_hit(caption, n, present_tokens)]
    trap_names = set(present_identities) | set(easy_wrong)
    hallucinated = [n for n in (roster or []) if n not in trap_names and _trap_hit(caption, n, present_tokens)]

    tokens = [w.lower() for w in _WORD_RE.findall(caption)]
    repetition = 1.0 - (len(set(tokens)) / len(tokens)) if tokens else 0.0

    tag_coverage: float | None = None
    if objects:
        hit = sum(1 for obj in objects if _contains(caption, obj))
        tag_coverage = hit / len(objects)

    sentences = _sentences(caption)
    first_sentence = sentences[0] if sentences else ""
    gist_ok = len(first_sentence) <= _GIST_MAX_CHARS

    meta_hits = [
        phrase for phrase, rx in zip(_META_FRAMING_PHRASES, _META_FRAMING_RES, strict=True) if rx.search(caption)
    ]

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


@dataclass(frozen=True)
class GatedScoreAggregate:
    """Corpus mean of applicable ``gated_score`` values with exclusion accounting.

    ``mean`` is ``None`` when no scored items remain (empty corpus or all N/A).
    ``scored`` is the mean's denominator; ``excluded`` is how many items were
    N/A (``gated_score is None``). UXR-15: surfaces components so a composite
    cannot silently absorb inapplicable rows as successes.
    """

    mean: float | None
    scored: int
    excluded: int


def aggregate_gated_scores(scores: Sequence[CaptionScores]) -> GatedScoreAggregate:
    """Mean gated score excluding N/A items; report how many were excluded.

    Callers (report wiring) must use ``scored``/``excluded`` rather than inventing
    a denominator from ``len(scores)`` (rg-015). Hard-gate zeros stay in the mean.
    """
    values = [g for s in scores if (g := s.gated_score) is not None]
    scored = len(values)
    excluded = len(scores) - scored
    mean = (sum(values) / scored) if scored else None
    return GatedScoreAggregate(mean=mean, scored=scored, excluded=excluded)


def mean_gated_score(scores: Sequence[CaptionScores]) -> float | None:
    """Corpus mean of applicable gated scores (None when denominator empty)."""
    return aggregate_gated_scores(scores).mean


def name_precision(scores: Sequence[CaptionScores]) -> float | None:
    """Corpus name precision: correct names / all names asserted, over ALL rows.

    The news-captioning literature's headline metric (GoodNews, EAMA, VACNIC,
    Rule-driven) adapted to a closed roster. One denominator for every scored
    row (ALTQ-1-REV-A-06/B-02): on a recognition-disabled row any asserted name
    is a policy violation, so its insertions count as incorrect assertions and
    its wrong/hallucinated names count like everyone else's. ``None`` when
    nothing was asserted.
    """
    correct = sum(len(s.inserted_identities) for s in scores if s.insertion_eligible)
    asserted = sum(len(s.inserted_identities) + len(s.wrong_name_hits) + len(s.hallucinated_names) for s in scores)
    if asserted == 0:
        return None
    return correct / asserted


def wrong_name_image_rate(scores: Sequence[CaptionScores]) -> float | None:
    """Share of ALL scored images whose caption names anyone not present.

    Same all-rows denominator as ``name_precision`` and the report's
    ``wrong_name_images`` count (ALTQ-1-REV-A-06/B-02): a wrong name on a
    recognition-disabled image is still a wrong name. Policy violations
    (naming a *present* identity while recognition is disabled) stay a separate
    count — different failure class.
    """
    if not scores:
        return None
    return sum(1 for s in scores if s.named_wrong_person) / len(scores)


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
    trips 1 counts as fully caught).

    Returns ``None`` when there is no trap coverage at all (EVAL-19 / VLM6-C-05): a
    vacuous 0/N rate over untrapped images would read as "zero hallucination" where
    the truth is "undefined". Trap coverage is the only honest denominator — do not
    divide an error by a volume the system controls when π(traps)=0.
    """
    if over not in ("all", "trapped"):
        raise ValueError("over must be 'all' or 'trapped'")
    # EVAL-19: without any authored traps the rate is non-observable, not 0.0.
    if sum(s.trap_count for s in scores) == 0:
        return None
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

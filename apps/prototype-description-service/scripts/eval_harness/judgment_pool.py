"""Multi-contributor judgment pooling with incompleteness disclosure (EVAL-25).

Candidate facts come from more than one source (caption models, prompt variants,
a human pass). A single source pooling itself is the named EVAL-25 bias: every
fact that source never mentioned stays invisible, and unjudged material silently
becomes a negative. This module refuses that construction and requires the
report renderer to print that unjudged pooled items are not negatives.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from .manifest import FactPolarity

UNJUDGED_ARE_NOT_NEGATIVES_DISCLOSURE = (
    "unjudged_are_not_negatives=true: unjudged pooled candidates are not "
    "known-nonrelevant; incompleteness is by design (EVAL-25)."
)


class SingleContributorPoolError(ValueError):
    """Fewer than two contributors: a self-pool is EVAL-25's named bias, not a degraded mode."""


@dataclass(frozen=True)
class CandidateFact:
    """One contributor's offered fact. Polarity is first-class (MLDATA-30)."""

    text: str
    polarity: FactPolarity | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("candidate fact text must be non-blank")


@dataclass(frozen=True)
class PooledFact:
    text: str
    polarity: FactPolarity | None
    pooled_from: tuple[str, ...]
    pool_rank: Mapping[str, int]
    key: str


@dataclass(frozen=True)
class JudgmentPool:
    items: tuple[PooledFact, ...]
    contributors: tuple[str, ...]
    depth: int


@dataclass(frozen=True)
class PoolIncompleteness:
    unjudged_count: int
    unique_contribution_count: Mapping[str, int]
    unjudged_are_not_negatives: bool = True
    judged_count: int = 0
    pooled_count: int = 0
    depth: int = 0
    contributors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Silence about incompleteness is the EVAL-25 failure mode — the flag
        # is an invariant of this report, not a caller-tunable.
        if self.unjudged_are_not_negatives is not True:
            raise ValueError("unjudged_are_not_negatives is an EVAL-25 invariant and must be True")

    def render(self) -> str:
        unique_bits = ", ".join(
            f"{cid}={count}" for cid, count in self.unique_contribution_count.items()
        )
        return "\n".join(
            (
                f"contributors={','.join(self.contributors)}",
                f"depth={self.depth}",
                f"pooled={self.pooled_count}",
                f"judged={self.judged_count}",
                f"unjudged={self.unjudged_count}",
                f"unique_contribution_count={unique_bits}",
                UNJUDGED_ARE_NOT_NEGATIVES_DISCLOSURE,
            )
        )


@dataclass
class _Accumulator:
    text: str
    polarity: FactPolarity | None
    pooled_from: list[str] = field(default_factory=list)
    pool_rank: dict[str, int] = field(default_factory=dict)


def normalize_fact_text(text: str) -> str:
    """NFC + casefold + collapsed whitespace — pooling identity for a fact string."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def pool_key(text: str, polarity: FactPolarity | None = None) -> str:
    """Stable dedupe key. Polarity is part of identity so a trap does not collapse onto a true twin."""
    tag = polarity.value if polarity is not None else "_"
    return f"{tag}:{normalize_fact_text(text)}"


def _as_fact(raw: CandidateFact | str) -> CandidateFact:
    if isinstance(raw, CandidateFact):
        return raw
    if isinstance(raw, str):
        return CandidateFact(text=raw)
    raise TypeError(f"candidate fact must be CandidateFact or str, got {type(raw).__name__}")


def build_pool(
    *,
    contributions: Mapping[str, Sequence[CandidateFact | str]],
    depth: int,
) -> JudgmentPool:
    """Union the top ``depth`` candidates per contributor; refuse a single-source pool.

    ``pool_rank`` is 1-based position in that contributor's truncated list.
    """
    if type(depth) is not int or depth < 1:
        raise ValueError(f"depth must be a positive int, got {depth!r}")
    contributor_ids = tuple(contributions)
    if len(contributor_ids) < 2:
        raise SingleContributorPoolError(
            f"EVAL-25 refuses a single-contributor pool (got {len(contributor_ids)}); "
            "one source pooling itself is the named bias, not a degraded mode. "
            "Pass at least two contributors."
        )
    if any(not cid or not str(cid).strip() for cid in contributor_ids):
        raise ValueError("contributor id must be non-empty")

    seen: dict[str, _Accumulator] = {}
    for cid, raw_facts in contributions.items():
        truncated = list(raw_facts)[:depth]
        for rank, raw in enumerate(truncated, start=1):
            fact = _as_fact(raw)
            key = pool_key(fact.text, fact.polarity)
            acc = seen.get(key)
            if acc is None:
                seen[key] = _Accumulator(
                    text=fact.text,
                    polarity=fact.polarity,
                    pooled_from=[cid],
                    pool_rank={cid: rank},
                )
                continue
            if cid not in acc.pool_rank:
                acc.pooled_from.append(cid)
                acc.pool_rank[cid] = rank

    items = tuple(
        PooledFact(
            text=acc.text,
            polarity=acc.polarity,
            pooled_from=tuple(acc.pooled_from),
            pool_rank=MappingProxyType(dict(acc.pool_rank)),
            key=key,
        )
        for key, acc in seen.items()
    )
    return JudgmentPool(items=items, contributors=contributor_ids, depth=depth)


def _judged_keys(
    *,
    pool: JudgmentPool,
    judged: Collection[CandidateFact | PooledFact | str],
) -> set[str]:
    by_key = {item.key: item for item in pool.items}
    by_text: dict[str, list[str]] = {}
    for item in pool.items:
        by_text.setdefault(normalize_fact_text(item.text), []).append(item.key)

    matched: set[str] = set()
    for raw in judged:
        if isinstance(raw, PooledFact):
            matched.add(raw.key)
            continue
        if isinstance(raw, CandidateFact):
            matched.add(pool_key(raw.text, raw.polarity))
            continue
        if not isinstance(raw, str):
            raise TypeError(f"judged item must be fact or str, got {type(raw).__name__}")
        if raw in by_key:
            matched.add(raw)
            continue
        matched.update(by_text.get(normalize_fact_text(raw), ()))
    return matched


def incompleteness_report(
    *,
    pool: JudgmentPool,
    judged: Collection[CandidateFact | PooledFact | str],
) -> PoolIncompleteness:
    """Count unjudged pooled candidates and per-contributor unique coverage.

    Unique contribution is the count of pooled items that *only* this contributor
    produced. A contributor whose every item is a duplicate of another source
    adds no coverage — that count is 0, not omitted.
    """
    judged_keys = _judged_keys(pool=pool, judged=judged)
    unjudged_count = sum(1 for item in pool.items if item.key not in judged_keys)
    unique: dict[str, int] = {cid: 0 for cid in pool.contributors}
    for item in pool.items:
        if len(item.pooled_from) == 1:
            unique[item.pooled_from[0]] += 1
    return PoolIncompleteness(
        unjudged_count=unjudged_count,
        unique_contribution_count=MappingProxyType(unique),
        unjudged_are_not_negatives=True,
        judged_count=len(pool.items) - unjudged_count,
        pooled_count=len(pool.items),
        depth=pool.depth,
        contributors=pool.contributors,
    )

"""EVAL-25 judgment pool: multi-contributor union, depth, incompleteness disclosure."""

import pytest

from scripts.eval_harness.judgment_pool import (
    UNJUDGED_ARE_NOT_NEGATIVES_DISCLOSURE,
    CandidateFact,
    SingleContributorPoolError,
    build_pool,
    incompleteness_report,
)
from scripts.eval_harness.manifest import FactPolarity


def test_overlapping_facts_deduped_and_pooled_from_both():
    pool = build_pool(
        contributions={
            "model_a": ["red hat", "blue coat", "lake"],
            "model_b": ["RED HAT", "green boots"],
        },
        depth=5,
    )
    by_norm = {item.key: item for item in pool.items}
    overlap = next(item for item in pool.items if "red hat" in item.key)
    assert overlap.pooled_from == ("model_a", "model_b")
    assert overlap.pool_rank["model_a"] == 1
    assert overlap.pool_rank["model_b"] == 1
    assert len(by_norm) == 4


def test_single_contributor_pool_raises():
    with pytest.raises(SingleContributorPoolError, match="EVAL-25"):
        build_pool(contributions={"model_a": ["red hat"]}, depth=5)
    with pytest.raises(SingleContributorPoolError, match="EVAL-25"):
        build_pool(contributions={}, depth=5)


def test_depth_truncates_per_contributor_not_globally():
    pool = build_pool(
        contributions={
            "model_a": ["a1", "a2", "a3", "a4"],
            "model_b": ["b1", "b2", "b3", "b4"],
        },
        depth=2,
    )
    texts = [item.text for item in pool.items]
    assert texts == ["a1", "a2", "b1", "b2"]
    assert "a3" not in texts and "b3" not in texts
    assert pool.depth == 2


def test_incompleteness_counts_unjudged_and_zero_unique_for_pure_duplicate_contributor():
    pool = build_pool(
        contributions={
            "model_a": ["red hat", "blue coat", "lake"],
            "model_b": ["red hat", "blue coat"],
        },
        depth=5,
    )
    report = incompleteness_report(pool=pool, judged=["red hat"])
    assert report.pooled_count == 3
    assert report.judged_count == 1
    assert report.unjudged_count == 2
    assert report.unique_contribution_count["model_a"] == 1
    assert report.unique_contribution_count["model_b"] == 0


def test_unjudged_are_not_negatives_disclosure_present():
    pool = build_pool(
        contributions={"human": ["lake"], "model_a": ["lake", "red hat"]},
        depth=3,
    )
    report = incompleteness_report(pool=pool, judged=[])
    assert report.unjudged_are_not_negatives is True
    rendered = report.render()
    assert "unjudged_are_not_negatives=true" in rendered
    assert UNJUDGED_ARE_NOT_NEGATIVES_DISCLOSURE in rendered


def test_pool_holds_true_and_false_polarity():
    pool = build_pool(
        contributions={
            "human": [
                CandidateFact(text="red hat", polarity=FactPolarity.TRUE),
                CandidateFact(text="unicorn", polarity=FactPolarity.FALSE),
            ],
            "model_a": [CandidateFact(text="red hat", polarity=FactPolarity.TRUE)],
        },
        depth=5,
    )
    polarities = {item.polarity for item in pool.items}
    assert FactPolarity.TRUE in polarities
    assert FactPolarity.FALSE in polarities
    assert len(pool.items) == 2

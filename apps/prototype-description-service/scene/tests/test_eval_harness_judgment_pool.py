"""EVAL-25 judgment pool: multi-contributor union, depth, incompleteness disclosure."""

import pytest

from scripts.eval_harness.judgment_pool import (
    UNJUDGED_ARE_NOT_NEGATIVES_DISCLOSURE,
    AmbiguousJudgmentError,
    CandidateFact,
    SingleContributorPoolError,
    build_pool,
    incompleteness_report,
)
from scripts.eval_harness.manifest import FactPolarity, ReferenceFact


def _complementary_red_hat_pool():
    return build_pool(
        contributions={
            "human": [
                CandidateFact(text="red hat", polarity=FactPolarity.TRUE),
                CandidateFact(text="red hat", polarity=FactPolarity.FALSE),
            ],
            "model_a": [CandidateFact(text="red hat", polarity=FactPolarity.TRUE)],
            "model_b": [CandidateFact(text="red hat", polarity=FactPolarity.TRUE)],
        },
        depth=5,
    )


def test_overlapping_facts_deduped_and_pooled_from_both():
    pool = build_pool(
        contributions={
            "model_a": ["red hat", "blue coat", "lake"],
            "model_b": ["RED HAT", "green boots"],
            "human": ["lake"],
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


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        (2, ["a1", "a2", "b1", "b2", "h1", "h2"]),
        (3, ["a1", "a2", "a3", "b1", "b2", "b3", "h1", "h2", "h3"]),
    ],
)
def test_depth_truncates_per_contributor_not_globally(depth, expected):
    pool = build_pool(
        contributions={
            "model_a": ["a1", "a2", "a3", "a4"],
            "model_b": ["b1", "b2", "b3", "b4"],
            "human": ["h1", "h2", "h3", "h4"],
        },
        depth=depth,
    )
    texts = [item.text for item in pool.items]
    assert texts == expected
    assert pool.depth == depth


def test_incompleteness_counts_unjudged_and_zero_unique_for_pure_duplicate_contributor():
    pool = build_pool(
        contributions={
            "model_a": ["red hat", "blue coat", "lake"],
            "model_b": ["red hat", "blue coat"],
            "human": ["red hat"],
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
        contributions={
            "human": ["lake"],
            "model_a": ["lake", "red hat"],
            "model_b": ["lake"],
        },
        depth=3,
    )
    report = incompleteness_report(pool=pool, judged=[])
    assert report.unjudged_are_not_negatives is True
    rendered = report.render()
    assert "unjudged_are_not_negatives=true" in rendered
    assert UNJUDGED_ARE_NOT_NEGATIVES_DISCLOSURE in rendered


def test_pool_holds_true_and_false_polarity():
    pool = _complementary_red_hat_pool()
    by_polarity = {item.polarity: item for item in pool.items}
    assert len(pool.items) == 2
    assert set(by_polarity) == {FactPolarity.TRUE, FactPolarity.FALSE}
    true_item = by_polarity[FactPolarity.TRUE]
    false_item = by_polarity[FactPolarity.FALSE]
    assert true_item.key != false_item.key
    assert true_item.text.casefold() == "red hat"
    assert false_item.text.casefold() == "red hat"


def test_candidate_fact_judgment_does_not_mark_complementary_polarity():
    pool = _complementary_red_hat_pool()
    true_item = next(item for item in pool.items if item.polarity is FactPolarity.TRUE)
    false_item = next(item for item in pool.items if item.polarity is FactPolarity.FALSE)
    judged_true = CandidateFact(text="red hat", polarity=FactPolarity.TRUE)

    report = incompleteness_report(pool=pool, judged=[judged_true])
    assert report.pooled_count == 2
    assert report.judged_count == 1
    assert report.unjudged_count == 1
    assert report.unjudged_are_not_negatives is True

    # Union with the TRUE pooled slot is a no-op: same key, complement still open.
    # An inverted-polarity mutant marks FALSE instead, so this union would close the pool.
    same_slot = incompleteness_report(pool=pool, judged=[judged_true, true_item])
    assert same_slot.judged_count == 1
    assert same_slot.unjudged_count == 1

    both = incompleteness_report(pool=pool, judged=[judged_true, false_item])
    assert both.judged_count == 2
    assert both.unjudged_count == 0


def test_ambiguous_bare_string_judgment_raises():
    pool = _complementary_red_hat_pool()
    with pytest.raises(AmbiguousJudgmentError, match="red hat") as exc_info:
        incompleteness_report(pool=pool, judged=["red hat"])
    message = str(exc_info.value)
    assert "true:red hat" in message
    assert "false:red hat" in message
    assert "PooledFact" in message
    assert "CandidateFact" in message


def test_unique_bare_string_judgment_resolves():
    pool = build_pool(
        contributions={
            "human": [
                CandidateFact(text="red hat", polarity=FactPolarity.TRUE),
                CandidateFact(text="blue coat", polarity=FactPolarity.TRUE),
            ],
            "model_a": [CandidateFact(text="red hat", polarity=FactPolarity.FALSE)],
            "model_b": [CandidateFact(text="blue coat", polarity=FactPolarity.TRUE)],
        },
        depth=5,
    )
    report = incompleteness_report(pool=pool, judged=["BLUE COAT"])
    assert report.pooled_count == 3
    assert report.judged_count == 1
    assert report.unjudged_count == 2
    assert report.unjudged_are_not_negatives is True


def test_bare_string_pool_key_marks_one_polarity():
    pool = _complementary_red_hat_pool()
    true_item = next(item for item in pool.items if item.polarity is FactPolarity.TRUE)
    report = incompleteness_report(pool=pool, judged=[true_item.key])
    assert report.judged_count == 1
    assert report.unjudged_count == 1
    assert report.unjudged_are_not_negatives is True

    pooled = incompleteness_report(pool=pool, judged=[true_item])
    assert pooled.judged_count == 1
    assert pooled.unjudged_count == 1
    assert pooled.unjudged_are_not_negatives is True


def test_same_model_family_prompt_variants_are_not_independent():
    """EVAL-25: model_a and model_a_t07 are one family, not two contributors.

    A human pass does not make prompt variants independent — otherwise the
    family check is dead and only the human check fires.
    """
    with pytest.raises(ValueError, match="family"):
        build_pool(
            contributions={
                "human": ["lake"],
                "model_a": ["red hat"],
                "model_a_t07": ["blue coat"],
            },
            depth=5,
        )


def test_pool_without_human_contributor_raises():
    """EVAL-25: distinct model families still self-grade without a human pass."""
    with pytest.raises(ValueError, match="human"):
        build_pool(
            contributions={
                "model_a": ["red hat"],
                "model_b": ["blue coat"],
            },
            depth=5,
        )


def test_gold_facts_without_source_pool_cannot_be_bound():
    """EVAL-25: gold that never went through a pool cannot be used."""
    from scripts.eval_harness.judgment_pool import bind_gold

    pool = build_pool(
        contributions={
            "human": ["red hat"],
            "model_a": ["blue coat"],
            "model_b": ["green boots"],
        },
        depth=5,
    )
    gold = [
        ReferenceFact(text="red hat", kind="object", phrases=["red hat"]),
    ]
    with pytest.raises(ValueError, match="source_pool"):
        bind_gold(pool=pool, gold=gold)


def test_gold_facts_from_a_named_pool_bind():
    from scripts.eval_harness.judgment_pool import bind_gold

    pool = build_pool(
        contributions={
            "human": ["red hat"],
            "model_a": ["blue coat"],
            "model_b": ["green boots"],
        },
        depth=5,
    )
    gold = [
        ReferenceFact(
            text="red hat",
            kind="object",
            phrases=["red hat"],
            source_pool="pilot-pool-v1",
        ),
    ]
    bound = bind_gold(pool=pool, gold=gold)
    assert bound[0].source_pool == "pilot-pool-v1"

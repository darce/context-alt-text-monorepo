"""VLM-6 S1: spatial-relation placement correctness metric."""

import pytest

from scripts.eval_harness.manifest import SpatialFact, SpatialRelation
from scripts.eval_harness.placement_metrics import (
    _invert_phrase,
    placement_accuracy,
    score_placement,
)


def _fact(subject, relation, reference=None, phrases=None, reference2=None):
    return SpatialFact(
        subject=subject,
        relation=relation,
        reference=reference,
        reference2=reference2,
        phrases=phrases or [],
    )


def test_invert_phrase_swaps_directional_word():
    assert _invert_phrase("Alice to the left of Bob") == "Alice to the right of Bob"
    assert _invert_phrase("the cat above the sofa") == "the cat below the sofa"
    assert _invert_phrase("in the foreground") == "in the background"


def test_invert_phrase_none_without_direction():
    assert _invert_phrase("Alice next to Bob") is None


def test_correct_placement_claim():
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice to the left of Bob"])]
    s = score_placement("Here is Alice to the left of Bob, smiling.", spatial_facts=facts)
    assert s.correct == ["Alice left_of Bob"] and s.wrong == []
    assert s.accuracy == 1.0 and s.claims == 1


def test_wrong_placement_claim_detected_via_inversion():
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice to the left of Bob"])]
    s = score_placement("Alice to the right of Bob.", spatial_facts=facts)
    assert s.correct == []
    assert s.wrong and s.wrong[0][0] == "Alice left_of Bob"
    assert s.accuracy == 0.0 and s.claims == 1


def test_no_claim_is_not_scored():
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice to the left of Bob"])]
    s = score_placement("A pleasant afternoon by the lake.", spatial_facts=facts)
    assert s.claims == 0 and s.accuracy is None


def test_fact_without_phrases_is_skipped():
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob")]
    s = score_placement("Alice to the left of Bob.", spatial_facts=facts)
    assert s.claims == 0


def test_correct_wins_when_both_present():
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice left of Bob"])]
    # caption contains the correct phrase; inversion 'Alice right of Bob' is absent
    s = score_placement("Alice left of Bob and also chatting.", spatial_facts=facts)
    assert s.correct and not s.wrong


def test_placement_accuracy_micro():
    facts_a = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice left of Bob"])]
    facts_b = [_fact("Cara", SpatialRelation.ABOVE, "Dan", ["Cara above Dan"])]
    correct = score_placement("Alice left of Bob.", spatial_facts=facts_a)
    wrong = score_placement("Cara below Dan.", spatial_facts=facts_b)
    silent = score_placement("nothing spatial.", spatial_facts=facts_a)
    assert placement_accuracy([correct, wrong, silent]) == pytest.approx(1 / 2)
    assert placement_accuracy([silent]) is None


def test_word_boundary_precision():
    # 'left' inside 'leftover' must not trigger a claim
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["to the left"])]
    assert score_placement("Bob ate the leftover cake.", spatial_facts=facts).claims == 0

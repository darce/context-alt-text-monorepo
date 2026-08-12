"""VLM-6 S1: spatial-relation placement correctness metric."""

import scripts.eval_harness.placement_metrics as placement_metrics_mod
import pytest

from scripts.eval_harness.manifest import SpatialFact, SpatialRelation
from scripts.eval_harness.placement_metrics import (
    PlacementScores,
    _invert_phrase,
    placement_accuracy,
    score_placement,
)


def test_module_docstring_states_viewer_left_convention():
    """S3-08: relations are image/viewer-left, not anatomical left."""
    doc = placement_metrics_mod.__doc__ or ""
    assert "viewer-left" in doc
    assert "anatomical" in doc


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


def test_invert_phrase_handles_trailing_punctuation():  # VLM-6 S5 W3 / VLM6-D-02
    # A directional token with attached punctuation must still invert (was None),
    # with the punctuation preserved so the wrong-claim phrase keeps its shape.
    assert _invert_phrase("in the foreground.") == "in the background."
    assert _invert_phrase("to the left, near X") == "to the right, near X"
    assert _invert_phrase("(above)") == "(below)"


def test_between_correct_claim():  # VLM-6 S5 W2 / VLM6-D-01
    facts = [_fact("Alice", SpatialRelation.BETWEEN, "Bob", ["Alice between Bob and Carol"], "Carol")]
    s = score_placement("Here is Alice between Bob and Carol, smiling.", spatial_facts=facts)
    assert s.correct == ["Alice between Bob and Carol"] and s.wrong == []
    assert s.accuracy == 1.0 and s.claims == 1


def test_between_wrong_claim_detected():  # VLM-6 S5 W2 / VLM6-D-01
    # A wrong between-claim (a NON-subject entity in the middle) previously scored
    # as 'no claim' (accuracy=None); it must now score as wrong.
    facts = [_fact("Alice", SpatialRelation.BETWEEN, "Bob", ["Alice between Bob and Carol"], "Carol")]
    s = score_placement("The photo shows Bob between Alice and Carol.", spatial_facts=facts)
    assert s.correct == []
    assert s.wrong and s.wrong[0][0] == "Alice between Bob and Carol"
    assert s.accuracy == 0.0 and s.claims == 1


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
    # Abstention is reported, not hidden (VLM6-R4-03 / UXR-15 / UXR-07).
    assert s.abstained == ["Alice left_of Bob"]


def test_fact_without_phrases_uses_relation_structure():
    # Relation + entities are enough to score; phrases are optional authored
    # near-verbatim hints, not a hard prerequisite (VLM6-R4-03).
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob")]
    s = score_placement("Alice to the left of Bob.", spatial_facts=facts)
    assert s.correct == ["Alice left_of Bob"]
    assert s.claims == 1 and s.accuracy == 1.0


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
    assert placement_accuracy([silent]) is None  # no claims (only abstentions) → None, not 0.0
    assert silent.abstained  # caller can distinguish abstention from "no facts"


def test_word_boundary_precision():
    # 'left' inside 'leftover' must not trigger a claim
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["to the left"])]
    s = score_placement("Bob ate the leftover cake.", spatial_facts=facts)
    assert s.claims == 0
    # Alice never mentioned → abstention for the scorable fact, not a wrong claim.
    assert s.abstained == ["Alice left_of Bob"]


# --- VLM6-R4-03: paraphrase must be able to score badly (and correctly) ---


def test_paraphrased_wrong_pair_order_scores_wrong():
    """Caption asserts the opposite relation without near-verbatim inversion.

    Pre-fix: only ``contains_phrase`` on authored/inverted strings counted, so
    ``Bob is to the left of Alice`` (semantically Alice RIGHT_OF Bob) scored as
    no claim (accuracy=None). Post-fix: structural pair match → wrong / 0.0.
    """
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice to the left of Bob"])]
    s = score_placement("Bob is to the left of Alice.", spatial_facts=facts)
    assert s.correct == []
    assert s.wrong and s.wrong[0][0] == "Alice left_of Bob"
    assert s.claims == 1 and s.accuracy == 0.0
    assert s.abstained == []


def test_paraphrased_correct_pair_order_scores_correct():
    """Non-verbatim correct wording still counts (no inventing: both entities + dir)."""
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice to the left of Bob"])]
    s = score_placement("Alice is left of Bob in the frame.", spatial_facts=facts)
    assert s.correct == ["Alice left_of Bob"]
    assert s.wrong == []
    assert s.accuracy == 1.0


def test_bare_left_verb_departure_is_not_placement():
    """VLM6-B-06: 'Alice left Bob at the station' is departure, not LEFT_OF.

    Pre-fix: bare mid-token 'left' matched entity…left…entity → accuracy=1.0.
    Post-fix: require 'left of' / 'to the left of'; departure → abstention.
    """
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob")]
    s = score_placement("Alice left Bob at the station.", spatial_facts=facts)
    assert s.correct == []
    assert s.wrong == []
    assert s.claims == 0
    assert s.accuracy is None
    assert s.abstained == ["Alice left_of Bob"]


def test_genuine_placement_phrasings_still_match_pair_order():
    """VLM6-B-06: unambiguous placement constructions still score correct."""
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob")]
    for caption in (
        "Alice to the left of Bob.",
        "Alice is left of Bob.",
        "Bob to the right of Alice.",  # inverse wording, same relation
    ):
        s = score_placement(caption, spatial_facts=facts)
        assert s.correct == ["Alice left_of Bob"], caption
        assert s.accuracy == 1.0, caption
        assert s.claims == 1, caption


def test_paraphrased_absolute_wrong_scores_wrong():
    """Subject-centric absolute placement that contradicts the fact scores wrong.

    ``the man stands on the right`` does not contain the authored phrase
    ``left of the woman`` nor its token-swap ``right of the woman`` as a
    free-standing claim about the pair, but it does assert the man is on the
    right — contradictory to LEFT_OF. Pre-fix: claims=0 / accuracy=None.
    """
    facts = [
        _fact("the man", SpatialRelation.LEFT_OF, "the woman", ["left of the woman"]),
    ]
    s = score_placement("the man stands on the right.", spatial_facts=facts)
    assert s.correct == []
    assert s.wrong and s.wrong[0][0] == "the man left_of the woman"
    assert s.claims == 1 and s.accuracy == 0.0


def test_paraphrased_absolute_correct_scores_correct():
    facts = [
        _fact("the man", SpatialRelation.LEFT_OF, "the woman", ["left of the woman"]),
    ]
    s = score_placement("the man is on the left.", spatial_facts=facts)
    assert s.correct == ["the man left_of the woman"]
    assert s.accuracy == 1.0


def test_above_below_structural_wrong():
    facts = [_fact("lamp", SpatialRelation.ABOVE, "table", ["lamp above the table"])]
    s = score_placement("The lamp sits below the table.", spatial_facts=facts)
    assert s.accuracy == 0.0 and s.claims == 1
    assert s.wrong[0][0] == "lamp above table"


def test_foreground_structural_wrong():
    facts = [_fact("dog", SpatialRelation.FOREGROUND, phrases=["dog in the foreground"])]
    s = score_placement("A dog in the background near the hedge.", spatial_facts=facts)
    assert s.accuracy == 0.0 and s.claims == 1


def test_abstention_vs_zero_accuracy_are_distinct():
    """MEAS-11 / VLM6-R4-03: None means no claims; 0.0 means claimed-and-wrong."""
    facts = [_fact("Alice", SpatialRelation.LEFT_OF, "Bob", ["Alice to the left of Bob"])]
    silent = score_placement("No people are described.", spatial_facts=facts)
    wrong = score_placement("Bob is to the left of Alice.", spatial_facts=facts)
    assert silent.accuracy is None and silent.claims == 0 and len(silent.abstained) == 1
    assert wrong.accuracy == 0.0 and wrong.claims == 1 and wrong.abstained == []
    # Micro-average over only-abstention runs stays None (not 0.0).
    assert placement_accuracy([silent, silent]) is None
    assert placement_accuracy([wrong]) == 0.0


def test_placement_scores_exposes_abstained_field():
    empty = PlacementScores()
    assert empty.abstained == []
    assert empty.claims == 0
    assert empty.accuracy is None

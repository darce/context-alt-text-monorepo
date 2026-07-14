"""VLM-2A Slice 2: caption deterministic metrics (assessment §6c tiers 1-2, 5-6)."""

import pytest

from scripts.eval_harness.caption_metrics import (
    CaptionScores,
    insertion_rate,
    name_precision,
    score_caption,
    wrong_name_image_rate,
)


def _entry(**overrides):
    base = {
        "present_identities": ["Alice Example"],
        "must_right": ["Alice Example"],
        "easy_wrong": [],
        "recognition_enabled": True,
    }
    base.update(overrides)
    return base


CAPTION = "Alice Example stands by a lake. The water is calm and blue."


def test_identity_insertion_detected():
    scores = score_caption(CAPTION, **_entry())
    assert scores.inserted_identities == ["Alice Example"]
    assert scores.missing_identities == []


def test_identity_insertion_case_insensitive():
    scores = score_caption(CAPTION.lower(), **_entry())
    assert scores.inserted_identities == ["Alice Example"]


def test_missing_identity_reported():
    scores = score_caption("A person stands by a lake.", **_entry())
    assert scores.inserted_identities == []
    assert scores.missing_identities == ["Alice Example"]


def test_must_right_gate_zeroes_on_failure():
    scores = score_caption("A person stands by a lake.", **_entry())
    assert scores.must_right_failures == ["Alice Example"]
    assert scores.must_right_pass is False
    assert scores.gated_score == 0.0


def test_must_right_gate_passes():
    scores = score_caption(CAPTION, **_entry())
    assert scores.must_right_failures == []
    assert scores.must_right_pass is True
    assert scores.gated_score > 0.0


def test_policy_disabled_naming_is_violation():
    scores = score_caption(CAPTION, **_entry(recognition_enabled=False, must_right=[]))
    assert scores.policy_violation is True
    assert scores.gated_score == 0.0


def test_policy_disabled_without_name_is_clean():
    scores = score_caption(
        "A person stands by a lake.",
        **_entry(recognition_enabled=False, must_right=[]),
    )
    assert scores.policy_violation is False
    # VLMFIX-S3-04: clean recognition-disabled images are excluded from
    # mean_gated_score (None), not injected as 1.0.
    assert scores.insertion_eligible is False
    assert scores.gated_score is None


def test_repetition_ratio():
    scores = score_caption("blue blue blue blue", **_entry(must_right=[]))
    assert scores.repetition_ratio == pytest.approx(0.75)


def test_fkre_in_plausible_band():
    scores = score_caption(CAPTION, **_entry())
    assert isinstance(scores.fkre, float)
    assert 0.0 <= scores.fkre <= 121.22  # theoretical FKRE bounds


def test_tag_coverage():
    scores = score_caption(
        "A dog runs on the beach.",
        **_entry(must_right=[], present_identities=[]),
        objects=["dog", "beach", "frisbee"],
    )
    assert scores.tag_coverage == pytest.approx(2 / 3)


def test_tag_coverage_none_without_objects():
    scores = score_caption(CAPTION, **_entry())
    assert scores.tag_coverage is None


def test_tag_coverage_word_boundary_no_substring_hit():  # S2-06
    # object tag 'cat' must not match 'scattered'
    scores = score_caption(
        "Leaves are scattered on the ground.",
        **_entry(must_right=[], present_identities=[]),
        objects=["cat"],
    )
    assert scores.tag_coverage == 0.0


def test_identity_word_boundary_no_substring_hit():  # S2-06
    # 'Cristina' must not match inside 'Cristinas'
    scores = score_caption(
        "Cristinas belongings sit on a table.", **_entry(present_identities=["Cristina"], must_right=[])
    )
    assert scores.inserted_identities == []
    assert scores.missing_identities == ["Cristina"]


def test_first_sentence_gist_flag():
    ok = score_caption("Short gist. " + "x" * 300, **_entry(must_right=[]))
    assert ok.first_sentence_gist_ok is True
    long_first = score_caption("y" * 200 + ". More.", **_entry(must_right=[]))
    assert long_first.first_sentence_gist_ok is False


def test_scores_are_deterministic():
    a = score_caption(CAPTION, **_entry())
    b = score_caption(CAPTION, **_entry())
    assert a == b
    assert isinstance(a, CaptionScores)


# --- corpus-level insertion rate ---


def test_insertion_rate_over_corpus():
    scores = [
        score_caption(CAPTION, **_entry()),
        score_caption("A person by a lake.", **_entry()),
    ]
    # 1 of 2 eligible identities inserted
    assert insertion_rate(scores) == pytest.approx(0.5)


def test_insertion_rate_excludes_policy_disabled():
    scores = [
        score_caption(CAPTION, **_entry()),
        score_caption("A person.", **_entry(recognition_enabled=False, must_right=[])),
    ]
    # policy-disabled fixture excluded from denominator
    assert insertion_rate(scores) == pytest.approx(1.0)


def test_insertion_rate_none_when_no_eligible_identities():
    scores = [score_caption("A glacier.", **_entry(present_identities=[], must_right=[]))]
    assert insertion_rate(scores) is None


# --- ALTQ-1: wrong-name trap + roster hallucination (hard gates) ---


def test_easy_wrong_name_in_caption_zeroes_gate():
    scores = score_caption(
        "Alice Example and Mallory Trap stand by a lake.",
        **_entry(easy_wrong=["Mallory Trap"]),
    )
    assert scores.wrong_name_hits == ["Mallory Trap"]
    assert scores.named_wrong_person is True
    assert scores.gated_score == 0.0


def test_roster_hallucination_zeroes_gate():
    scores = score_caption(
        "Alice Example and Bob Builder stand by a lake.",
        **_entry(),
        roster=["Alice Example", "Bob Builder", "Carol Cruz"],
    )
    assert scores.hallucinated_names == ["Bob Builder"]
    assert scores.gated_score == 0.0


def test_present_identity_never_counts_as_hallucination():
    scores = score_caption(CAPTION, **_entry(), roster=["Alice Example", "Bob Builder"])
    assert scores.hallucinated_names == []
    assert scores.wrong_name_hits == []
    assert scores.gated_score == 1.0


def test_wrong_name_gates_even_when_recognition_disabled():
    scores = score_caption(
        "Mallory Trap by a lake.",
        **_entry(recognition_enabled=False, must_right=[], easy_wrong=["Mallory Trap"]),
    )
    assert scores.gated_score == 0.0


# --- ALTQ-1: style axes (report-only signals) ---


def test_meta_framing_detected_on_7b_winner_output():
    # Verbatim closer from the committed 7b winning caption — the defect the
    # saturated benchmark could not see.
    scores = score_caption(
        "Caitlin Weaver stands on a rocky shore. The scene captures a moment during her 2023 research residency.",
        **_entry(present_identities=["Caitlin Weaver"], must_right=["Caitlin Weaver"]),
    )
    assert "the scene captures" in scores.meta_framing_hits
    assert "captures a moment" in scores.meta_framing_hits
    assert scores.gated_score == 1.0  # report-only: style hits do NOT gate


def test_meta_framing_clean_caption_has_no_hits():
    scores = score_caption(CAPTION, **_entry())
    assert scores.meta_framing_hits == []


def test_context_duplication_high_when_caption_restates_context():
    context = "Caitlin Weaver on the Antarctic peninsula during her 2023 research residency."
    scores = score_caption(
        "Caitlin Weaver on the Antarctic peninsula during her 2023 research residency.",
        **_entry(present_identities=["Caitlin Weaver"], must_right=[]),
        context_text=context,
    )
    assert scores.context_duplication_ratio == pytest.approx(1.0)


def test_context_duplication_low_for_visual_description():
    scores = score_caption(
        "A woman in a black jacket stands on a rocky shore beside calm water.",
        **_entry(present_identities=[], must_right=[]),
        context_text="Antarctica expedition itinerary and travel notes.",
    )
    assert scores.context_duplication_ratio == pytest.approx(0.0)


def test_context_duplication_none_without_context():
    scores = score_caption(CAPTION, **_entry())
    assert scores.context_duplication_ratio is None


def test_sentence_count_counted():
    scores = score_caption("One. Two! Three?", **_entry(must_right=[], present_identities=[]))
    assert scores.sentence_count == 3


def test_name_front_loaded_true_and_false():
    front = score_caption(CAPTION, **_entry())
    assert front.name_front_loaded is True
    late = score_caption(
        "By a calm blue lake under towering peaks and a wide open sky, after a long morning hike "
        "through the valley with heavy packs, stands Alice Example.",
        **_entry(),
    )
    assert late.name_front_loaded is False


def test_name_front_loaded_none_without_identities():
    scores = score_caption("A glacier.", **_entry(present_identities=[], must_right=[]))
    assert scores.name_front_loaded is None


# --- ALTQ-1: corpus name precision / wrong-name image rate ---


def test_name_precision_counts_wrong_names_against():
    scores = [
        score_caption(CAPTION, **_entry()),
        score_caption("Mallory Trap by a lake.", **_entry(easy_wrong=["Mallory Trap"], must_right=[])),
    ]
    assert name_precision(scores) == pytest.approx(0.5)


def test_name_precision_none_when_nothing_asserted():
    scores = [score_caption("A glacier.", **_entry(present_identities=[], must_right=[]))]
    assert name_precision(scores) is None


def test_wrong_name_image_rate():
    scores = [
        score_caption(CAPTION, **_entry()),
        score_caption("Mallory Trap by a lake.", **_entry(easy_wrong=["Mallory Trap"], must_right=[])),
    ]
    assert wrong_name_image_rate(scores) == pytest.approx(0.5)

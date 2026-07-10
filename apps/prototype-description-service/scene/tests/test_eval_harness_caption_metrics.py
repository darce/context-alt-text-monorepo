"""VLM-2A Slice 2: caption deterministic metrics (assessment §6c tiers 1-2, 5-6)."""

import pytest

from scripts.eval_harness.caption_metrics import (
    CaptionScores,
    insertion_rate,
    score_caption,
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

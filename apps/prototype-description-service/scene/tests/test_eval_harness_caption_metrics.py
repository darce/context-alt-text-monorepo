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
        "Russet Fathom stands on a rocky shore. The scene captures a moment during her 2023 research residency.",
        **_entry(present_identities=["Russet Fathom"], must_right=["Russet Fathom"]),
    )
    assert "the scene captures" in scores.meta_framing_hits
    assert "captures a moment" in scores.meta_framing_hits
    assert scores.gated_score == 1.0  # report-only: style hits do NOT gate


def test_meta_framing_clean_caption_has_no_hits():
    scores = score_caption(CAPTION, **_entry())
    assert scores.meta_framing_hits == []


def test_context_duplication_high_when_caption_restates_context():
    context = "Russet Fathom on the Antarctic peninsula during her 2023 research residency."
    scores = score_caption(
        "Russet Fathom on the Antarctic peninsula during her 2023 research residency.",
        **_entry(present_identities=["Russet Fathom"], must_right=[]),
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


# --- ALTQ-1 review-fix regressions (round r07140ddf) ---


def test_first_name_only_mention_trips_trap():  # B-01 (high)
    scores = score_caption(
        "Alice Example and Muted relax by a lake.",
        **_entry(easy_wrong=["Muted Yarrow"]),
    )
    assert scores.wrong_name_hits == ["Muted Yarrow"]
    assert scores.gated_score == 0.0


def test_shared_surname_with_present_identity_does_not_trip_trap():  # B-01 guard
    scores = score_caption(
        "Russet Fathom stands on the shore.",
        **_entry(present_identities=["Russet Fathom"], must_right=["Russet Fathom"], easy_wrong=["Muted Fathom"]),
    )
    assert scores.wrong_name_hits == []
    assert scores.gated_score == 1.0


def test_token_trap_applies_to_roster_hallucinations():  # B-01
    scores = score_caption(
        "Alice Example waves at Zed across the pool.",
        **_entry(),
        roster=["Alice Example", "Zed Zenith"],
    )
    assert scores.hallucinated_names == ["Zed Zenith"]
    assert scores.gated_score == 0.0


def test_short_name_tokens_do_not_over_trigger():  # B-01 bound: initials/particles
    scores = score_caption(
        "Alice Example sits de facto at the head of the table.",
        **_entry(easy_wrong=["J. de Vries"]),
    )
    assert scores.wrong_name_hits == []


def test_name_precision_counts_policy_disabled_assertions():  # A-06/B-02
    scores = [
        score_caption(CAPTION, **_entry()),
        # recognition-disabled row asserting a present name: policy violation,
        # counted as an incorrect assertion in the shared denominator
        score_caption(CAPTION, **_entry(recognition_enabled=False, must_right=[])),
    ]
    assert name_precision(scores) == pytest.approx(0.5)


def test_wrong_name_image_rate_counts_ineligible_rows():  # A-06/B-02
    scores = [
        score_caption(CAPTION, **_entry()),
        score_caption(
            "Mallory Trap by a lake.",
            **_entry(recognition_enabled=False, must_right=[], easy_wrong=["Mallory Trap"]),
        ),
    ]
    assert wrong_name_image_rate(scores) == pytest.approx(0.5)


def test_present_identity_in_easy_wrong_never_zeroes_correct_caption():  # A-05
    scores = score_caption(CAPTION, **_entry(easy_wrong=["Alice Example"]))
    assert scores.wrong_name_hits == []
    assert scores.gated_score == 1.0


def test_nfc_nfd_name_drift_still_trips_gate():  # A-10
    import unicodedata as _ud

    nfd_name = _ud.normalize("NFD", "Zoë Quinn")
    nfc_caption = _ud.normalize("NFC", "Alice Example and Zoë Quinn by a lake.")
    scores = score_caption(nfc_caption, **_entry(easy_wrong=[nfd_name]))
    assert scores.wrong_name_hits == [nfd_name]
    assert scores.gated_score == 0.0
# --- VLM-6 S1: fabricated-fact hallucination metric --------------------------

from scripts.eval_harness.caption_metrics import (  # noqa: E402
    fabricated_fact_rate,
    fabrication_by_kind,
    score_hallucination,
)
from scripts.eval_harness.manifest import (  # noqa: E402
    FactKind,
    FactPolarity,
    ReferenceFact,
)


def _false_fact(text, phrases, kind=FactKind.OBJECT):
    return ReferenceFact(text=text, kind=kind, polarity=FactPolarity.FALSE, phrases=phrases)


def _true_fact(text, phrases=None, kind=FactKind.OBJECT):
    return ReferenceFact(text=text, kind=kind, polarity=FactPolarity.TRUE, phrases=phrases or [])


def test_false_fact_trap_flags_fabrication_with_kind():
    facts = [_false_fact("a dog", ["dog", "puppy"], kind=FactKind.OBJECT)]
    s = score_hallucination("A puppy playing on grass.", reference_facts=facts)
    assert s.fabricated is True
    assert s.fabricated_facts[0].kind is FactKind.OBJECT
    assert s.fabricated_facts[0].matched_phrase == "puppy"
    assert s.trap_count == 1


def test_no_fabrication_when_trap_absent():
    facts = [_false_fact("a dog", ["dog", "puppy"])]
    s = score_hallucination("A cat on a sofa.", reference_facts=facts)
    assert s.fabricated is False and s.fabricated_facts == []


def test_trap_match_is_word_boundary_not_substring():
    # 'dog' must not fire on 'dogma'/'dogged'
    facts = [_false_fact("a dog", ["dog"])]
    assert score_hallucination("A dogged pursuit of dogma.", reference_facts=facts).fabricated is False


def test_true_fact_coverage():
    facts = [_true_fact("a bicycle", ["bicycle", "bike"]), _true_fact("red color", ["red"])]
    s = score_hallucination("A red bike leaning on a wall.", reference_facts=facts)
    assert set(s.covered_facts) == {"a bicycle", "red color"}
    assert s.missing_facts == [] and s.coverage == 1.0


def test_coverage_partial_and_none_when_no_true_facts():
    facts = [_true_fact("a bicycle", ["bicycle"]), _true_fact("a hat", ["hat"])]
    s = score_hallucination("A bicycle only.", reference_facts=facts)
    assert s.covered_facts == ["a bicycle"] and s.missing_facts == ["a hat"]
    assert s.coverage == 0.5
    assert score_hallucination("x", reference_facts=[_false_fact("a", ["a"])]).coverage is None


def test_duplicate_reference_facts_counted_once():
    # A fact authored twice (same text/kind/polarity/phrases) must count once, or coverage
    # and the FactKind fabrication tally are skewed (D-04).
    facts = [
        _true_fact("a bicycle", ["bicycle"]),
        _true_fact("a bicycle", ["bicycle"]),  # duplicate authoring
        _true_fact("a hat", ["hat"]),
    ]
    s = score_hallucination("A bicycle only.", reference_facts=facts)
    assert s.covered_facts == ["a bicycle"]  # once, not twice
    assert s.missing_facts == ["a hat"]
    assert s.coverage == 0.5  # 1 / 2 distinct, not 2 / 3

    dup_trap = [_false_fact("a dog", ["dog"]), _false_fact("a dog", ["dog"])]
    s2 = score_hallucination("A dog runs.", reference_facts=dup_trap)
    assert len(s2.fabricated_facts) == 1 and s2.trap_count == 1  # one real trap, not two


def test_count_advisory_fires_on_overcount_but_not_headline():
    s = score_hallucination("Two people standing together.", reference_facts=[], face_count=1)
    assert s.count_advisory is not None and "2" in s.count_advisory
    assert s.fabricated is False  # advisory never drives the headline


def test_count_advisory_silent_when_within_facecount():
    assert score_hallucination("Three people talking.", reference_facts=[], face_count=3).count_advisory is None
    assert score_hallucination("A person walking.", reference_facts=[], face_count=1).count_advisory is None
    # no face_count -> no advisory at all
    assert score_hallucination("A crowd of people.", reference_facts=[], face_count=None).count_advisory is None


def test_count_advisory_collective_nouns():
    # A collective quantifier fires only when paired with a people noun (precision-first:
    # "a crowd of issues" / "a couple of birds" must not read as a people overcount).
    assert score_hallucination("A crowd of people.", reference_facts=[], face_count=1).count_advisory is not None
    assert score_hallucination("A group of men.", reference_facts=[], face_count=1).count_advisory is not None
    assert score_hallucination("A couple sitting.", reference_facts=[], face_count=0).count_advisory is None


def test_fabricated_fact_rate_all_vs_trapped():
    trapped_hit = score_hallucination("a dog", reference_facts=[_false_fact("a dog", ["dog"])])
    trapped_clean = score_hallucination("a cat", reference_facts=[_false_fact("a dog", ["dog"])])
    untrapped = score_hallucination("anything", reference_facts=[])
    scores = [trapped_hit, trapped_clean, untrapped]
    assert fabricated_fact_rate(scores, over="all") == pytest.approx(1 / 3)
    assert fabricated_fact_rate(scores, over="trapped") == pytest.approx(1 / 2)
    assert fabricated_fact_rate([untrapped], over="trapped") is None


def test_fabrication_by_kind_tally():
    scores = [
        score_hallucination(
            "a dog and a beach",
            reference_facts=[
                _false_fact("a dog", ["dog"], kind=FactKind.OBJECT),
                _false_fact("a beach", ["beach"], kind=FactKind.SCENE),
            ],
        ),
        score_hallucination("a dog", reference_facts=[_false_fact("a dog", ["dog"], kind=FactKind.OBJECT)]),
    ]
    tally = fabrication_by_kind(scores)
    assert tally[FactKind.OBJECT] == 2 and tally[FactKind.SCENE] == 1


def test_phrases_fallback_to_text_in_scoring():
    s = score_hallucination(
        "A red bicycle here.",
        reference_facts=[ReferenceFact(text="red bicycle", kind=FactKind.OBJECT, polarity=FactPolarity.FALSE)],
    )
    assert s.fabricated is True and s.fabricated_facts[0].matched_phrase == "red bicycle"

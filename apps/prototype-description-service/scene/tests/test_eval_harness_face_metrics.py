"""VLM-2A Slice 2: face metrics — detection + identification P/R, full scope edge ledger.

FIR-5 S3 §F extensions: face-level ID P/R, unknown-rejection, single-linkage clustering.
FIR-5 S3d: demographic Fair-SA per-cohort ID P/R (DIRECTIONAL; multi-face exclusion).
TEST-15: each metric has a can-fail fixture proven to go red.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from scripts.eval_harness.face_assignment import FaceDecision
from scripts.eval_harness.manifest import AnnotationMode, ManifestError, ScoreInvariant
from scripts.eval_harness.face_metrics import (
    DEMOGRAPHIC_SECTION_HEADER,
    UNLABELED_COHORT_KEY,
    ImageDetection,
    ImageIdentities,
    clustering_metrics_at_cut,
    clustering_sweep,
    demographic_rollup,
    detection_pr,
    face_identification_pr,
    face_unknown_rejection,
    identification_pr,
)

# --- detection level (identity-agnostic) ---


def test_detection_micro_counts():
    items = [
        ImageDetection(image="a.jpg", pred_faces=2, labeled_faces=2),
        ImageDetection(image="b.jpg", pred_faces=3, labeled_faces=2),  # 1 FP
        ImageDetection(image="c.jpg", pred_faces=1, labeled_faces=2),  # 1 FN
    ]
    result = detection_pr(items, annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert result.true_positives == 5
    assert result.false_positives == 1
    assert result.false_negatives == 1
    assert result.precision == pytest.approx(5 / 6)
    assert result.recall == pytest.approx(5 / 6)


def test_detection_zero_face_corpus_has_null_precision():
    items = [ImageDetection(image="glacier.jpg", pred_faces=0, labeled_faces=0)]
    result = detection_pr(items, annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert result.precision is None  # undefined, never 1.0
    assert result.recall is None


def test_detection_spurious_faces_on_empty_image():
    items = [ImageDetection(image="glacier.jpg", pred_faces=2, labeled_faces=0)]
    result = detection_pr(items, annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert result.precision == 0.0


def test_detection_pr_raises_against_roster_only():
    """Negative: detection scoring against a roster_only manifest raises."""
    items = [ImageDetection(image="a.jpg", pred_faces=2, labeled_faces=1)]
    with pytest.raises(ManifestError, match="detection_pr refuses roster_only") as exc_info:
        detection_pr(items, annotation_mode="roster_only")
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert "false positives" in str(exc_info.value)


def test_detection_pr_exhaustive_still_counts():
    """Positive pair: exhaustive mode still computes detection P/R."""
    items = [ImageDetection(image="a.jpg", pred_faces=2, labeled_faces=2)]
    result = detection_pr(items, annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert result.true_positives == 2
    assert result.false_positives == 0


@pytest.mark.parametrize(
    ("kwargs", "invariant"),
    [
        ({}, ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE),
        ({"annotation_mode": None}, ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE),
        ({"annotation_mode": ""}, ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE),
        ({"annotation_mode": "foo"}, ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE),
        ({"annotation_mode": "EXHAUSTIVE"}, ScoreInvariant.DETECTION_UNRECOGNISED_ANNOTATION_MODE),
    ],
    ids=["omit", "None", "empty-str", "unrecognised-foo", "EXHAUSTIVE-upper"],
)
def test_detection_pr_refuses_unless_exhaustive_enum(kwargs, invariant):
    """S2R2-02: omit / None / empty / unknown / wrong-case all refuse. No default."""
    items = [ImageDetection(image="a.jpg", pred_faces=3, labeled_faces=1)]
    with pytest.raises(ManifestError) as exc_info:
        detection_pr(items, **kwargs)
    assert exc_info.value.invariant == invariant


def test_score_face_run_record_refuses_omitted_mode():
    """S2R2-04: mapping without annotation_mode refuses (not fail-open)."""
    from scripts.eval_harness.report import score_face_run_record

    record = {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {"manifest_sha256": "m" * 64, "head_sha": "0" * 40, "started_at": "t", "leg": "candidate"},
        "items": [],
    }
    manifest = {
        "roster": ["Alice Example"],
        "entries": [
            {
                "path": "x.jpg",
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "name": "Alice Example"}],
            }
        ],
    }
    with pytest.raises(ManifestError, match="requires annotation_mode") as exc_info:
        score_face_run_record(record, manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_ANNOTATION_MODE


def test_score_face_run_record_raises_against_roster_only():
    """Negative: face-bakeoff scoring refuses a roster_only manifest."""
    from scripts.eval_harness.report import score_face_run_record

    record = {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {"manifest_sha256": "m" * 64, "head_sha": "0" * 40, "started_at": "t", "leg": "candidate"},
        "items": [],
    }
    manifest = {
        "annotation_mode": "roster_only",
        "roster": ["Alice Example"],
        "entries": [
            {
                "path": "x.jpg",
                "media_id": 1,
                "face_count": 1,
                "present_identities": ["Alice Example"],
                "must_right": [],
                "easy_wrong": [],
                "policy": {"recognition_enabled": True},
                "face_boxes": [{"x": 0.4, "y": 0.4, "w": 0.4, "h": 0.4, "name": "Alice Example"}],
            }
        ],
    }
    with pytest.raises(ManifestError, match="score_face_run_record refuses roster_only") as exc_info:
        score_face_run_record(record, manifest)
    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REFUSES_ROSTER_ONLY
    assert "false positives" in str(exc_info.value)


# --- identification level (named assertions vs labeled identities) ---


def test_identification_micro_and_wrong_names():
    items = [
        ImageIdentities(image="a.jpg", predicted=["Alice"], labeled=["Alice"]),
        ImageIdentities(image="b.jpg", predicted=["Bob"], labeled=["Alice"]),
    ]
    result = identification_pr(items)
    assert result.true_positives == 1
    assert result.false_positives == 1
    assert result.false_negatives == 1
    # wrong-name = top product risk: listed individually
    assert result.wrong_names == [("b.jpg", "Bob")]


def test_identification_duplicate_identity_deduped():
    # same person in multiple crops: dedupe by identity, not by face
    items = [
        ImageIdentities(image="a.jpg", predicted=["Alice", "Alice"], labeled=["Alice"]),
    ]
    result = identification_pr(items)
    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.precision == 1.0


def test_identification_stranger_true_rejection_not_penalized():
    items = [
        ImageIdentities(image="nina.jpg", predicted=[], labeled=[], stranger_faces=1),
    ]
    result = identification_pr(items)
    assert result.true_rejections == 1
    assert result.false_positives == 0
    assert result.precision is None  # no assertions made: undefined, not 1.0


def test_identification_stranger_true_rejection_in_mixed_image():  # S2-05
    # roster person correctly named AND a stranger present with no wrong name:
    # the stranger is a true rejection even though the image is not all-empty.
    items = [
        ImageIdentities(image="group.jpg", predicted=["Muted"], labeled=["Muted"], stranger_faces=2),
    ]
    result = identification_pr(items)
    assert result.true_rejections == 1
    assert result.true_positives == 1


def test_identification_wrong_name_on_stranger_image_is_not_a_true_rejection():  # S2-05
    items = [
        ImageIdentities(image="group.jpg", predicted=["Bob"], labeled=["Muted"], stranger_faces=1),
    ]
    result = identification_pr(items)
    assert result.true_rejections == 0  # a wrong name was asserted -> not a clean rejection
    assert result.wrong_names == [("group.jpg", "Bob")]


def test_identification_policy_disabled_excluded():
    items = [
        ImageIdentities(
            image="a.jpg",
            predicted=["Alice"],
            labeled=["Alice"],
            recognition_enabled=False,
        ),
        ImageIdentities(image="b.jpg", predicted=["Bob"], labeled=["Bob"]),
    ]
    result = identification_pr(items)
    assert result.true_positives == 1  # only b.jpg counted
    assert result.excluded_images == ["a.jpg"]


def test_identification_macro_diverges_from_micro():
    # Alice: 10 images all correct; Bob: 1 image, missed.
    items = [ImageIdentities(image=f"alice-{i}.jpg", predicted=["Alice"], labeled=["Alice"]) for i in range(10)] + [
        ImageIdentities(image="bob.jpg", predicted=[], labeled=["Bob"])
    ]
    result = identification_pr(items)
    assert result.recall == pytest.approx(10 / 11)  # micro masks Bob
    assert result.per_identity["Alice"].recall == 1.0
    assert result.per_identity["Bob"].recall == 0.0
    assert result.macro_recall == pytest.approx(0.5)  # macro exposes him


def test_identification_per_identity_precision_counts_wrong_name_against_predicted_name():
    items = [
        ImageIdentities(image="b.jpg", predicted=["Bob"], labeled=["Alice"]),
    ]
    result = identification_pr(items)
    assert result.per_identity["Bob"].precision == 0.0
    assert result.per_identity["Alice"].recall == 0.0


# ---------------------------------------------------------------------------
# FIR-5 S3 §F face-level metrics (TEST-15 can-fail fixtures)
# ---------------------------------------------------------------------------


def _dec(
    *,
    media_id: int = 1,
    box_index: int = 0,
    true_name: str | None,
    decision: str,
    predicted_name: str | None = None,
    enrolled: bool = True,
    excluded: bool = False,
    tau_k: float = 0.5,
    s_max: float = 0.8,
) -> FaceDecision:
    return FaceDecision(
        media_id=media_id,
        path=f"{media_id}.jpg",
        box_index=box_index,
        det_index=0,
        true_name=true_name,
        decision=decision,  # type: ignore[arg-type]
        predicted_name=predicted_name,
        s_max=s_max,
        name_star=predicted_name,
        tau_k=tau_k,
        fold=0,
        enrolled=enrolled,
        excluded_single_face_recall=excluded,
    )


def test_face_id_forced_wrong_name_drops_precision_and_recall():
    """TEST-15: confusion is FP on name* AND FN on true (enrolled) — both P and R drop."""
    good = [
        _dec(media_id=i, true_name="Alice", decision="accept", predicted_name="Alice")
        for i in range(4)
    ]
    wrong = _dec(
        media_id=99,
        true_name="Alice",
        decision="accept",
        predicted_name="Bob",  # forced wrong-name
        enrolled=True,
    )
    baseline = face_identification_pr(good, missed_gt=0, unmatched_detections=0)
    broken = face_identification_pr(good + [wrong], missed_gt=0, unmatched_detections=0)
    assert baseline.precision == 1.0
    assert baseline.recall == 1.0
    assert broken.precision < baseline.precision
    assert broken.recall < baseline.recall
    assert broken.false_positives == 1
    assert broken.false_negatives == 1


def test_face_id_forced_recall_miss_reject_enrolled():
    """TEST-15: reject of an enrolled identity is FN — recall goes red."""
    decisions = [
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
        _dec(media_id=2, true_name="Alice", decision="reject", predicted_name=None, enrolled=True),
    ]
    result = face_identification_pr(decisions, missed_gt=0, unmatched_detections=0)
    assert result.true_positives == 1
    assert result.false_negatives == 1
    assert result.recall == pytest.approx(0.5)
    assert result.precision == 1.0


def test_face_id_single_face_confusion_is_fp_only():
    """Non-enrolled single-face wrong-name: FP only, no FN."""
    decisions = [
        _dec(
            media_id=1,
            true_name="Solo",
            decision="accept",
            predicted_name="Bob",
            enrolled=False,
            excluded=True,
        ),
    ]
    result = face_identification_pr(decisions, missed_gt=0, unmatched_detections=0)
    assert result.false_positives == 1
    assert result.false_negatives == 0
    assert result.precision == 0.0
    assert result.recall == 0.0  # 0/0 → 0


def test_face_id_zero_over_zero_is_zero():
    result = face_identification_pr([], missed_gt=0, unmatched_detections=0)
    assert result.precision == 0.0
    assert result.recall == 0.0


def test_face_unknown_rejection_stranger_label_goes_red():
    """TEST-15 MANDATORY: candidate labels a stranger → unknown-rejection RED."""
    clean = [
        _dec(media_id=i, true_name=None, decision="reject", predicted_name=None)
        for i in range(5)
    ]
    polluted = clean + [
        _dec(
            media_id=99,
            true_name=None,
            decision="accept",
            predicted_name="Alice",  # false-accept
            s_max=0.9,
        )
    ]
    clean_rate = face_unknown_rejection(clean).rate
    bad = face_unknown_rejection(polluted)
    assert clean_rate == 1.0
    assert bad.false_accepts == 1
    assert bad.rate < 1.0
    assert bad.rate == pytest.approx(5 / 6)


def test_face_unknown_rejection_ignores_named_probes():
    decisions = [
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
        _dec(media_id=2, true_name=None, decision="reject"),
    ]
    result = face_unknown_rejection(decisions)
    assert result.n == 1
    assert result.correct_rejects == 1


# --- clustering (single-linkage) ---


def _embs_and_labels_two_identity_clusters():
    """Two tight identity clusters far apart (cosine)."""
    embs = []
    labels = []
    # Alice near e0
    for i in range(5):
        v = np.array([1.0, 0.01 * i, 0.0])
        embs.append((v / np.linalg.norm(v)).tolist())
        labels.append("Alice")
    # Bob near e1
    for i in range(5):
        v = np.array([0.01 * i, 1.0, 0.0])
        embs.append((v / np.linalg.norm(v)).tolist())
        labels.append("Bob")
    return embs, labels


def test_clustering_forced_merge():
    """TEST-15: loose cut merges Alice+Bob → false-merge > 0, purity < 1."""
    embs, labels = _embs_and_labels_two_identity_clusters()
    tight = clustering_metrics_at_cut(embs, labels, d_cut=0.05, pair_floor=1)
    loose = clustering_metrics_at_cut(embs, labels, d_cut=0.99, pair_floor=1)
    assert tight.false_merge == 0.0 or tight.n_clusters >= 2
    assert loose.n_clusters == 1  # single cluster
    assert loose.m_co_clustered == 10 * 9 // 2
    assert loose.false_merge > 0.0
    assert loose.purity < 1.0


def test_clustering_forced_split():
    """TEST-15: tight cut splits same-identity faces → false-split > 0."""
    # Same identity but orthogonal embeddings → must split at any cut < 1.
    embs = [
        [1.0, 0.0],
        [0.0, 1.0],
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    # L2-normalize
    embs = [(np.asarray(e) / np.linalg.norm(e)).tolist() for e in embs]
    labels = ["Alice", "Alice", "Alice", "Alice"]
    result = clustering_metrics_at_cut(embs, labels, d_cut=0.1, pair_floor=1)
    assert result.false_split > 0.0
    assert result.n_clusters > 1


def test_clustering_forced_impure_cluster():
    """TEST-15: mixed-identity cluster → purity < 1."""
    # Force one cluster with two identities by using nearly identical embeddings.
    embs = [
        [1.0, 0.0],
        [0.999, 0.001],
        [0.998, 0.002],
    ]
    embs = [(np.asarray(e) / np.linalg.norm(e)).tolist() for e in embs]
    labels = ["Alice", "Bob", "Alice"]
    result = clustering_metrics_at_cut(embs, labels, d_cut=0.5, pair_floor=1)
    assert result.n_clusters == 1
    assert result.purity < 1.0


def test_clustering_guard_m_zero_all_singletons_with_pair_floors_met():
    """TEST-15 GUARD-FIRES: M==0 all-singletons with P_same,P_diff≥20 → DIRECTIONAL.

    Proves M==0 guard fires independently of pair floors.
    """
    # 10 identities × 3 faces each with orthogonal-ish unique directions → many pairs,
    # but tight cut keeps all singletons.
    embs = []
    labels = []
    rng = np.random.default_rng(7)
    for ident in range(10):
        # Distinct random unit vectors → pairwise cos ~0, d~1; tight cut → all
        # singletons. P_same = 10*C(3,2)=30, P_diff large.
        for _ in range(3):
            v = rng.normal(size=32)
            v = v / np.linalg.norm(v)
            embs.append(v.tolist())
            labels.append(f"id{ident}")
    result = clustering_metrics_at_cut(embs, labels, d_cut=0.01, pair_floor=20)
    assert result.p_same >= 20
    assert result.p_diff >= 20
    assert result.m_co_clustered == 0
    assert result.purity == 1.0  # vacuous all-singletons purity
    assert result.directional is True
    assert "m==0" in result.directional_reasons


def test_clustering_guard_under_pair_floor():
    """Under-pair (P_same < 20) case is DIRECTIONAL."""
    embs = [[1, 0], [0.99, 0.01], [0, 1], [0.01, 0.99]]
    embs = [(np.asarray(e) / np.linalg.norm(e)).tolist() for e in embs]
    labels = ["A", "A", "B", "B"]
    result = clustering_metrics_at_cut(embs, labels, d_cut=0.5, pair_floor=20)
    assert result.p_same < 20
    assert result.directional is True
    assert any(r.startswith("p_same") for r in result.directional_reasons)


def test_clustering_sweep_headline_uses_tau_op():
    embs, labels = _embs_and_labels_two_identity_clusters()
    sweep, headline = clustering_sweep(
        embs,
        labels,
        tau_grid=(0.2, 0.5, 0.9),
        tau_op=0.5,
        pair_floor=1,
    )
    assert len(sweep) == 3
    assert headline.d_cut == pytest.approx(0.5)
    assert headline.n_faces == 10


def test_face_id_detection_recall_coupling_flag_computed():
    """EVAL-16: coupling flag is computed from missed_gt / unmatched detections."""
    clean = face_identification_pr(
        [_dec(true_name="Alice", decision="accept", predicted_name="Alice")],
        missed_gt=0,
        unmatched_detections=0,
    )
    assert clean.detection_recall_coupling_flag is False
    assert clean.precision_denominator == 1
    assert clean.recall_denominator == 1
    assert clean.sampling_frame  # named frame always present

    coupled = face_identification_pr(
        [_dec(true_name="Alice", decision="accept", predicted_name="Alice")],
        missed_gt=2,
        unmatched_detections=0,
    )
    assert coupled.detection_recall_coupling_flag is True
    assert coupled.missed_gt == 2

    coupled_fp = face_identification_pr(
        [_dec(true_name="Alice", decision="accept", predicted_name="Alice")],
        missed_gt=0,
        unmatched_detections=1,
    )
    assert coupled_fp.detection_recall_coupling_flag is True


def test_face_id_coupling_kwargs_required_no_fail_open_default():
    """FIR5V11-05 / REF-27: missed_gt and unmatched_detections are required kwargs."""
    with pytest.raises(TypeError):
        face_identification_pr(  # type: ignore[call-arg]
            [_dec(true_name="Alice", decision="accept", predicted_name="Alice")]
        )


def test_face_identification_pr_reject_dict_without_media_id_keys():
    """BR-05: a reject decision as a dict omitting media_id/box_index must not KeyError.

    Those keys only label a wrong-name row; a reject legitimately omits them.
    Regression: reading them before the accept/reject branch raised KeyError on
    every named reject dict, aborting the whole pooled-metric computation (TEST-15).
    """
    from scripts.eval_harness.face_metrics import face_identification_pr

    pr = face_identification_pr(
        [{"true_name": "Alice", "decision": "reject", "enrolled": True}],
        missed_gt=0,
        unmatched_detections=0,
    )
    assert pr.false_negatives == 1  # reject of an enrolled identity → FN
    assert pr.true_positives == 0 and pr.false_positives == 0


# ---------------------------------------------------------------------------
# FIR-5 S3d — demographic Fair-SA rollup (DIRECTIONAL; multi-face exclusion)
# ---------------------------------------------------------------------------


def test_demographic_rollup_per_cohort_id_pr():
    """≥2-cohort fixture: Alice/Bob → cohort-a, Carol → cohort-b; per-cohort P/R."""
    decisions = [
        # cohort-a: Alice correct, Bob wrong-name (FP+FN)
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
        _dec(media_id=2, true_name="Bob", decision="accept", predicted_name="Alice"),
        # cohort-b: Carol correct + reject miss
        _dec(media_id=3, true_name="Carol", decision="accept", predicted_name="Carol"),
        _dec(media_id=4, true_name="Carol", decision="reject", predicted_name=None),
    ]
    roster_cohorts = {
        "Alice": "cohort-a",
        "Bob": "cohort-a",
        "Carol": "cohort-b",
    }
    rollup = demographic_rollup(decisions, roster_cohorts)

    assert rollup.directional is True
    assert rollup.section_header == DEMOGRAPHIC_SECTION_HEADER
    assert set(rollup.by_cohort) == {"cohort-a", "cohort-b"}

    a = rollup.by_cohort["cohort-a"]
    assert a.true_positives == 1
    assert a.false_positives == 1
    assert a.false_negatives == 1  # Bob enrolled wrong-name → FN
    assert a.n_named_probes == 2
    assert a.precision == pytest.approx(0.5)
    assert a.recall == pytest.approx(0.5)

    b = rollup.by_cohort["cohort-b"]
    assert b.true_positives == 1
    assert b.false_negatives == 1
    assert b.false_positives == 0
    assert b.n_named_probes == 2
    assert b.precision == 1.0
    assert b.recall == pytest.approx(0.5)


def test_demographic_rollup_multi_face_image_cohort_excluded():
    """ANTI-MIS-ATTRIBUTION (TEST-15 can-fail): multi-face image-level cohort NOT counted.

    A multi-face entry may carry GoldenEntry.demographic_cohort, but the caller must
    not put that media_id in single_subject_cohort_by_media. Faces without a roster
    cohort must not appear under the image-level cohort label.
    """
    multi_face_media = 50
    # Image-level tag would be "cohort-x" — multi-face, so NOT in fallback map.
    decisions = [
        _dec(
            media_id=multi_face_media,
            box_index=0,
            true_name="Alice",
            decision="accept",
            predicted_name="Alice",
        ),
        _dec(
            media_id=multi_face_media,
            box_index=1,
            true_name="Bob",
            decision="accept",
            predicted_name="Bob",
        ),
        # Single-subject celebs01 fallback IS counted.
        _dec(
            media_id=10,
            true_name="Solo",
            decision="accept",
            predicted_name="Solo",
        ),
    ]
    # No roster cohorts for Alice/Bob/Solo — only single-subject media 10 maps.
    single_subject = {10: "cohort-x"}
    rollup = demographic_rollup(
        decisions,
        roster_cohorts={},
        single_subject_cohort_by_media=single_subject,
    )

    # Multi-face faces must NOT be under image-level cohort-x.
    if "cohort-x" in rollup.by_cohort:
        cx = rollup.by_cohort["cohort-x"]
        assert cx.n_named_probes == 1  # Solo only
        assert cx.true_positives == 1
    else:
        pytest.fail("single-subject celebs01 fallback must populate cohort-x")

    # Alice/Bob land in unlabeled (legible), never silently under cohort-x.
    assert UNLABELED_COHORT_KEY in rollup.by_cohort
    unlabeled = rollup.by_cohort[UNLABELED_COHORT_KEY]
    assert unlabeled.n_named_probes == 2
    assert unlabeled.true_positives == 2


def test_demographic_rollup_empty_roster_cohorts_has_directional_header():
    """Empty/missing roster_cohorts: strangers-only → empty section; a NAMED probe
    with no cohort → UNLABELED; header + DIRECTIONAL always present (no KeyError/skip)."""
    # Strangers only → no named probes → empty by_cohort.
    decisions = [
        _dec(media_id=1, true_name=None, decision="reject"),
        _dec(media_id=2, true_name=None, decision="accept", predicted_name="Alice"),
    ]
    rollup = demographic_rollup(decisions, roster_cohorts={})
    assert rollup.directional is True
    assert rollup.section_header == DEMOGRAPHIC_SECTION_HEADER
    assert "no demographic n-floor" in rollup.directional_reasons
    assert rollup.by_cohort == {}

    # Empty decisions + empty roster also keeps the header (silent skip forbidden).
    empty = demographic_rollup([], {})
    assert empty.directional is True
    assert empty.section_header
    assert empty.by_cohort == {}

    # Empty roster WITH a named probe (and no single-subject fallback) must route to
    # UNLABELED — a NON-empty by_cohort — so this test actually exercises the
    # empty-roster branch (not only strangers-exclusion). A regression that dropped
    # the unlabeled fallback in _resolve_cohort would go red here (TEST-15).
    named_no_cohort = demographic_rollup(
        [_dec(media_id=3, true_name="Nobody", decision="accept", predicted_name="Nobody")],
        roster_cohorts={},
    )
    assert set(named_no_cohort.by_cohort) == {UNLABELED_COHORT_KEY}
    assert named_no_cohort.by_cohort[UNLABELED_COHORT_KEY].n_named_probes == 1
    assert named_no_cohort.section_header == DEMOGRAPHIC_SECTION_HEADER
    assert named_no_cohort.directional is True


def test_demographic_rollup_never_fabricates_zero_miss_fields():
    """FIR5RR-05: per-cohort miss fields are None (not attributed), never 0;
    coupling is inherited from the parent totals or None (unknown)."""
    decisions = [
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
        _dec(media_id=2, true_name="Bob", decision="accept", predicted_name="Bob"),
    ]
    cohorts = {"Alice": "cohort-a", "Bob": "cohort-b"}
    inherited = demographic_rollup(
        decisions, cohorts, parent_detection_coupling=True
    )
    for pr in inherited.by_cohort.values():
        assert pr.missed_gt is None  # not 0 — the cohort frame cannot know
        assert pr.unmatched_detections is None
        assert pr.detection_recall_coupling_flag is True  # inherited, not False
        assert "not attributed per cohort" in pr.sampling_frame
    # No parent frame supplied → coupling is unknown (None), never False.
    unknown = demographic_rollup(decisions, cohorts)
    for pr in unknown.by_cohort.values():
        assert pr.detection_recall_coupling_flag is None


def test_face_id_pr_none_counts_and_coupling_override_rules():
    """FIR5RR-05: None counts carry the override; real counts forbid it."""
    decisions = [
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
    ]
    pr = face_identification_pr(
        decisions,
        missed_gt=None,
        unmatched_detections=None,
        detection_coupling=True,
    )
    assert pr.missed_gt is None and pr.unmatched_detections is None
    assert pr.detection_recall_coupling_flag is True
    # With attributed counts the flag is COMPUTED — asserting it is rejected.
    with pytest.raises(ValueError, match="only valid when"):
        face_identification_pr(
            decisions,
            missed_gt=1,
            unmatched_detections=0,
            detection_coupling=False,
        )


def test_face_id_pr_partial_miss_attribution_raises_all_or_nothing():
    """FIR5CR-03: exactly one None miss count raises; defaults are None."""
    from scripts.eval_harness.face_metrics import FaceLevelIdPr

    decisions = [
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
    ]
    with pytest.raises(ValueError, match="all-or-nothing"):
        face_identification_pr(decisions, missed_gt=None, unmatched_detections=0)
    with pytest.raises(ValueError, match="all-or-nothing"):
        face_identification_pr(decisions, missed_gt=3, unmatched_detections=None)
    # Dataclass defaults are None (not-attributed), never fail-open zeros.
    bare = FaceLevelIdPr(
        true_positives=0,
        false_positives=0,
        false_negatives=0,
        n_named_probes=0,
        n_recall_eligible=0,
        wrong_names=(),
        detection_recall_coupling_flag=None,
    )
    assert bare.missed_gt is None and bare.unmatched_detections is None


def test_unknown_rejection_error_target_discloses_trial_dependence():
    """FIR5RR-13: n=43 floor kept; dependence disclosed on the error target."""
    from scripts.eval_harness.face_metrics import (
        UNKNOWN_REJECTION_ERROR_TARGET,
        UNKNOWN_REJECTION_N_FLOOR,
    )

    assert UNKNOWN_REJECTION_N_FLOOR == 43
    assert "n=43" in UNKNOWN_REJECTION_ERROR_TARGET
    assert "independent" in UNKNOWN_REJECTION_ERROR_TARGET
    assert "effective" in UNKNOWN_REJECTION_ERROR_TARGET
    result = face_unknown_rejection(
        [_dec(media_id=1, true_name=None, decision="reject")]
    )
    assert "independent" in result.error_target


def test_demographic_rollup_strangers_excluded_and_unlabeled_legible():
    """Strangers excluded; named identity with no cohort → unlabeled bucket."""
    decisions = [
        _dec(media_id=1, true_name=None, decision="reject"),
        _dec(media_id=2, true_name="UnknownPerson", decision="accept", predicted_name="UnknownPerson"),
        _dec(media_id=3, true_name="Alice", decision="accept", predicted_name="Alice"),
    ]
    rollup = demographic_rollup(
        decisions,
        roster_cohorts={"Alice": "cohort-a"},
    )
    assert "cohort-a" in rollup.by_cohort
    assert rollup.by_cohort["cohort-a"].n_named_probes == 1
    assert UNLABELED_COHORT_KEY in rollup.by_cohort
    assert rollup.by_cohort[UNLABELED_COHORT_KEY].n_named_probes == 1
    # Stranger not counted anywhere.
    total_n = sum(pr.n_named_probes for pr in rollup.by_cohort.values())
    assert total_n == 2


# --- FIR-8: optional last-field matched_faces + bounds table ---


def test_matched_faces_is_optional_last_field():
    fields = dataclasses.fields(ImageDetection)
    assert fields[-1].name == "matched_faces"
    assert fields[-1].default is None
    # Positional 3-arg construction must keep working (field added last).
    row = ImageDetection("a.jpg", 3, 2)
    assert row.matched_faces is None


@pytest.mark.parametrize(
    ("matched", "expect_ok", "fp", "fn"),
    [
        (0, True, 3, 2),   # (i) accepted; neither FP nor FN negative
        (2, True, 1, 0),   # (ii) upper bound matched == min(pred, labeled) — load-bearing for <= vs <
        (3, False, None, None),  # (iii) exceeds labeled
        (-1, False, None, None),  # (iv) below 0
        (None, True, 1, 0),  # (v) omitted → count-only legacy
    ],
)
def test_matched_faces_bounds_table(matched, expect_ok, fp, fn):
    """FIR-8 matched_faces bounds, including count-only (matched=None).

    Count-only uses exhaustive because the arithmetic is identity-agnostic
    TP=min(pred, labeled). Omission is not exhaustive.
    """
    if matched is None:
        item = ImageDetection(image="x.jpg", pred_faces=3, labeled_faces=2)
    else:
        item = ImageDetection(image="x.jpg", pred_faces=3, labeled_faces=2, matched_faces=matched)
    if not expect_ok:
        with pytest.raises(ValueError, match="matched_faces_out_of_bounds"):
            detection_pr([item], annotation_mode=AnnotationMode.EXHAUSTIVE)
        return
    result = detection_pr([item], annotation_mode=AnnotationMode.EXHAUSTIVE)
    assert result.false_positives == fp
    assert result.false_negatives == fn
    assert result.false_positives >= 0
    assert result.false_negatives >= 0

"""VLM-2A Slice 2: face metrics — detection + identification P/R, full scope edge ledger.

FIR-5 S3 §F extensions: face-level ID P/R, unknown-rejection, single-linkage clustering.
FIR-5 S3d: demographic Fair-SA per-cohort ID P/R (DIRECTIONAL; multi-face exclusion).
TEST-15: each metric has a can-fail fixture proven to go red.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from scripts.eval_harness.face_assignment import (
    FaceDecision,
    collect_matched_faces,
    gt_box_name,
    score_face_assignment,
)
from scripts.eval_harness import face_metrics as face_metrics_mod
from scripts.eval_harness.manifest import AnnotationMode, ManifestError, ScoreInvariant
from scripts.eval_harness.face_metrics import (
    DEMOGRAPHIC_SECTION_HEADER,
    POSITIONAL_EVAL_NOT_EVALUABLE,
    POSITIONAL_EVAL_SCORED,
    POSITIONAL_VACUITY_SIGNAL,
    SAMPLING_FRAME_FACE_ID,
    SAMPLING_FRAME_UNKNOWN_REJECTION,
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
    LabeledOrderResult,
    labeled_left_to_right,
    labeled_order,
    latency_summary,
    nearest_rank_percentile,
    normalized_centre_order_key,
    positional_identification,
    predicted_left_to_right,
    predicted_names_for_positional,
    sort_identity_rows_by_normalized_centre,
    wire_bbox_normalized_centre,
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
    good = [_dec(media_id=i, true_name="Alice", decision="accept", predicted_name="Alice") for i in range(4)]
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
    clean = [_dec(media_id=i, true_name=None, decision="reject", predicted_name=None) for i in range(5)]
    polluted = clean + [
        _dec(
            media_id=99,
            true_name=None,
            decision="accept",
            predicted_name="Alice",  # false-accept
            s_max=0.9,
        )
    ]
    clean_rate = face_unknown_rejection(clean, missed_stranger_gt=0).rate
    bad = face_unknown_rejection(polluted, missed_stranger_gt=0)
    assert clean_rate == 1.0
    assert bad.false_accepts == 1
    assert bad.rate < 1.0
    assert bad.rate == pytest.approx(5 / 6)


def test_face_unknown_rejection_ignores_named_probes():
    decisions = [
        _dec(media_id=1, true_name="Alice", decision="accept", predicted_name="Alice"),
        _dec(media_id=2, true_name=None, decision="reject"),
    ]
    result = face_unknown_rejection(decisions, missed_stranger_gt=0)
    assert result.n == 1
    assert result.correct_rejects == 1


def test_face_unknown_rejection_missed_stranger_gt_counts_against_rate():
    """VLM6-B-08 / EVAL-16 / AUDIT-07: missed stranger GT lowers the rate.

    Pre-fix: three matched reject-stranger decisions → rate=1.0, n=3 even when
    fifty stranger boxes were missed upstream. Post-fix: missed_stranger_gt
    enters n and the rate denominator as failures.
    """
    matched = [
        _dec(media_id=i, true_name=None, decision="reject", predicted_name=None) for i in range(3)
    ]
    # Unfixed signature rejects the kwarg → TypeError (RED). Fixed → counts.
    with_misses = face_unknown_rejection(matched, missed_stranger_gt=50)
    assert with_misses.correct_rejects == 3
    assert with_misses.false_accepts == 0
    assert getattr(with_misses, "missed_stranger_gt", 0) == 50
    assert with_misses.n == 53  # matched + missed
    assert with_misses.rate == pytest.approx(3 / 53)
    assert with_misses.rate < 1.0
    # Sampling frame names the true observation unit (AUDIT-07).
    assert "missed" in SAMPLING_FRAME_UNKNOWN_REJECTION.lower()
    assert "full_corpus_including_unpublishable" not in SAMPLING_FRAME_UNKNOWN_REJECTION
    assert with_misses.sampling_frame == SAMPLING_FRAME_UNKNOWN_REJECTION


def test_face_unknown_rejection_requires_missed_stranger_gt():
    """S3-03 / AUDIT-07: production-shaped call without attributed misses must fail.

    Pre-fix fail-open default of 0 published rate=1.0 with n=3 while 50
    strangers were unattributed. Post-fix: missing kwarg is TypeError.
    """
    matched = [
        _dec(media_id=i, true_name=None, decision="reject", predicted_name=None) for i in range(3)
    ]
    with pytest.raises(TypeError, match="missed_stranger_gt"):
        face_unknown_rejection(matched)  # type: ignore[call-arg]


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
    """EVAL-16 / VLM6-B-01 / VLM6-B-02: missed_gt folds into FN; flag is disclosure.

    Pre-fix defect: one enrolled-accept TP + missed_gt=2 yielded FN=0, recall=1.0
    and only flipped detection_recall_coupling_flag. TEST-15: this assertion goes
    red against code that ignores misses and merely sets the flag.
    """
    # One TP accept + two detector-missed named GT → FN includes both misses.
    # Assert FN/recall FIRST so unfixed code fails on the load-bearing claim
    # (VLM6-B-02), not only on the sampling-frame string rewrite.
    coupled = face_identification_pr(
        [_dec(true_name="Alice", decision="accept", predicted_name="Alice")],
        missed_gt=2,
        unmatched_detections=0,
    )
    assert coupled.true_positives == 1
    assert coupled.false_negatives == 2  # EVAL-16: missed_gt folded into FN
    assert coupled.recall == pytest.approx(1 / 3)  # TP / (TP+FN) = 1/3
    assert coupled.recall_denominator == 3  # TP + FN
    assert coupled.precision == 1.0  # no FP from misses
    assert coupled.detection_recall_coupling_flag is True  # disclosure retained
    assert coupled.missed_gt == 2

    clean = face_identification_pr(
        [_dec(true_name="Alice", decision="accept", predicted_name="Alice")],
        missed_gt=0,
        unmatched_detections=0,
    )
    assert clean.detection_recall_coupling_flag is False
    assert clean.precision_denominator == 1
    assert clean.recall_denominator == 1
    assert clean.false_negatives == 0
    assert clean.recall == 1.0
    assert clean.sampling_frame  # named frame always present
    assert "missed_gt" in SAMPLING_FRAME_FACE_ID
    assert "excluded from FN" not in SAMPLING_FRAME_FACE_ID

    coupled_fp = face_identification_pr(
        [_dec(true_name="Alice", decision="accept", predicted_name="Alice")],
        missed_gt=0,
        unmatched_detections=1,
    )
    assert coupled_fp.detection_recall_coupling_flag is True
    # Unmatched detections alone do not invent FNs (no missed named GT).
    assert coupled_fp.false_negatives == 0
    assert coupled_fp.recall == 1.0


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
    inherited = demographic_rollup(decisions, cohorts, parent_detection_coupling=True)
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
        [_dec(media_id=1, true_name=None, decision="reject")],
        missed_stranger_gt=0,
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


# ---------------------------------------------------------------------------
# VLM6-R4-08 / VLM6-RH-03 / VLM6-RH-04 — L→R order + shared latency schema
# ---------------------------------------------------------------------------


def test_labeled_left_to_right_all_anonymous_is_empty_not_none():
    """Boxes present, all strangers → established empty order ([]), not unknown."""
    boxes = [{"name": None, "x": 0.2, "y": 0.5, "w": 0.1, "h": 0.1}, {"name": "", "x": 0.8}]
    assert labeled_left_to_right(boxes) == []


def test_labeled_left_to_right_named_but_missing_x_is_none():
    """VLM6-R4-08: named boxes with no x are malformed GT → exclude (None), not []."""
    assert labeled_left_to_right([{"name": "A"}, {"name": "B"}]) is None
    assert labeled_left_to_right([{"name": "A", "x": None}, {"name": "B", "y": 0.5}]) is None


def test_labeled_left_to_right_partial_x_keeps_named_with_coords():
    """Named box missing x is dropped; named-with-x still establishes order."""
    boxes = [
        {"name": "NoX"},  # dropped
        {"name": "Right", "x": 0.8},
        {"name": "Left", "x": 0.2},
    ]
    assert labeled_left_to_right(boxes) == ["Left", "Right"]


def test_wire_bbox_normalized_centre_converts_pixel_corner():
    """VLM6-RH-03: absolute-pixel corner → normalized centre."""
    # corner (100,50) size 200x100 on 1000x500 → centre (200,100) → (0.2, 0.2)
    cx, cy = wire_bbox_normalized_centre(
        {"x": 100, "y": 50, "width": 200, "height": 100},
        image_width=1000,
        image_height=500,
    )
    assert cx == pytest.approx(0.2)
    assert cy == pytest.approx(0.2)
    assert (
        wire_bbox_normalized_centre(
            {"x": 0, "y": 0, "width": 10, "height": 10},
            image_width=None,
            image_height=100,
        )
        is None
    )


def test_wire_bbox_normalized_centre_rejects_degenerate_box_size():
    """S3-07: w<=0 / h<=0 is unpositionable None (not a fabricated centre)."""
    assert (
        wire_bbox_normalized_centre(
            {"x": 0, "y": 0, "width": 0, "height": 10},
            image_width=200,
            image_height=100,
        )
        is None
    )
    assert (
        wire_bbox_normalized_centre(
            {"x": 100, "y": 0, "width": -40, "height": 10},
            image_width=200,
            image_height=100,
        )
        is None
    )
    assert (
        wire_bbox_normalized_centre(
            {"x": 0, "y": 0, "width": 10, "height": 0},
            image_width=200,
            image_height=100,
        )
        is None
    )


def test_predicted_left_to_right_matches_centre_not_corner_order():
    """Corner-x and centre-x disagree: wide-left vs narrow-right → centre order wins."""
    # Image 400px wide.
    # Wide face: corner x=100, w=200 → centre 200 → norm 0.5
    # Narrow face: corner x=150, w=50 → centre 175 → norm 0.4375  (LEFT of wide)
    # Corner-x sort would put Wide first (100 < 150); centre sort puts Narrow first.
    identities = [
        {
            "name": "Wide",
            "bbox": {"x": 100, "y": 0, "width": 200, "height": 100},
            "unpositioned": False,
        },
        {
            "name": "Narrow",
            "bbox": {"x": 150, "y": 0, "width": 50, "height": 100},
            "unpositioned": False,
        },
    ]
    assert predicted_left_to_right(identities, image_width=400, image_height=200) == [
        "Narrow",
        "Wide",
    ]
    # RV3-04 / TEST-15: alias is object identity — no behavioural fallback.
    # A re-clone that agrees only on Wide/Narrow must not pass.
    assert predicted_names_for_positional is predicted_left_to_right
    assert predicted_names_for_positional(identities, image_width=400, image_height=200) == [
        "Narrow",
        "Wide",
    ]
    # Without image size both fall to unpositioned → alpha: "Narrow" < "Wide".
    # Use names that reverse under alpha to prove the unpositioned path.
    # Drive the ALIAS (not only predicted_left_to_right) through Zebra/Aardvark.
    swapped_names = [
        {
            "name": "Zebra",
            "bbox": {"x": 100, "y": 0, "width": 200, "height": 100},
        },
        {
            "name": "Aardvark",
            "bbox": {"x": 150, "y": 0, "width": 50, "height": 100},
        },
    ]
    assert predicted_names_for_positional(swapped_names, image_width=400, image_height=200) == [
        "Aardvark",  # centre-left
        "Zebra",
    ]
    assert predicted_names_for_positional(swapped_names, image_width=None, image_height=None) == [
        "Aardvark",  # alpha fallback among unpositioned
        "Zebra",
    ]


def test_centre_x_tie_both_apis_share_one_order_key():
    """S3-01 / rg-005: identical centre-x, different centre-y → one shared order.

    Pre-fix: predicted_left_to_right sorted (cx, name) → [Alice, Bob] while
    sort_identity_rows_by_normalized_centre sorted (cx, cy, name) → [Bob, Alice].
    Post-fix: both use normalized_centre_order_key → same L→R sequence.
    RV3-04: drive the alias itself through the centre-y tie fixture.
    """
    rows = [
        {"name": "Alice", "bbox": {"x": 90, "y": 200, "width": 20, "height": 20}},  # cx=100 cy=210
        {"name": "Bob", "bbox": {"x": 90, "y": 10, "width": 20, "height": 20}},  # cx=100 cy=20
    ]
    predicted = predicted_names_for_positional(rows, image_width=200, image_height=400)
    sorted_rows = sort_identity_rows_by_normalized_centre(
        rows, image_width=200, image_height=400
    )
    row_names = [r["name"] for r in sorted_rows]
    assert predicted == row_names
    assert predicted == ["Bob", "Alice"]  # lower centre-y first
    # Shared pure key is the single definition (no third fork).
    assert normalized_centre_order_key(0.5, 0.05, "Bob") < normalized_centre_order_key(
        0.5, 0.525, "Alice"
    )


def test_labeled_left_to_right_tie_stable_across_input_order():
    """S3-02: exact-x ties use secondary keys; input array order must not decide.

    Pre-fix: stable sort on x alone → input order wins on pure ties.
    Post-fix: (x, y, name) matches predicted path → same sequence either way.
    HARM-07: never invent y=0.0 for a missing secondary coordinate.
    """
    order_a = [{"name": "Bob", "x": 0.5, "y": 0.1}, {"name": "Alice", "x": 0.5, "y": 0.1}]
    order_b = [{"name": "Alice", "x": 0.5, "y": 0.1}, {"name": "Bob", "x": 0.5, "y": 0.1}]
    assert labeled_left_to_right(order_a) == labeled_left_to_right(order_b)
    assert labeled_left_to_right(order_a) == ["Alice", "Bob"]  # name tie-break
    # Different y at same x must NOT collapse via invented 0.0.
    y_order = [
        {"name": "High", "x": 0.5, "y": 0.9},
        {"name": "Low", "x": 0.5, "y": 0.1},
    ]
    assert labeled_left_to_right(y_order) == ["Low", "High"]
    assert labeled_order(y_order).order_degraded is False


def test_labeled_order_per_box_missing_y_preserves_real_y(  # VLM6-R2-G-01
):
    """Per-box fallback: one missing y must not discard every other box's y.

    Reviewer repro: A(0.5,0.9), B(0.5,0.1), C(0.2, y=None).
    Whole-image (x,name) fallback yields C,A,B (A before B by name).
    Per-box: C by x alone, then B,A by real y → C,B,A. order_degraded=True.
    TEST-15: pre-fix whole-image path must go red on this fixture.
    """
    boxes = [
        {"name": "A", "x": 0.5, "y": 0.9, "w": 0.1, "h": 0.1},
        {"name": "B", "x": 0.5, "y": 0.1, "w": 0.1, "h": 0.1},
        {"name": "C", "x": 0.2, "w": 0.1, "h": 0.1},  # no y
    ]
    result = labeled_order(boxes)
    assert result.names == ["C", "B", "A"]
    assert result.order_degraded is True
    assert result.y_missing_count == 1
    # Convenience wrapper agrees.
    assert labeled_left_to_right(boxes) == ["C", "B", "A"]


def test_labeled_order_identical_x_no_y_discloses_degraded_not_spatial(  # VLM6-R2-G-01
):
    """Identical x, no y: order is unknown spatially — disclose degraded.

    Do not treat alphabetical name order as a spatial claim (HARM-07 / AUDIT-07).
    Deterministic stability across input order is required; invented L→R is not.
    """
    bare_a = [{"name": "Bob", "x": 0.5}, {"name": "Alice", "x": 0.5}]
    bare_b = [{"name": "Alice", "x": 0.5}, {"name": "Bob", "x": 0.5}]
    ra, rb = labeled_order(bare_a), labeled_order(bare_b)
    assert ra.names == rb.names  # deterministic, input-order independent
    assert ra.order_degraded is True
    assert rb.order_degraded is True
    assert ra.y_missing_count == 2
    assert rb.y_missing_count == 2


def test_labeled_order_identical_centre_x_distinct_y():  # VLM6-R2-G-01
    """Same centre-x, distinct y → y decides; not degraded."""
    boxes = [
        {"name": "A", "x": 0.5, "y": 0.9, "w": 0.1, "h": 0.1},
        {"name": "B", "x": 0.5, "y": 0.1, "w": 0.1, "h": 0.1},
    ]
    result = labeled_order(boxes)
    assert result.names == ["B", "A"]
    assert result.order_degraded is False
    assert result.y_missing_count == 0


def test_labeled_order_blank_non_numeric_y_is_missing():  # RA-04 source / wF1
    """Blank / whitespace / non-numeric y must coerce to missing, not raise.

    Called *directly* (not via report._normalize_face_boxes_for_order) so non-report
    callers share the same fail-closed missing-y branch (order_degraded=True).
    TEST-15: pre-fix float(y) raises ValueError on these fixtures.
    """
    for y in ("", "  ", "abc"):
        result = labeled_order([{"name": "A", "x": 0.5, "y": y}])
        assert isinstance(result, LabeledOrderResult), repr(y)
        assert result.names == ["A"], repr(y)
        assert result.order_degraded is True, repr(y)
        assert result.y_missing_count == 1, repr(y)
    # Numeric string still parses (not a third state).
    ok = labeled_order([{"name": "A", "x": 0.5, "y": "0.3"}])
    assert ok.names == ["A"]
    assert ok.order_degraded is False
    assert ok.y_missing_count == 0


def test_namedness_predicate_shared_across_sites():  # VLM6-R2-A-01
    """One namedness predicate: strip; empty/whitespace → anonymous.

    Pre-fix: gt_box_name stripped but L→R gated on ``name is None or == ''``
    only — whitespace-only counted as named; padded names kept unstripped.
    Cross-site: association / labeled L→R / predicted L→R / identification_pr
    must agree. TEST-15: self-certifying gt_box_name-only green is not enough.
    """
    ws = "   "
    padded = " Alice "
    # Predicate itself.
    assert gt_box_name({"name": ws}) is None
    assert gt_box_name({"name": padded}) == "Alice"
    assert gt_box_name({"name": ""}) is None
    assert gt_box_name({"name": None}) is None

    # Labeled L→R: whitespace-only skipped; padded stripped.
    assert labeled_left_to_right(
        [{"name": ws, "x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1}]
    ) == []
    boxes = [
        {"name": "  ", "x": 0.3, "y": 0.5, "w": 0.1, "h": 0.1},
        {"name": "Bob", "x": 0.7, "y": 0.5, "w": 0.1, "h": 0.1},
    ]
    assert labeled_left_to_right(boxes) == ["Bob"]
    assert [gt_box_name(b) for b in boxes] == [None, "Bob"]

    # identification_pr: model naming Bob only is a clean TP (no FN on '  ').
    pr = identification_pr(
        [ImageIdentities(image="x.jpg", predicted=["Bob"], labeled=labeled_left_to_right(boxes))]
    )
    assert (pr.true_positives, pr.false_positives, pr.false_negatives) == (1, 0, 0)
    assert pr.wrong_names == []

    # Padded GT name strips so model "Alice" is TP, not wrong-name.
    boxes3 = [{"name": padded, "x": 0.5, "y": 0.5, "w": 0.1, "h": 0.1}]
    assert labeled_left_to_right(boxes3) == ["Alice"]
    pr3 = identification_pr(
        [
            ImageIdentities(
                image="y.jpg",
                predicted=["Alice"],
                labeled=labeled_left_to_right(boxes3),
            )
        ]
    )
    assert (pr3.true_positives, pr3.false_positives, pr3.false_negatives) == (1, 0, 0)
    assert pr3.wrong_names == []

    # Predicted L→R: same predicate (whitespace skipped; padded stripped).
    assert predicted_left_to_right(
        [
            {"name": "  ", "bbox": {"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1}},
            {"name": "Bob", "bbox": {"x": 0.8, "y": 0.2, "w": 0.1, "h": 0.1}},
        ],
        image_width=100,
        image_height=100,
    ) == ["Bob"]
    assert predicted_left_to_right(
        [{"name": padded, "bbox": {"x": 10, "y": 10, "width": 20, "height": 20}}],
        image_width=100,
        image_height=100,
    ) == ["Alice"]

    # Association / collect_matched_faces: whitespace-only is stranger miss.
    run_items = [
        {
            "media_id": 1,
            "path": "a.jpg",
            "image_size": [100, 100],
            "faces": [],
        }
    ]
    gt = {
        1: [
            {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": ""},
            {"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1, "name": None},
            {"x": 0.3, "y": 0.3, "w": 0.1, "h": 0.1, "name": "   "},
            {"x": 0.4, "y": 0.4, "w": 0.1, "h": 0.1, "name": " Alice "},
        ]
    }
    _matched, _assoc, false_det, missed_named, missed_stranger = collect_matched_faces(
        run_items, gt
    )
    assert false_det == 0
    assert missed_named == 1  # only stripped "Alice"
    assert missed_stranger == 3  # "", None, whitespace


def test_face_metrics_namedness_sites_share_one_predicate(monkeypatch):
    """RA-02 / TEST-15: every face_metrics name decision routes through one predicate.

    Pre-fix (cx1 residual): ``sort_identity_rows_by_normalized_centre`` used
    ``str(row.get("name") or "")`` while L→R paths used ``gt_box_name`` — a
    reintroduced inline check never appears in the spy and fails this test.
    Not an enumeration of call sites (those rot); a divergent site is one that
    does not call the module predicate.
    """
    assert hasattr(face_metrics_mod, "named_box_name"), (
        "face_metrics must expose named_box_name as the single namedness predicate"
    )
    calls: list[object] = []
    real = face_metrics_mod.named_box_name

    def spy(box: object) -> str | None:
        calls.append(box)
        return real(box)

    monkeypatch.setattr(face_metrics_mod, "named_box_name", spy)

    rows = [
        {"name": "  ", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"name": " Bob ", "bbox": {"x": 50, "y": 0, "width": 10, "height": 10}},
    ]
    labeled_boxes = [
        {"name": "  ", "x": 0.2, "y": 0.5},
        {"name": " Alice ", "x": 0.8, "y": 0.5},
    ]

    n0 = len(calls)
    sort_identity_rows_by_normalized_centre(rows, image_width=100, image_height=100)
    sort_calls = len(calls) - n0
    assert sort_calls >= 2, (
        "sort_identity_rows_by_normalized_centre must route each row through "
        f"named_box_name (got {sort_calls} calls)"
    )

    n1 = len(calls)
    assert predicted_left_to_right(rows, image_width=100, image_height=100) == ["Bob"]
    pred_calls = len(calls) - n1
    assert pred_calls >= 2

    n2 = len(calls)
    assert labeled_left_to_right(labeled_boxes) == ["Alice"]
    assert labeled_order(labeled_boxes).names == ["Alice"]
    labeled_calls = len(calls) - n2
    assert labeled_calls >= 2


def test_sort_identity_rows_name_tiebreak_uses_stripped_namedness():
    """RA-02: same centre → tertiary name key must use the namedness predicate.

    Pre-fix: raw ``" Bob "`` sorts before ``"Alice"`` (leading space). After
    strip the order is Alice, Bob — same as predicted L→R name sequence.
    Rows are still all kept (storage multiset); only the sort key is normalized.
    """
    rows = [
        {"name": " Bob ", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"name": "Alice", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
    ]
    ordered = sort_identity_rows_by_normalized_centre(
        rows, image_width=100, image_height=100
    )
    # Spatial keys identical → name tie-break via stripped namedness.
    assert [r["name"] for r in ordered] == ["Alice", " Bob "]
    predicted = predicted_left_to_right(rows, image_width=100, image_height=100)
    assert predicted == ["Alice", "Bob"]
    # Named subsequence order of sort rows (via predicate) matches predicted.
    assert hasattr(face_metrics_mod, "named_box_name"), "named_box_name missing"
    pred = face_metrics_mod.named_box_name
    assert [pred(r) for r in ordered if pred(r) is not None] == predicted


def test_named_box_name_rejects_invisible_format_chars():
    """RA-03: format controls (Cf) are not names; strip alone is insufficient.

    Explicit rule (face_metrics.named_box_name): remove Unicode category Cf
    (ZWSP/ZWJ/ZWNJ/BOM/soft-hyphen/…), then str.strip() of Unicode whitespace;
    empty → anonymous (None). Visible characters remain (``"A\\u200bB"`` → ``"AB"``).
    Mechanism only — corpus incidence not measured (AUDIT-07).
    """
    assert hasattr(face_metrics_mod, "named_box_name"), "named_box_name missing"
    named_box_name = face_metrics_mod.named_box_name
    for invisible in ("\u200b", "\u200d", "\u200c", "\ufeff", "\u00ad"):
        assert named_box_name({"name": invisible}) is None, repr(invisible)
        assert labeled_left_to_right(
            [{"name": invisible, "x": 0.5, "y": 0.5}]
        ) == []
        assert predicted_left_to_right(
            [{"name": invisible, "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}}],
            image_width=100,
            image_height=100,
        ) == []
    # NBSP is whitespace — still anonymous after strip.
    assert named_box_name({"name": "\u00a0"}) is None
    assert named_box_name({"name": "\u00a0Alice\u00a0"}) == "Alice"
    # Format char inside a real name is removed, not a distinct identity.
    assert named_box_name({"name": "A\u200bB"}) == "AB"
    assert named_box_name({"name": " Alice "}) == "Alice"
    assert named_box_name({"name": "   "}) is None
    assert named_box_name({"name": None}) is None
    assert named_box_name({"name": ""}) is None


def test_gt_box_name_empty_string_is_anonymous():
    """HARM-06 / rg-005: empty-string name is anonymous, not named.

    Strengthened cross-site coverage lives in
    test_namedness_predicate_shared_across_sites (VLM6-R2-A-01). Kept as a
    thin direct unit for gt_box_name + stranger-miss routing.
    """
    assert gt_box_name({"name": None, "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}) is None
    assert gt_box_name({"name": "", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}) is None
    assert gt_box_name({"name": "   ", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}) is None
    assert gt_box_name({"name": "Alice", "x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}) == "Alice"
    # Empty-name unmatched GT counts as stranger miss, not named missed_gt.
    run_items = [
        {
            "media_id": 1,
            "path": "a.jpg",
            "image_size": [100, 100],
            "faces": [],
        }
    ]
    gt = {
        1: [
            {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": ""},
            {"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1, "name": None},
        ]
    }
    _matched, _assoc, false_det, missed_named, missed_stranger = collect_matched_faces(
        run_items, gt
    )
    assert false_det == 0
    assert missed_named == 0
    assert missed_stranger == 2


def test_missed_gt_named_only_stranger_not_id_fn():
    """S3-04 / EVAL-16 / EVAL-19: unmatched stranger GT is not identification FN.

    Zero detections, GT = named Alice + anonymous stranger:
    - assignment.missed_gt == 1 (Alice only)
    - assignment.missed_stranger_gt == 1
    - face_identification_pr FN folds named misses only
    """
    run_items = [
        {
            "media_id": 1,
            "path": "a.jpg",
            "image_size": [100, 100],
            "faces": [],
        }
    ]
    gt = {
        1: [
            {"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2, "name": "Alice"},
            {"x": 0.2, "y": 0.2, "w": 0.1, "h": 0.1, "name": None},
        ]
    }
    matched, associations, false_det, missed_named, missed_stranger = collect_matched_faces(
        run_items, gt
    )
    assert matched == []
    assert false_det == 0
    assert missed_named == 1
    assert missed_stranger == 1
    assert len(associations[1].unmatched_gt) == 2

    assignment = score_face_assignment(run_items, gt, k_folds=2)
    assert assignment.missed_gt == 1
    assert assignment.missed_stranger_gt == 1

    pr_named = face_identification_pr(
        assignment.decisions,
        missed_gt=assignment.missed_gt,
        unmatched_detections=assignment.false_detections,
    )
    assert pr_named.false_negatives == 1  # Alice only
    assert pr_named.missed_gt == 1

    # Contrasting wrong unit: feeding both misses would inflate FN (pre-fix).
    pr_inflated = face_identification_pr(
        [],
        missed_gt=2,  # Alice + stranger — wrong observation unit
        unmatched_detections=0,
    )
    assert pr_inflated.false_negatives == 2


def test_predicted_left_to_right_dedupes_leftmost_like_labeled():
    """VLM6-R4-08: predicted duplicate names keep leftmost only (mirrors labeled)."""
    identities = [
        {"name": "A", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
        {"name": "A", "bbox": {"x": 50, "y": 0, "width": 10, "height": 10}},
        {"name": "B", "bbox": {"x": 100, "y": 0, "width": 10, "height": 10}},
    ]
    assert predicted_left_to_right(identities, image_width=200, image_height=100) == ["A", "B"]


def test_positional_identification_uses_centre_order_via_predicted_rows():
    """VLM6-B-03: positional scoring via predicted_rows uses centre-x, not corner-x.

    Wide box corner-x=100 w=200 vs narrow corner-x=150 w=50 on 400px image:
    corner order [Wide, Narrow], centre order [Narrow, Wide]. Labeled L→R is
    centre-based [Narrow, Wide] → exact_order only when predicted uses centre.
    """
    rows = [
        {"name": "Wide", "bbox": {"x": 100, "y": 0, "width": 200, "height": 100}},
        {"name": "Narrow", "bbox": {"x": 150, "y": 0, "width": 50, "height": 100}},
    ]
    # Raw identity_names order (corner / storage order) would be [Wide, Narrow].
    corner_order_names = ["Wide", "Narrow"]
    labelled = ["Narrow", "Wide"]  # centre L→R as labeled_left_to_right would yield
    # Without predicted_rows: only leftmost dedupe of the raw list (still wrong order).
    bare = positional_identification(
        [
            ImageIdentities(
                image="a.jpg",
                predicted=corner_order_names,
                labeled=labelled,
                labeled_order_known=True,
            )
        ]
    )
    assert bare.position_accuracy == 0.0
    assert bare.exact_order_images == 0
    # With predicted_rows + image size: centre order wins → exact match.
    # Unfixed code rejects predicted_rows kwarg → TypeError (RED). Fixed → exact.
    fixed = positional_identification(
        [
            ImageIdentities(
                image="a.jpg",
                predicted=corner_order_names,  # ignored when rows present
                labeled=labelled,
                labeled_order_known=True,
                predicted_rows=rows,
                image_width=400,
                image_height=200,
            )
        ]
    )
    assert fixed.exact_order_images == 1
    assert fixed.position_accuracy == 1.0
    assert getattr(fixed, "evaluable", None) is True
    assert getattr(fixed, "status", POSITIONAL_EVAL_SCORED) == POSITIONAL_EVAL_SCORED


def test_positional_identification_dedupes_duplicate_predicted_names():
    """VLM6-B-03: [Alice, Alice, Bob] vs labeled [Alice, Bob] → exact after dedup.

    Pre-fix via raw identity_names: 1/3 position hits. Post-fix: leftmost-wins
    dedup matches labeled cardinality → exact_order 1.0.
    """
    result = positional_identification(
        [
            ImageIdentities(
                image="a.jpg",
                predicted=["Alice", "Alice", "Bob"],
                labeled=["Alice", "Bob"],
                labeled_order_known=True,
            )
        ]
    )
    assert result.compared_images == 1
    assert result.exact_order_images == 1
    assert result.position_accuracy == 1.0
    assert result.position_hits == 2
    assert result.position_total == 2


def test_positional_vacuity_signal_on_real_golden_corpus():
    """VLM6-B-10 / EVAL-23 / AUDIT-07: golden.json has face_boxes on 0/37 → π=0.

    Positional identification must emit an explicit not_evaluable vacuity signal
    the verdict layer can consume — never a silent accuracy=None pass.
    """
    import json
    from pathlib import Path

    golden_path = Path(__file__).parent / "seed" / "golden.json"
    manifest = json.loads(golden_path.read_text())
    entries = manifest["entries"]
    assert len(entries) == 37
    assert sum(1 for e in entries if e.get("face_boxes")) == 0

    items: list[ImageIdentities] = []
    for entry in entries:
        ordered = labeled_left_to_right(entry.get("face_boxes") or [])
        items.append(
            ImageIdentities(
                image=str(entry["path"]),
                predicted=list(entry.get("present_identities") or []),
                labeled=list(ordered) if ordered is not None else [],
                labeled_order_known=ordered is not None,
            )
        )
    result = positional_identification(items)
    assert result.compared_images == 0
    assert result.position_accuracy is None
    assert getattr(result, "evaluable", None) is False
    assert getattr(result, "status", None) == POSITIONAL_EVAL_NOT_EVALUABLE
    assert getattr(result, "vacuity_signal", None) == POSITIONAL_VACUITY_SIGNAL
    assert "π=0" in (getattr(result, "vacuity_signal", None) or "")
    assert len(result.excluded_images) == 37


def test_sort_identity_rows_preserves_duplicates_reorders_by_centre():
    """face_pass storage keeps multiset; only sort key is corrected."""
    rows = [
        {"name": "Wide", "bbox": {"x": 100, "y": 0, "width": 200, "height": 100}},
        {"name": "Narrow", "bbox": {"x": 150, "y": 0, "width": 50, "height": 100}},
        {"name": "Wide", "bbox": {"x": 300, "y": 0, "width": 20, "height": 100}},
    ]
    ordered = sort_identity_rows_by_normalized_centre(rows, image_width=400, image_height=200)
    assert [r["name"] for r in ordered] == ["Narrow", "Wide", "Wide"]


def test_latency_summary_schema_and_throughput():
    """VLM6-RH-04: one nested schema with n/mean/min/p50/p95/p99/max + throughput."""
    assert latency_summary([]) is None
    block = latency_summary([1.0, 2.0, 10.0], unit="s", wall_clock_s=30.0, throughput_n=3)
    assert block is not None
    assert block["unit"] == "s"
    assert block["n"] == 3
    assert block["mean"] == pytest.approx(4.333, abs=0.001)
    assert block["min"] == 1.0
    assert block["p50"] == 2.0
    assert block["p95"] == 10.0
    assert block["p99"] == 10.0
    assert block["max"] == 10.0
    assert block["wall_clock_s"] == 30.0
    assert block["images_per_min"] == 6.0  # 3 images / 0.5 min
    assert nearest_rank_percentile([1.0, 2.0, 10.0], 0.50) == 2.0
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 0.5)


# --- FIR-8: optional last-field matched_faces + bounds table ---


def test_matched_faces_is_optional_last_field():
    fields = dataclasses.fields(ImageDetection)
    assert fields[-1].name == "matched_faces"
    assert fields[-1].default is None
    # Positional 3-arg construction must keep working (field added last).
    row = ImageDetection("a.jpg", 3, 2)
    assert row.matched_faces is None


# VLM6-S7-02: this test was defined twice; the shadowed copy's extra
# `assert result.recall is None` was dropped, not merged — recall is None only
# when tp+fn == 0, which no row here produces (labeled_faces=2 throughout).
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

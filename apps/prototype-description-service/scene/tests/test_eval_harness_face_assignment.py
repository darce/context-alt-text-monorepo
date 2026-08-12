"""FIR-5 S3: face assignment — §A0/§C association, §D LOO, §E k-fold, §F similar_people.

TEST-15: fixtures are can-fail (each assertion proven to go red on a broken impl).
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from scripts.eval_harness.face_assignment import (
    IOU_MATCH_THRESHOLD,
    TAU_GRID,
    AssociationResult,
    MatchedFace,
    OpenSetCounts,
    assign_open_set_kfold,
    associate_detections,
    build_loo_gallery,
    global_fold_ranks,
    gt_box_name,
    gt_normalized_centre_to_pixel_corner,
    iou_pixel_corner,
    is_enrolled_for_probe,
    matched_named_by_identity,
    mean_prototype,
    score_face_assignment,
    score_similar_people,
    select_tau_open_set_f1,
    similar_people_hungarian,
)
from scripts.eval_harness.face_metrics import named_box_name

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(vec: list[float]) -> list[float]:
    a = np.asarray(vec, dtype=np.float64)
    n = float(np.linalg.norm(a))
    assert n > 0
    return (a / n).tolist()


def _face(
    bbox_px: list[float],
    embedding: list[float],
    *,
    det_score: float = 0.9,
) -> dict:
    # Minimal §B face; landmarks unused by score-time assignment.
    lm = [[0.0, 0.0]] * 5
    return {
        "bbox_px": bbox_px,
        "landmarks_px": lm,
        "embedding": _unit(embedding),
        "det_score": det_score,
    }


def _gt(x: float, y: float | None, w: float, h: float, name: str | None) -> dict:
    return {"x": x, "y": y, "w": w, "h": h, "name": name, "source": "iptc"}


def _matched(
    media_id: int,
    box_index: int,
    emb: list[float],
    true_name: str | None,
    *,
    det_index: int = 0,
    path: str = "x.jpg",
) -> MatchedFace:
    return MatchedFace(
        media_id=media_id,
        path=path,
        box_index=box_index,
        det_index=det_index,
        embedding=tuple(_unit(emb)),
        true_name=true_name,
    )


# ---------------------------------------------------------------------------
# §A0 / §C coordinate conversion + IoU
# ---------------------------------------------------------------------------


def test_gt_normalized_centre_to_pixel_corner():
    # Centre (0.5, 0.5), size 0.2×0.4 on 100×200 image → top-left (40, 60), size 20×80.
    px = gt_normalized_centre_to_pixel_corner(cx=0.5, cy=0.5, w=0.2, h=0.4, image_size=[100, 200])
    assert px == pytest.approx([40.0, 60.0, 20.0, 80.0])


def test_detector_bbox_not_shifted_through_gt_converter():
    """Detector boxes are already pixel-corner — association must not centre-shift them."""
    # GT covers [0,0,50,50] in pixels on 100×100 → centre (0.25, 0.25), size (0.5, 0.5).
    gt = [_gt(0.25, 0.25, 0.5, 0.5, "Alice")]
    # Detector already pixel-corner matching GT exactly.
    det = [[0.0, 0.0, 50.0, 50.0]]
    result = associate_detections(det, gt, [100, 100])
    assert len(result.pairs) == 1
    assert result.pairs[0].iou == pytest.approx(1.0)


def test_iou_pixel_corner_identical_is_one():
    assert iou_pixel_corner([10, 20, 30, 40], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_iou_pixel_corner_disjoint_is_zero():
    assert iou_pixel_corner([0, 0, 10, 10], [20, 20, 10, 10]) == 0.0


# ---------------------------------------------------------------------------
# §C matcher: single-GT highest-IoU + Hungarian ≥2
# ---------------------------------------------------------------------------


def test_associate_single_gt_highest_iou():
    gt = [_gt(0.5, 0.5, 0.2, 0.2, "Alice")]  # px centre 50,50 size 20 → [40,40,20,20]
    dets = [
        [0.0, 0.0, 10.0, 10.0],  # low IoU
        [38.0, 38.0, 24.0, 24.0],  # high IoU
        [80.0, 80.0, 10.0, 10.0],  # low
    ]
    result = associate_detections(dets, gt, [100, 100])
    assert len(result.pairs) == 1
    assert result.pairs[0].det_index == 1
    assert result.pairs[0].name == "Alice"
    assert result.pairs[0].iou >= IOU_MATCH_THRESHOLD
    assert set(result.unmatched_detections) == {0, 2}
    assert result.unmatched_gt == ()


def test_associate_hungarian_three_faces():
    """3 GT × 3 det: Hungarian one-to-one, not greedy double-assign."""
    # Non-overlapping GT boxes in three corners of a 300×300 image.
    gts = [
        _gt(50 / 300, 50 / 300, 60 / 300, 60 / 300, "A"),  # ~[20,20,60,60]
        _gt(150 / 300, 50 / 300, 60 / 300, 60 / 300, "B"),  # ~[120,20,60,60]
        _gt(250 / 300, 50 / 300, 60 / 300, 60 / 300, "C"),  # ~[220,20,60,60]
    ]
    # Detections slightly offset but clearly matching A,C,B order (permuted).
    dets = [
        [18.0, 18.0, 64.0, 64.0],  # → A
        [218.0, 18.0, 64.0, 64.0],  # → C
        [118.0, 18.0, 64.0, 64.0],  # → B
    ]
    result = associate_detections(dets, gts, [300, 300])
    assert len(result.pairs) == 3
    by_det = {p.det_index: p.name for p in result.pairs}
    assert by_det == {0: "A", 1: "C", 2: "B"}
    # No double-assigned GT.
    assert len({p.gt_index for p in result.pairs}) == 3
    assert result.unmatched_detections == ()
    assert result.unmatched_gt == ()


def test_associate_below_threshold_rejected():
    gt = [_gt(0.5, 0.5, 0.2, 0.2, "Alice")]
    # Far away detection.
    dets = [[0.0, 0.0, 5.0, 5.0]]
    result = associate_detections(dets, gt, [100, 100])
    assert result.pairs == ()
    assert result.unmatched_detections == (0,)
    assert result.unmatched_gt == (0,)


def test_associate_stranger_name_none():
    gt = [_gt(0.5, 0.5, 0.4, 0.4, None)]
    dets = [[30.0, 30.0, 40.0, 40.0]]
    result = associate_detections(dets, gt, [100, 100])
    assert len(result.pairs) == 1
    assert result.pairs[0].name is None


# ---------------------------------------------------------------------------
# Null-y GT hardening (wF4 residual 3 / VLM6 Wave G wG2)
# ---------------------------------------------------------------------------
# FaceBox.y is optional (order_degraded / labeled_y_missing_images). Association
# needs a full centre for IoU — must not float(None), must not invent y=0 or
# match on x alone, and must stamp incompleteness so consumers can tell a
# complete association from a degraded one (rg-015 / DIAG-03 / S2-07).


def test_associate_null_y_with_detections_does_not_crash():
    """DBG-10 / TEST-15: null-y named box + n_det>0 must not TypeError."""
    gt = [_gt(0.5, None, 0.2, 0.2, "Alice")]
    dets = [[40.0, 40.0, 20.0, 20.0]]
    result = associate_detections(dets, gt, [100, 100])
    # No crash — result is stamped incomplete (not a complete empty match).
    assert result.geometry_incomplete_gt == (0,)
    assert result.association_complete is False
    assert result.pairs == ()
    assert result.unmatched_detections == (0,)
    # Incomplete GT is not a detector FN (unmatched_gt).
    assert result.unmatched_gt == ()


def test_associate_mixed_y_excludes_incomplete_keeps_complete_match():
    """Complete sibling still associates; null-y excluded + stamped."""
    # Bob complete centre (0.25,0.25) size 0.4 → px [5,5,40,40] on 100×100.
    # Alice null-y at x=0.75 — cannot enter IoU matrix.
    gts = [
        _gt(0.25, 0.25, 0.4, 0.4, "Bob"),
        _gt(0.75, None, 0.4, 0.4, "Alice"),
    ]
    dets = [[5.0, 5.0, 40.0, 40.0]]  # matches Bob
    result = associate_detections(dets, gts, [100, 100])
    assert len(result.pairs) == 1
    assert result.pairs[0].name == "Bob"
    assert result.pairs[0].gt_index == 0
    assert result.geometry_incomplete_gt == (1,)
    assert result.association_complete is False
    assert result.unmatched_gt == ()
    assert result.unmatched_detections == ()


def test_associate_null_y_not_x_only_match():
    """Option-3 trap: must not silently match on x alone when y is missing."""
    # If y were invented as 0.5, this det would match Alice with high IoU.
    # With y=None the box must be excluded — never an invented pair.
    gt = [_gt(0.5, None, 0.2, 0.2, "Alice")]
    dets = [[40.0, 40.0, 20.0, 20.0]]  # would be perfect match at y=0.5
    result = associate_detections(dets, gt, [100, 100])
    assert result.pairs == ()
    assert result.geometry_incomplete_gt == (0,)


def test_associate_null_y_zero_det_stamps_incomplete_not_fn():
    """Zero-det path: incomplete GT is geometry stamp, not unmatched_gt FN."""
    gts = [
        _gt(0.25, 0.25, 0.2, 0.2, "Bob"),
        _gt(0.75, None, 0.2, 0.2, "Alice"),
    ]
    result = associate_detections([], gts, [100, 100])
    assert result.pairs == ()
    assert result.unmatched_detections == ()
    assert result.unmatched_gt == (0,)  # Bob only — complete, missed
    assert result.geometry_incomplete_gt == (1,)
    assert result.association_complete is False


def test_collect_matched_faces_null_y_with_detections_no_crash_no_fn_inflate():
    """collect_matched_faces: n_det>0 + null-y must score without crash.

    Incomplete named GT must not inflate missed_gt (detection FN).
    """
    from scripts.eval_harness.face_assignment import collect_matched_faces

    gt_complete = _gt(0.25, 0.25, 0.4, 0.4, "Bob")
    gt_incomplete = _gt(0.75, None, 0.4, 0.4, "Alice")
    run = [
        {
            "media_id": 1,
            "path": "mixed.jpg",
            "image_size": [100, 100],
            "faces": [
                _face([5.0, 5.0, 40.0, 40.0], [1.0, 0.0]),  # Bob
            ],
        }
    ]
    matched, assocs, false_det, missed_named, missed_stranger = collect_matched_faces(
        run, {1: [gt_complete, gt_incomplete]}
    )
    assert len(matched) == 1
    assert matched[0].true_name == "Bob"
    assert false_det == 0
    assert missed_named == 0  # Alice incomplete ≠ detector FN
    assert missed_stranger == 0
    assoc = assocs[1]
    assert assoc.geometry_incomplete_gt == (1,)
    assert assoc.association_complete is False


def test_score_face_assignment_propagates_geometry_incomplete_stamp():
    """AssignmentResult must surface incompleteness (not only AssociationResult)."""
    gt = [_gt(0.5, None, 0.2, 0.2, "Alice")]
    run = [
        {
            "media_id": 7,
            "path": "null-y.jpg",
            "image_size": [100, 100],
            "faces": [_face([40.0, 40.0, 20.0, 20.0], [1.0, 0.0])],
        }
    ]
    result = score_face_assignment(run, {7: gt})
    assert result.geometry_incomplete_gt == 1
    assert result.association_incomplete_media == 1
    assert result.false_detections == 1  # lone det unmatched
    assert result.missed_gt == 0  # incomplete ≠ FN
    assert result.matched == ()


def test_associate_facebox_model_null_y():
    """FaceBox pydantic model with y=None takes the same path as dict GT."""
    from scripts.eval_harness.manifest import FaceBox

    gt = [FaceBox(x=0.5, y=None, w=0.2, h=0.2, name="Alice", source="iptc")]
    dets = [[40.0, 40.0, 20.0, 20.0]]
    result = associate_detections(dets, gt, [100, 100])
    assert result.geometry_incomplete_gt == (0,)
    assert result.pairs == ()


# ---------------------------------------------------------------------------
# §D LOO gallery
# ---------------------------------------------------------------------------


def test_loo_every_matched_face_is_scored_and_enrolled_requires_two():
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [0.9, 0.1, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], "Bob"),  # single-face Bob
    ]
    by_id = matched_named_by_identity(faces)
    counts = {n: len(fs) for n, fs in by_id.items()}

    assert is_enrolled_for_probe("Alice", counts) is True
    assert is_enrolled_for_probe("Bob", counts) is False

    # Alice probe 0: prototype from the other Alice face only.
    gal0 = build_loo_gallery(faces[0], by_id)
    assert "Alice" in gal0
    assert "Bob" in gal0  # Bob still present as other-identity prototype (1 face OK for Y≠X)
    # LOO: Alice prototype should equal the other face (L2).
    other = np.asarray(faces[1].embedding)
    assert gal0["Alice"] == pytest.approx(other / np.linalg.norm(other))

    # Bob single-face: no Bob prototype when scoring Bob.
    gal_bob = build_loo_gallery(faces[2], by_id)
    assert "Bob" not in gal_bob
    assert "Alice" in gal_bob


def test_single_face_excluded_single_face_recall_no_nan():
    faces = [
        _matched(1, 0, [1, 0], "Solo"),
        _matched(2, 0, [0, 1], "Alice"),
        _matched(3, 0, [0.1, 0.9], "Alice"),
    ]
    result = assign_open_set_kfold(faces, k_folds=2, tau_grid=(0.2, 0.5, 0.9))
    solo_decisions = [d for d in result.decisions if d.true_name == "Solo"]
    assert len(solo_decisions) == 1
    assert solo_decisions[0].excluded_single_face_recall is True
    assert solo_decisions[0].enrolled is False
    # Metrics stay finite.
    for d in result.decisions:
        assert d.s_max == d.s_max  # not NaN
        assert not math.isnan(d.tau_k)


def test_mean_prototype_not_first_n():
    # Two opposite-ish vectors: mean is between them, not equal to either.
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    proto = mean_prototype([a, b])
    expected = np.array([0.5, 0.5])
    expected = expected / np.linalg.norm(expected)
    assert proto == pytest.approx(expected)
    assert not np.allclose(proto, a)
    assert not np.allclose(proto, b)


def test_mean_prototype_empty_raises():
    with pytest.raises(ValueError, match="≥1"):
        mean_prototype([])


# ---------------------------------------------------------------------------
# §E k-fold global key + pooled decisions + open-set F1
# ---------------------------------------------------------------------------


def test_global_fold_key_is_subject_disjoint():
    """CAL-07: each named identity's faces share one fold (no identity split across folds)."""
    faces: list[MatchedFace] = []
    # 5 faces each for Alice, Bob + 5 strangers.
    for i in range(5):
        faces.append(_matched(100 + i, 0, [1, 0, float(i) * 0.01], "Alice", path=f"a{i}.jpg"))
        faces.append(_matched(200 + i, 0, [0, 1, float(i) * 0.01], "Bob", path=f"b{i}.jpg"))
        faces.append(_matched(300 + i, 0, [0, 0, 1], None, path=f"s{i}.jpg"))

    folds = global_fold_ranks(faces, k_folds=5)
    # Named identities are each confined to a single fold.
    alice_folds = {fold for f, fold in zip(faces, folds, strict=True) if f.true_name == "Alice"}
    bob_folds = {fold for f, fold in zip(faces, folds, strict=True) if f.true_name == "Bob"}
    assert len(alice_folds) == 1
    assert len(bob_folds) == 1
    assert alice_folds != bob_folds  # distinct subjects land in distinct folds when K≥2
    # Strangers still spread (each stranger face is its own subject).
    stranger_folds = {fold for f, fold in zip(faces, folds, strict=True) if f.true_name is None}
    assert stranger_folds == {0, 1, 2, 3, 4}


def test_fit_phase_galleries_exclude_held_out_identities():
    """CAL-07 (FIR5RR-03): a held-out confusable identity provably SHIFTS the
    selected τ — asserted through ``assign_open_set_kfold`` itself, not a
    hand-reconstruction of the fit loop.

    Fixture: Alice = two identical faces ([1,0,0]); Bob = a spread pair with
    cos(b1,b2)=0.62 whose faces sit at cos=0.9 to Alice's prototype.

    - CORRECT fit for Alice's fold (fit = Bob only): Bob probes match their LOO
      prototype at 0.62 → F1=1 on the τ∈{0.20..0.60} plateau → τ_k = 0.40.
    - LEAKED fit (full-corpus galleries incl. held-out Alice): Bob probes
      argmax to Alice at 0.9 → FP at every grid τ → F1=0 everywhere → the
      full-grid plateau selects 0.55.

    Asserting the CONCRETE τ_k=0.40 therefore goes red if the fit phase ever
    sees full-corpus galleries (discriminability proven in-test below by
    computing the leaked selection and asserting it differs).
    """
    s = float(np.sqrt(1.0 - 0.81))  # b = [0.9, ±s] → cos(b1,b2) = 0.81 − 0.19 = 0.62
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0, 0], "Alice"),
        _matched(3, 0, [0.9, s, 0], "Bob"),
        _matched(4, 0, [0.9, -s, 0], "Bob"),
    ]
    folds = global_fold_ranks(faces, k_folds=2)
    alice_fold = next(f for m, f in zip(faces, folds, strict=True) if m.true_name == "Alice")
    bob_fold = next(f for m, f in zip(faces, folds, strict=True) if m.true_name == "Bob")
    assert alice_fold != bob_fold

    result = assign_open_set_kfold(faces, k_folds=2, tau_grid=TAU_GRID)
    # Concrete held-out selection: Alice's fold τ fit on Bob-only galleries.
    assert result.tau_k[alice_fold] == pytest.approx(0.40)
    # Alice's pooled decisions carry that same held-out τ_k.
    assert all(
        d.tau_k == pytest.approx(0.40) for d in result.decisions if d.true_name == "Alice"
    )

    # Discriminability proof (TEST-15): a fit that leaks full-corpus galleries
    # (held-out Alice enrolled) selects a DIFFERENT τ for the same probes.
    by_id_full = matched_named_by_identity(faces)
    counts_full = {n: len(fs) for n, fs in by_id_full.items()}
    bob_probes = [m for m in faces if m.true_name == "Bob"]
    leaked_tau = select_tau_open_set_f1(
        probes=bob_probes,
        by_identity=by_id_full,
        identity_counts=counts_full,
        tau_grid=TAU_GRID,
    )
    assert leaked_tau == pytest.approx(0.55)
    assert leaked_tau != result.tau_k[alice_fold]


def test_pooled_decisions_cover_all_matched_named_n():
    faces = [
        _matched(i, 0, [1.0, float(i) * 0.01], "Alice") for i in range(6)
    ] + [
        _matched(10 + i, 0, [0.0, 1.0], "Bob") for i in range(4)
    ]
    result = assign_open_set_kfold(faces, k_folds=5)
    named = [d for d in result.decisions if d.true_name is not None]
    assert len(named) == 10  # full matched-named-face n (no enroll/probe split)
    assert len(result.decisions) == len(faces)
    # Every face decided exactly once.
    keys = {(d.media_id, d.box_index, d.det_index) for d in result.decisions}
    assert len(keys) == len(faces)


def test_kfold_clamped_to_subject_count_avoids_empty_fit():
    """REF-27 / FIR5V11-03: K >> n_subjects is clamped so fit sets stay non-empty."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
        _matched(3, 0, [0, 1, 0], None),
        _matched(4, 0, [0, 1, 0.05], None),
    ]
    # Requested K=5 with 3 subjects (Alice + 2 strangers) clamps to 3.
    result = assign_open_set_kfold(faces, k_folds=5, tau_grid=(0.2, 0.5, 0.9))
    used_folds = {d.fold for d in result.decisions}
    assert len(result.tau_k) == 3
    assert used_folds <= set(range(len(result.tau_k)))
    assert len(result.decisions) == len(faces)
    assert all(d.tau_k == result.tau_k[d.fold] for d in result.decisions)
    # Joint ranking spreads Alice vs strangers across folds (not all fold 0).
    assert len(used_folds) >= 2
    # FIR5RR-04: the clamp is recorded — requested vs effective K disclosed.
    assert result.requested_k == 5
    assert result.effective_k == 3
    # All folds fit normally here → τ provenance is "fitted" (FIR5RR-07).
    assert result.tau_fit_status == "fitted"


def test_single_subject_mid_grid_fallback_flagged_unfitted():
    """FIR5RR-07: single-subject corpus falls back to mid-grid τ and says so."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Alice"),
    ]
    result = assign_open_set_kfold(faces, k_folds=5, tau_grid=(0.2, 0.5, 0.9))
    assert result.effective_k == 1
    assert result.tau_k == (0.5,)  # mid-grid
    assert result.tau_fit_status == "mid_grid_unfitted"
    # Multi-subject corpora with fit sets stay "fitted" (discrimination).
    multi = assign_open_set_kfold(
        faces + [_matched(3, 0, [0, 1, 0], "Bob"), _matched(4, 0, [0, 1, 0.05], "Bob")],
        k_folds=2,
        tau_grid=(0.2, 0.5, 0.9),
    )
    assert multi.tau_fit_status == "fitted"


def test_empty_fit_fold_fails_fast_when_unavoidable_collision():
    """REF-27: if every probe collides into one fold under effective_k>1, raise."""
    faces = [
        _matched(1, 0, [1, 0, 0], "Alice"),
        _matched(2, 0, [1, 0.05, 0], "Bob"),
    ]
    import scripts.eval_harness.face_assignment as fa

    original = fa.global_fold_ranks
    try:
        fa.global_fold_ranks = lambda matched, k_folds=5: [0] * len(matched)  # type: ignore[assignment]
        with pytest.raises(ValueError, match="empty fit fold"):
            assign_open_set_kfold(faces, k_folds=2, tau_grid=(0.2, 0.5, 0.9))
    finally:
        fa.global_fold_ranks = original  # type: ignore[assignment]


def test_metrics_consume_pooled_not_single_tau_op_rescore():
    """Metrics read each face's POOLED per-fold decision, never a re-score at τ_op (EVAL-07)."""
    from scripts.eval_harness.face_assignment import FaceDecision
    from scripts.eval_harness.face_metrics import face_identification_pr

    rng = np.random.default_rng(0)
    faces: list[MatchedFace] = []
    for i in range(10):
        faces.append(_matched(i, 0, [1.0, 0.05 * i, 0.0], "Alice"))
    for i in range(10):
        faces.append(_matched(100 + i, 0, [0.0, 1.0, 0.05 * i], "Bob"))
    for i in range(5):
        faces.append(_matched(200 + i, 0, list(rng.normal(size=3)), None))

    result = assign_open_set_kfold(faces, k_folds=5)
    assert len(result.tau_k) == 5
    assert result.tau_op == pytest.approx(float(np.median(result.tau_k)))
    # Structural: every pooled decision carries its OWN fold's τ_k.
    assert all(d.tau_k == result.tau_k[d.fold] for d in result.decisions)

    # Discrimination (TEST-15, not tautology): a pooled REJECT whose s_max sits
    # ABOVE τ_op must be counted as a reject (FN for an enrolled identity), NOT
    # silently re-scored to an accept at a single global τ_op. If a metric
    # regressed to `accept = s_max >= tau_op`, this face would flip to a TP and
    # the assertions below would go red.
    tau_op = 0.5
    rejected_above_tau_op = FaceDecision(
        media_id=1, path="p.jpg", box_index=0, det_index=0,
        true_name="Alice", decision="reject", predicted_name=None,
        s_max=0.90, name_star="Alice", tau_k=0.95, fold=0,
        enrolled=True, excluded_single_face_recall=False,
    )
    assert rejected_above_tau_op.s_max > tau_op  # a τ_op re-score WOULD accept
    pr = face_identification_pr([rejected_above_tau_op], missed_gt=0, unmatched_detections=0)
    assert pr.true_positives == 0 and pr.false_negatives == 1


def test_open_set_f1_zero_over_zero_is_zero():
    counts = OpenSetCounts(0, 0, 0)
    assert counts.precision == 0.0
    assert counts.recall == 0.0
    assert counts.f1 == 0.0


def test_select_tau_tiebreak_largest_contiguous_plateau_mean():
    """When a contiguous max-F1 plateau exists, pick grid τ closest to its mean."""
    # Construct probes that yield F1==1 for a plateau of mid-grid taus and lower elsewhere.
    # Perfect Alice matches with high cosine; no strangers → any low-enough τ is max F1.
    faces = [
        _matched(1, 0, [1, 0], "Alice"),
        _matched(2, 0, [0.99, 0.01], "Alice"),
        _matched(3, 0, [0.98, 0.02], "Alice"),
        _matched(4, 0, [0, 1], "Bob"),
        _matched(5, 0, [0.01, 0.99], "Bob"),
        _matched(6, 0, [0.02, 0.98], "Bob"),
    ]
    by_id = matched_named_by_identity(faces)
    counts = {n: len(fs) for n, fs in by_id.items()}
    # With near-perfect separation, F1 is max across a wide plateau of low-to-mid τ.
    tau = select_tau_open_set_f1(
        probes=faces,
        by_identity=by_id,
        identity_counts=counts,
        tau_grid=TAU_GRID,
    )
    # Full-grid plateau (perfect separation → F1==1.0 at every grid τ): the mean
    # of 0.20..0.90 is 0.55, which is on the grid. Assert the CONCRETE tie-break
    # value — a smallest-τ regression would return 0.20 (the §E-forbidden
    # most-permissive τ) yet still pass a bare `0.20<=tau<=0.90` range check
    # (TEST-15: the assertion must be able to go red on that regression).
    assert tau == pytest.approx(0.55)


def test_select_tau_empty_probes_returns_grid_mid():
    tau = select_tau_open_set_f1(
        probes=[],
        by_identity={},
        identity_counts={},
        tau_grid=TAU_GRID,
    )
    assert tau == TAU_GRID[len(TAU_GRID) // 2]


def test_largest_contiguous_plateau_prefers_larger_tau_on_length_tie():
    """§E: on two EQUAL-length max-F1 plateaus, keep the LATER (larger-τ) run.

    Ascending τ grid → later index == larger τ. A strict-`>` regression keeps the
    earliest (smallest-τ) plateau — the most-permissive τ §E forbids as a
    false-accept bias. TEST-15 can-fail guard for the tie-break selector.
    """
    from scripts.eval_harness.face_assignment import _largest_contiguous_plateau_indices

    # Two isolated equal-length (len-2) max runs: indices [1,2] and [4,5] → later wins.
    assert _largest_contiguous_plateau_indices([0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0], 1.0) == [4, 5]
    # A strictly-longer earlier run still wins over a shorter later one.
    assert _largest_contiguous_plateau_indices([1.0, 1.0, 1.0, 0.0, 1.0], 1.0) == [0, 1, 2]


# ---------------------------------------------------------------------------
# §F similar_people Hungarian
# ---------------------------------------------------------------------------


def test_similar_people_hungarian_no_double_assigned_name():
    """≥2-identity photo: one-to-one names — no double-assigned gallery name."""
    # Two faces, two identities with clear embeddings.
    alice_a = _matched(1, 0, [1, 0], "Alice", path="group.jpg")
    bob_b = _matched(1, 1, [0, 1], "Bob", path="group.jpg")
    # Extra enrollment faces so both are enrolled.
    alice_enroll = _matched(2, 0, [0.99, 0.01], "Alice", path="a2.jpg")
    bob_enroll = _matched(3, 0, [0.01, 0.99], "Bob", path="b2.jpg")
    all_faces = [alice_a, bob_b, alice_enroll, bob_enroll]
    by_id = matched_named_by_identity(all_faces)
    counts = {n: len(fs) for n, fs in by_id.items()}
    tau_map = {
        (1, 0, 0): 0.3,
        (1, 1, 0): 0.3,
        (2, 0, 0): 0.3,
        (3, 0, 0): 0.3,
    }
    result = similar_people_hungarian(
        probes_on_photo=[alice_a, bob_b],
        by_identity=by_id,
        identity_counts=counts,
        tau_by_probe_key=tau_map,
    )
    accepted = [d.predicted_name for d in result.face_decisions if d.decision == "accept"]
    # No name assigned twice.
    assert len(accepted) == len(set(accepted))
    names = {d.box_index: d.predicted_name for d in result.face_decisions}
    assert names[0] == "Alice"
    assert names[1] == "Bob"


def test_score_similar_people_selects_multi_identity_photos():
    faces = [
        _matched(1, 0, [1, 0], "Alice", path="g.jpg"),
        _matched(1, 1, [0, 1], "Bob", path="g.jpg"),
        _matched(2, 0, [0.99, 0.01], "Alice", path="solo.jpg"),
        _matched(3, 0, [0.01, 0.99], "Bob", path="solo2.jpg"),
    ]
    assignment = assign_open_set_kfold(faces, k_folds=2, tau_grid=(0.2, 0.5, 0.9))
    results = score_similar_people(faces, assignment.decisions)
    assert len(results) == 1
    assert results[0].media_id == 1


# ---------------------------------------------------------------------------
# End-to-end score_face_assignment + determinism
# ---------------------------------------------------------------------------


def test_score_face_assignment_end_to_end():
    run_items = [
        {
            "media_id": 1,
            "path": "a.jpg",
            "model_id": "test",
            "embedding_dim": 2,
            "image_size": [100, 100],
            "faces": [
                _face([40, 40, 20, 20], [1, 0]),
                _face([10, 10, 15, 15], [0.1, 0.9]),  # stranger-ish
            ],
        },
        {
            "media_id": 2,
            "path": "b.jpg",
            "model_id": "test",
            "embedding_dim": 2,
            "image_size": [100, 100],
            "faces": [_face([40, 40, 20, 20], [0.95, 0.05])],
        },
    ]
    gt = {
        1: [_gt(0.5, 0.5, 0.2, 0.2, "Alice"), _gt(0.15, 0.15, 0.15, 0.15, None)],
        2: [_gt(0.5, 0.5, 0.2, 0.2, "Alice")],
    }
    result = score_face_assignment(run_items, gt, k_folds=2, tau_grid=(0.2, 0.5, 0.9))
    assert len(result.matched) >= 2
    assert len(result.decisions) == len(result.matched)
    assert isinstance(result.association_by_media[1], AssociationResult)


def test_determinism_loo_kfold_cross_process(tmp_path: Path):
    """LOO + k-fold pooled decisions AND §F clustering re-derive identically under varied PYTHONHASHSEED."""
    script = tmp_path / "run_score.py"
    script.write_text(
        """
import json, sys
from scripts.eval_harness.face_assignment import score_face_assignment, MatchedFace, assign_open_set_kfold

faces = []
for i in range(8):
    faces.append({
        "media_id": i,
        "path": f"p{i}.jpg",
        "box_index": 0,
        "det_index": 0,
        "embedding": [1.0, 0.01 * i],
        "true_name": "Alice" if i < 4 else "Bob",
    })
# normalize embeddings
import numpy as np
matched = []
from scripts.eval_harness.face_assignment import MatchedFace
for f in faces:
    e = np.asarray(f["embedding"], dtype=float)
    e = e / np.linalg.norm(e)
    matched.append(MatchedFace(
        media_id=f["media_id"], path=f["path"], box_index=0, det_index=0,
        embedding=tuple(e.tolist()), true_name=f["true_name"],
    ))
r = assign_open_set_kfold(matched, k_folds=4, tau_grid=(0.2, 0.4, 0.6, 0.8))
out = {
    "tau_k": list(r.tau_k),
    "tau_op": r.tau_op,
    "decisions": [
        {
            "media_id": d.media_id,
            "decision": d.decision,
            "predicted_name": d.predicted_name,
            "tau_k": d.tau_k,
            "fold": d.fold,
            "s_max": None if d.s_max == float("-inf") else d.s_max,
        }
        for d in r.decisions
    ],
}
# Clustering (§F single-linkage) must ALSO re-derive identically cross-process:
# union-find + pair-counting can be dict/set-iteration-order sensitive.
from scripts.eval_harness.face_metrics import clustering_sweep
_named_m = [m for m in matched if m.true_name is not None]
_sweep, _headline = clustering_sweep(
    [list(m.embedding) for m in _named_m],
    [m.true_name for m in _named_m],
    tau_grid=(0.2, 0.4, 0.6, 0.8),
    tau_op=r.tau_op,
)
out["clustering_headline"] = {
    "labels": list(_headline.labels),
    "purity": _headline.purity,
    "false_merge": _headline.false_merge,
    "false_split": _headline.false_split,
    "directional": _headline.directional,
}
out["clustering_sweep_labels"] = [list(c.labels) for c in _sweep]
print(json.dumps(out, sort_keys=True))
"""
    )
    env_base = {"PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    outs = []
    for seed in ("0", "1", "42"):
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
            env={**os.environ, **env_base, "PYTHONHASHSEED": seed},
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        outs.append(proc.stdout.strip())
    assert outs[0] == outs[1] == outs[2]


def test_scipy_optimize_importable():
    """rg-001: scipy is a direct dep; Hungarian entrypoint must import."""
    import scipy.optimize
    from scipy.optimize import linear_sum_assignment

    assert linear_sum_assignment is not None
    assert scipy.optimize is not None


# ---------------------------------------------------------------------------
# Namedness: gt_box_name must share body with face_metrics.named_box_name (wF2)
# ---------------------------------------------------------------------------


def test_gt_box_name_agrees_with_named_box_name_on_adversarial_names() -> None:
    """Association and face_metrics must use one namedness rule (TEST-06 / TEST-15).

    Assert agreement between the two call sites across adversarial names — not
    hardcoded expected strings. Divergence on BOM/ZWSP was the Wave E residual:
    strip-only ``gt_box_name`` treated format-control-padded names as named while
    ``named_box_name`` (Cf drop + strip) treated them as named under a different
    key or as anonymous when Cf-only.
    """
    adversarial = [
        "\ufeffAlice",  # BOM + name
        "\u200bAlice",  # ZWSP + name
        "A\u200bB",  # ZWSP mid
        " Alice ",  # padded
        "\u00a0Alice\u00a0",  # NBSP padded
        "   ",  # whitespace-only
        "\u200b",  # ZWSP-only → anonymous under Cf rule
        "\ufeff",  # BOM-only → anonymous under Cf rule
        "",  # empty
        None,  # missing
        "Alice",  # normal
        "Bob Builder",
    ]
    disagreements: list[str] = []
    for raw in adversarial:
        box = {"name": raw}
        left = gt_box_name(box)
        right = named_box_name(box)
        if left != right:
            disagreements.append(f"raw={raw!r} gt_box_name={left!r} named_box_name={right!r}")
    assert not disagreements, (
        "gt_box_name must agree with face_metrics.named_box_name (single harness "
        f"predicate); diverged on:\n  " + "\n  ".join(disagreements)
    )

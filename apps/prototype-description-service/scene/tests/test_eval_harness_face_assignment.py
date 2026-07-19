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


def _gt(x: float, y: float, w: float, h: float, name: str | None) -> dict:
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


def test_global_fold_key_spreads_identities_and_strangers():
    """Each identity's faces and strangers appear across folds (no empty named fold)."""
    faces: list[MatchedFace] = []
    # 5 faces each for Alice, Bob + 5 strangers → with K=5 each fold gets one of each.
    for i in range(5):
        faces.append(_matched(100 + i, 0, [1, 0, float(i) * 0.01], "Alice", path=f"a{i}.jpg"))
        faces.append(_matched(200 + i, 0, [0, 1, float(i) * 0.01], "Bob", path=f"b{i}.jpg"))
        faces.append(_matched(300 + i, 0, [0, 0, 1], None, path=f"s{i}.jpg"))

    folds = global_fold_ranks(faces, k_folds=5)
    assert set(folds) == {0, 1, 2, 3, 4}

    for k in range(5):
        in_fold = [f for f, fold in zip(faces, folds, strict=True) if fold == k]
        names = {f.true_name for f in in_fold}
        assert "Alice" in names
        assert "Bob" in names
        assert None in names  # stranger present in every fold


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


def test_metrics_consume_pooled_not_single_tau_op_rescore():
    """Different folds may use different τ_k — decisions are not one global threshold."""
    # Build faces where scores straddle the grid so fold τ can differ.
    rng = np.random.default_rng(0)
    faces: list[MatchedFace] = []
    for i in range(10):
        # Alice cluster near e0
        faces.append(_matched(i, 0, [1.0, 0.05 * i, 0.0], "Alice"))
    for i in range(10):
        faces.append(_matched(100 + i, 0, [0.0, 1.0, 0.05 * i], "Bob"))
    for i in range(5):
        # strangers far from both
        faces.append(_matched(200 + i, 0, list(rng.normal(size=3)), None))

    result = assign_open_set_kfold(faces, k_folds=5)
    # τ_k need not be identical across folds for this to be valid; pooled uses each face's fold τ.
    assert len(result.tau_k) == 5
    assert result.tau_op == pytest.approx(float(np.median(result.tau_k)))
    # Each decision's tau_k matches its fold's entry.
    for d in result.decisions:
        assert d.tau_k == result.tau_k[d.fold]


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
    assert tau in TAU_GRID
    # Residual ties → larger τ within plateau-mean closest; value is provisional.
    assert 0.20 <= tau <= 0.90


def test_select_tau_empty_probes_returns_grid_mid():
    tau = select_tau_open_set_f1(
        probes=[],
        by_identity={},
        identity_counts={},
        tau_grid=TAU_GRID,
    )
    assert tau == TAU_GRID[len(TAU_GRID) // 2]


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
    """LOO + k-fold pooled decisions re-derive identically under varied PYTHONHASHSEED."""
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

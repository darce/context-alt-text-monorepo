"""FIR-12 BR-26: run-record → SearchResult adapter — EVAL-16/18/19, MLDATA-09.

TEST-15: each of the seven assertions is proven live against a /tmp mutant.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.eval_harness.face_assignment import (
    argmax_gallery,
    assign_open_set_kfold,
    collect_matched_faces,
    mean_prototype,
)
from scripts.eval_harness.fir_bakeoff_run import (
    PROBE_STRATA,
    FirBakeoffRunError,
    RunPlan,
    build_run_plan,
    score_run,
)
from scripts.eval_harness.fir_search_adapter import (
    max_score_per_search_unit,
    searches_from_run_records,
)
from scripts.eval_harness.gallery_split import GalleryName, GallerySplit, Template
from scripts.eval_harness.open_set_identification import SearchResult

_EMPTY_CELLS = ["mask_sufficient_n", "veil", "goggles", "hair_occl"]
SequenceNames = list[str | None]


def _unit(vec: list[float]) -> list[float]:
    array = np.asarray(vec, dtype=np.float64)
    norm = float(np.linalg.norm(array))
    assert norm > 0
    return (array / norm).tolist()


def _face(bbox_px: list[float], embedding: list[float]) -> dict[str, Any]:
    return {
        "bbox_px": bbox_px,
        "landmarks_px": [[0.0, 0.0]] * 5,
        "embedding": _unit(embedding),
        "det_score": 0.9,
    }


def _gt(x: float, y: float, w: float, h: float, name: str | None) -> dict[str, Any]:
    return {"x": x, "y": y, "w": w, "h": h, "name": name, "source": "iptc"}


def _item(media_id: int, faces: list[dict[str, Any]]) -> dict[str, Any]:
    dim = len(faces[0]["embedding"]) if faces else 3
    return {
        "media_id": media_id,
        "path": f"{media_id}.jpg",
        "model_id": "test",
        "embedding_dim": dim,
        "image_size": [100, 100],
        "faces": faces,
    }


def _layout(n: int) -> list[tuple[float, float, float, float, list[float]]]:
    out: list[tuple[float, float, float, float, list[float]]] = []
    for i in range(n):
        cx = (i + 0.5) / n
        cy = 0.5
        w = min(0.22, 0.9 / n)
        h = 0.22
        bbox = [(cx - w / 2) * 100.0, (cy - h / 2) * 100.0, w * 100.0, h * 100.0]
        out.append((cx, cy, w, h, bbox))
    return out


def _named_item(
    media_id: int, names: SequenceNames, vecs: dict[str, list[float]]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    layout = _layout(len(names))
    faces = []
    boxes = []
    for name, (cx, cy, w, h, bbox) in zip(names, layout, strict=True):
        boxes.append(_gt(cx, cy, w, h, name))
        faces.append(_face(bbox, vecs[name if name is not None else "_stranger"]))
    return _item(media_id, faces), boxes


def _empty_named_item(
    media_id: int, names: SequenceNames
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    layout = _layout(len(names))
    boxes = [
        _gt(cx, cy, w, h, name)
        for name, (cx, cy, w, h, _) in zip(names, layout, strict=True)
    ]
    return _item(media_id, []), boxes


def _entry(
    media_id: int, stratum: str, identities: list[str], sha_char: str
) -> dict[str, Any]:
    return {
        "sha256": sha_char * 64,
        "media_id": media_id,
        "stratum": stratum,
        "present_identities": identities,
    }


def _write_manifest(
    tmp_path: Path,
    entries: list[dict[str, Any]],
    *,
    strata_counts: dict[str, Any],
) -> Path:
    payload = {
        "schema": "bakeoff-selection/1",
        "entries": entries,
        "strata_counts": strata_counts,
        "declared_empty_cells": list(_EMPTY_CELLS),
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _counts(**images: int) -> dict[str, Any]:
    return {name: {"images": n, "unique_subjects_faces_gt0": 0} for name, n in images.items()}


def _two_subject_plan(tmp_path: Path, *, extra: list[dict[str, Any]] | None = None) -> RunPlan:
    entries = [
        _entry(1, "E_clean", ["Alice"], "a"),
        _entry(2, "E_clean", ["Alice"], "b"),
        _entry(3, "E_clean", ["Bob"], "c"),
        _entry(4, "E_clean", ["Bob"], "d"),
        _entry(10, "A_true_occluder", ["Alice"], "e"),
        _entry(11, "B_eyewear", ["Bob"], "f"),
    ]
    counts = _counts(A_true_occluder=1, B_eyewear=1, C_pose=0, D_capture=0, E_clean=4)
    if extra:
        entries.extend(extra)
        for item in extra:
            stratum = str(item["stratum"])
            current = counts[stratum]["images"]
            counts[stratum] = {
                "images": current + 1,
                "unique_subjects_faces_gt0": 0,
            }
    path = _write_manifest(tmp_path, entries, strata_counts=counts)
    return build_run_plan(selection_manifest_path=path, seed=7)


def _full_plan(tmp_path: Path) -> RunPlan:
    entries = [
        _entry(1, "E_clean", ["Alice"], "a"),
        _entry(2, "E_clean", ["Alice"], "b"),
        _entry(3, "E_clean", ["Bob"], "c"),
        _entry(4, "E_clean", ["Bob"], "d"),
        _entry(5, "E_clean", ["Dale", "Eve"], "i"),
        _entry(10, "A_true_occluder", ["Alice"], "e"),
        _entry(11, "B_eyewear", ["Bob"], "f"),
        _entry(12, "C_pose", ["Alice"], "g"),
        _entry(13, "D_capture", ["Carol"], "h"),
    ]
    path = _write_manifest(
        tmp_path,
        entries,
        strata_counts=_counts(
            A_true_occluder=1, B_eyewear=1, C_pose=1, D_capture=1, E_clean=5
        ),
    )
    return build_run_plan(selection_manifest_path=path, seed=7)


def _vecs() -> dict[str, list[float]]:
    return {
        "Alice": [1.0, 0.0, 0.0],
        "Bob": [0.0, 1.0, 0.0],
        "Dale": [0.0, 0.0, 1.0],
        "Eve": [1.0, 1.0, 0.0],
        "Carol": [0.0, 1.0, 1.0],
        "_stranger": [1.0, 0.0, 1.0],
    }


def _gallery_of(plan: RunPlan, subject: str) -> GalleryName:
    if subject in plan.split.g1:
        return GalleryName.G1
    if subject in plan.split.g2:
        return GalleryName.G2
    raise AssertionError(f"{subject!r} is not enrolled")


def _enrolled_template(plan: RunPlan, subject: str) -> Template:
    return plan.split.g1.get(subject) or plan.split.g2[subject]


def _enrollment_records(
    plan: RunPlan, vecs: dict[str, list[float]]
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    by_media: dict[int, list[str]] = {}
    for subject, template in {**plan.split.g1, **plan.split.g2}.items():
        for media_id in template.media_ids:
            by_media.setdefault(media_id, []).append(subject)
    items: list[dict[str, Any]] = []
    gt: dict[int, list[dict[str, Any]]] = {}
    for media_id, names in sorted(by_media.items()):
        unique = list(dict.fromkeys(names))
        item, boxes = _named_item(media_id, unique, vecs)
        items.append(item)
        gt[media_id] = boxes
    return items, gt


def _flatten(
    searches: dict[str, dict[str, list[SearchResult]]],
) -> list[SearchResult]:
    out: list[SearchResult] = []
    for payload in searches.values():
        out.extend(payload["mated"])
        out.extend(payload["nonmated"])
    return out


def _with_probe_in_gallery(
    plan: RunPlan, *, subject: str, probe_media_id: int
) -> RunPlan:
    own = _gallery_of(plan, subject)
    old = _enrolled_template(plan, subject)
    updated = Template(
        template_id=old.template_id,
        subject_id=old.subject_id,
        media_ids=tuple(dict.fromkeys((*old.media_ids, probe_media_id))),
    )
    if own is GalleryName.G1:
        g1 = {**plan.split.g1, subject: updated}
        g2 = dict(plan.split.g2)
    else:
        g1 = dict(plan.split.g1)
        g2 = {**plan.split.g2, subject: updated}
    split = GallerySplit(
        g1=g1,
        g2=g2,
        probe_templates=plan.split.probe_templates,
        withheld_probe_templates=plan.split.withheld_probe_templates,
    )
    return RunPlan(
        split=split,
        probe_entries=plan.probe_entries,
        seed=plan.seed,
        index=plan.index,
        gallery_entries=plan.gallery_entries,
        probe_sets=plan.probe_sets,
    )


def test_probe_media_in_searched_gallery_raises(tmp_path: Path) -> None:
    plan = _two_subject_plan(tmp_path)
    broken = _with_probe_in_gallery(plan, subject="Alice", probe_media_id=10)
    vecs = _vecs()
    items, gt = _enrollment_records(broken, vecs)
    probe, boxes = _named_item(10, ["Alice"], vecs)
    items.append(probe)
    gt[10] = boxes
    with pytest.raises(FirBakeoffRunError, match="present in searched gallery"):
        searches_from_run_records(items, gt, plan=broken)


def test_missed_named_gt_emits_fta_mated_search(tmp_path: Path) -> None:
    plan = _two_subject_plan(tmp_path)
    item, boxes = _empty_named_item(10, ["Alice"])
    searches, overall = searches_from_run_records([item], {10: boxes}, plan=plan)
    results = _flatten(searches)
    mated = [row for row in results if row.true_name is not None]
    assert len(results) == 1
    assert len(mated) == 1
    assert overall == []
    row = mated[0]
    assert row.detected is False
    assert row.top1_score is None
    assert row.top1_name is None
    assert row.true_name == "Alice"
    assert row.media_id == 10
    assert row.gallery == _gallery_of(plan, "Alice")


def test_missed_stranger_gt_emits_zero_searches(tmp_path: Path) -> None:
    extra = [_entry(12, "C_pose", [], "g")]
    plan = _two_subject_plan(tmp_path, extra=extra)
    item, boxes = _empty_named_item(12, [None])
    searches, overall = searches_from_run_records([item], {12: boxes}, plan=plan)
    assert _flatten(searches) == []
    assert overall == []
    assert all(
        payload["mated"] == [] and payload["nonmated"] == []
        for payload in searches.values()
    )


def test_adapter_publishes_raw_smax_below_kfold_tau(tmp_path: Path) -> None:
    plan = _two_subject_plan(tmp_path)
    vecs = _vecs()
    items, gt = _enrollment_records(plan, vecs)
    leftover_alice = 2 if 2 not in {mid for mid in _enrolled_template(plan, "Alice").media_ids} else None
    leftover_bob = 4 if 4 not in {mid for mid in _enrolled_template(plan, "Bob").media_ids} else None
    for media_id, name in ((leftover_alice, "Alice"), (leftover_bob, "Bob")):
        if media_id is None:
            continue
        item, boxes = _named_item(media_id, [name], vecs)
        items.append(item)
        gt[media_id] = boxes
    probe_vec = [0.10, 0.0, math.sqrt(1.0 - 0.01)]
    layout = _layout(1)
    cx, cy, w, h, bbox = layout[0]
    probe = _item(10, [_face(bbox, probe_vec)])
    items.append(probe)
    gt[10] = [_gt(cx, cy, w, h, "Alice")]

    matched, _, _, _ = collect_matched_faces(items, gt)
    kfold = assign_open_set_kfold(matched)
    probe_decisions = [d for d in kfold.decisions if d.media_id == 10]
    assert probe_decisions
    assert all(d.predicted_name is None for d in probe_decisions)
    assert all(d.decision == "reject" for d in probe_decisions)

    alice_gallery = _gallery_of(plan, "Alice")
    enrolled = _enrolled_template(plan, "Alice")
    proto_faces = [
        face
        for face in matched
        if face.media_id in enrolled.media_ids and face.true_name == "Alice"
    ]
    assert proto_faces
    prototypes = {
        "Alice": mean_prototype([face.embedding_array() for face in proto_faces])
    }
    probe_face = next(face for face in matched if face.media_id == 10)
    expected_s, expected_name = argmax_gallery(probe_face.embedding_array(), prototypes)
    assert expected_name == "Alice"
    assert expected_s < 0.20

    searches, _ = searches_from_run_records(items, gt, plan=plan)
    mated = [
        row
        for row in searches["A_true_occluder"]["mated"]
        if row.media_id == 10 and row.gallery == alice_gallery
    ]
    assert len(mated) == 1
    row = mated[0]
    assert row.detected is True
    assert row.top1_name == "Alice"
    assert row.top1_name is not None
    assert row.top1_score == pytest.approx(expected_s)
    assert row.top1_score is not None
    assert row.top1_score < 0.20


def test_empty_gallery_raises(tmp_path: Path) -> None:
    plan = _two_subject_plan(tmp_path)
    vecs = _vecs()
    alice = "Alice"
    bob_items, bob_gt = _enrollment_records(plan, vecs)
    bob_only_items = [
        item
        for item in bob_items
        if item["media_id"] in _enrolled_template(plan, "Bob").media_ids
    ]
    bob_only_gt = {
        media_id: boxes
        for media_id, boxes in bob_gt.items()
        if media_id in _enrolled_template(plan, "Bob").media_ids
    }
    probe, boxes = _named_item(10, [alice], vecs)
    with pytest.raises(FirBakeoffRunError, match="empty gallery"):
        searches_from_run_records(
            [*bob_only_items, probe],
            {**bob_only_gt, 10: boxes},
            plan=plan,
        )


@pytest.mark.parametrize(
    "high_first",
    [True, False],
    ids=["high_then_low", "low_then_high"],
)
def test_two_boxes_same_subject_one_search_max_score(
    tmp_path: Path, high_first: bool
) -> None:
    plan = _two_subject_plan(tmp_path)
    vecs = _vecs()
    items, gt = _enrollment_records(plan, vecs)
    high = [0.95, math.sqrt(1.0 - 0.95**2), 0.0]
    low = [0.30, math.sqrt(1.0 - 0.30**2), 0.0]
    layout = _layout(2)
    first_vec, second_vec = (high, low) if high_first else (low, high)
    faces = [
        _face(layout[0][4], first_vec),
        _face(layout[1][4], second_vec),
    ]
    boxes = [
        _gt(*layout[0][:4], "Alice"),
        _gt(*layout[1][:4], "Alice"),
    ]
    items.append(_item(10, faces))
    gt[10] = boxes

    gallery = _gallery_of(plan, "Alice")
    enrolled = _enrolled_template(plan, "Alice")
    proto = mean_prototype(
        [
            np.asarray(_unit(vecs["Alice"]), dtype=np.float64)
            for _ in enrolled.media_ids
        ]
    )
    s_high, _ = argmax_gallery(np.asarray(_unit(high)), {"Alice": proto})
    s_low, _ = argmax_gallery(np.asarray(_unit(low)), {"Alice": proto})
    assert s_high > s_low

    first_s, second_s = (s_high, s_low) if high_first else (s_low, s_high)
    reduced = max_score_per_search_unit(
        [
            ((10, gallery, "Alice"), first_s, "Alice"),
            ((10, gallery, "Alice"), second_s, "Alice"),
        ]
    )
    assert list(reduced) == [(10, gallery, "Alice")]
    assert reduced[(10, gallery, "Alice")][0] == pytest.approx(s_high)

    searches, _ = searches_from_run_records(items, gt, plan=plan)
    mated = [
        row
        for row in searches["A_true_occluder"]["mated"]
        if row.media_id == 10 and row.gallery == gallery
    ]
    assert len(mated) == 1
    assert mated[0].true_name == "Alice"
    assert mated[0].top1_score == pytest.approx(s_high)
    assert mated[0].top1_score != pytest.approx(s_low)


def test_round_trip_score_run_complete_finite_fnir(tmp_path: Path) -> None:
    plan = _full_plan(tmp_path)
    vecs = _vecs()
    items, gt = _enrollment_records(plan, vecs)
    probes: list[tuple[int, list[str | None]]] = [
        (10, ["Alice"]),
        (11, ["Bob"]),
        (12, ["Alice"]),
        (13, ["Carol"]),
    ]
    for media_id, names in probes:
        item, boxes = _named_item(media_id, names, vecs)
        items.append(item)
        gt[media_id] = boxes

    searches, overall_nonmated = searches_from_run_records(items, gt, plan=plan)
    report = score_run(
        plan=plan,
        searches=searches,
        overall_nonmated=overall_nonmated,
        tau=0.50,
    )
    assert report.overall.incomplete is False
    assert report.overall.fnir is not None
    assert math.isfinite(report.overall.fnir)
    assert report.overall.measured is True
    for name in PROBE_STRATA:
        assert report.search_shortfalls[name] == 0
        assert report.nonmated_shortfalls[name] == 0
        assert report.points[name].incomplete is False

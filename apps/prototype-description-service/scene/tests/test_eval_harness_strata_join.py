"""FIR-12: join run records to the frozen selection-manifest strata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness.face_run_record import FaceRunItem
from scripts.eval_harness.strata_join import (
    StratumJoinError,
    join_by_stratum,
    load_stratum_index,
)

_EMPTY_CELLS = ["mask_sufficient_n", "veil", "goggles", "hair_occl"]
_DECLARED_IMAGES = {
    "A_true_occluder": 32,
    "B_eyewear": 80,
    "C_pose": 34,
    "D_capture": 87,
    "E_clean": 407,
}


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "manifests" / "fir12-selection-v1.json"
        if candidate.is_file():
            return parent
    raise RuntimeError("cannot locate repo root from test path")


def _manifest_path() -> Path:
    return _repo_root() / "benchmarks" / "manifests" / "fir12-selection-v1.json"


def _raw_manifest() -> dict:
    return json.loads(_manifest_path().read_text(encoding="utf-8"))


def _face_item(media_id: int) -> FaceRunItem:
    return FaceRunItem(
        media_id=media_id,
        path=f"/tmp/{media_id}.jpg",
        model_id="unit/test",
        embedding_dim=4,
        image_size=[16, 16],
        faces=[],
    )


def _entry(
    media_id: int,
    stratum: str,
    identities: list[str],
    sha_char: str,
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
    strata_counts: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "schema": "bakeoff-selection/1",
        "entries": entries,
        "strata_counts": strata_counts
        or {"E_clean": {"images": len(entries), "unique_subjects_faces_gt0": 0}},
        "declared_empty_cells": list(_EMPTY_CELLS),
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_strata_counts_round_trip_from_frozen_manifest() -> None:
    path = _manifest_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    index = load_stratum_index(path)
    assert index.strata_counts == raw["strata_counts"]
    assert list(index.declared_empty_cells) == raw["declared_empty_cells"]
    assert index.strata_counts["A_true_occluder"]["images"] == 32
    assert index.strata_counts["B_eyewear"]["images"] == 80
    assert index.strata_counts["C_pose"]["images"] == 34
    assert index.strata_counts["D_capture"]["images"] == 87
    assert index.strata_counts["E_clean"]["images"] == 407
    assert index.declared_images == _DECLARED_IMAGES


def test_index_retains_present_identities_from_frozen_manifest() -> None:
    raw = _raw_manifest()
    first = raw["entries"][0]
    index = load_stratum_index(_manifest_path())
    expected = tuple(first["present_identities"])
    assert expected == ("Al Pacino",)
    assert index.subjects_by_sha256[first["sha256"]] == expected
    assert index.subjects_by_media_id[first["media_id"]] == expected


def test_unknown_record_key_raises() -> None:
    index = load_stratum_index(_manifest_path())
    with pytest.raises(StratumJoinError, match="absent from selection manifest"):
        join_by_stratum([{"sha256": "0" * 64, "subjects": ["Nobody"]}], index)
    with pytest.raises(StratumJoinError, match="absent from selection manifest"):
        join_by_stratum([{"media_id": 10**9, "subjects": ["Nobody"]}], index)
    with pytest.raises(StratumJoinError, match="absent from selection manifest"):
        join_by_stratum([_face_item(10**9)], index)


def test_declared_empty_cells_appear_in_to_rows() -> None:
    index = load_stratum_index(_manifest_path())
    report = join_by_stratum([], index)
    empty = [row for row in report.to_rows() if row["declared_empty"]]
    assert [row["stratum"] for row in empty] == _EMPTY_CELLS
    assert all(row["declared_empty"] is True for row in empty)
    assert all(row["n_images"] == 0 and row["unique_subjects"] == 0 for row in empty)
    assert all(row["manifest_images"] == 0 for row in empty)
    assert all(row["incomplete"] is False for row in empty)


def test_unique_subjects_counts_distinct_subjects_not_rows(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        [
            _entry(1, "E_clean", ["Same Subject"], "a"),
            _entry(2, "E_clean", ["Same Subject"], "b"),
        ],
        strata_counts={"E_clean": {"images": 2, "unique_subjects_faces_gt0": 1}},
    )
    report = join_by_stratum([_face_item(1), _face_item(2)], load_stratum_index(path))
    bucket = report.buckets["E_clean"]
    assert bucket.n_images == 2
    assert bucket.unique_subjects == 1
    rows = {row["stratum"]: row for row in report.to_rows()}
    assert rows["E_clean"]["unique_subjects"] == 1
    assert rows["E_clean"]["n_images"] == 2
    assert rows["E_clean"]["declared_empty"] is False


def test_unique_subjects_counts_two_distinct_identities(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        [
            _entry(1, "E_clean", ["Alice"], "a"),
            _entry(2, "E_clean", ["Bob"], "b"),
        ],
        strata_counts={"E_clean": {"images": 2, "unique_subjects_faces_gt0": 2}},
    )
    report = join_by_stratum([_face_item(1), _face_item(2)], load_stratum_index(path))
    assert report.buckets["E_clean"].unique_subjects == 2
    rows = {row["stratum"]: row for row in report.to_rows()}
    assert rows["E_clean"]["unique_subjects"] == 2
    assert rows["E_clean"]["n_images"] == 2
    assert rows["E_clean"]["incomplete"] is False
    assert report.coverage_gaps() == []


def test_face_run_item_unique_subjects_from_frozen_manifest() -> None:
    raw = _raw_manifest()
    pacino = next(entry for entry in raw["entries"] if entry["media_id"] == 6)
    winehouse = next(entry for entry in raw["entries"] if entry["media_id"] == 8)
    assert pacino["stratum"] == "E_clean"
    assert winehouse["stratum"] == "E_clean"
    assert pacino["present_identities"] == ["Al Pacino"]
    assert winehouse["present_identities"] == ["Amy Winehouse"]
    report = join_by_stratum(
        [_face_item(pacino["media_id"]), _face_item(winehouse["media_id"])],
        load_stratum_index(_manifest_path()),
    )
    row = {item["stratum"]: item for item in report.to_rows()}["E_clean"]
    assert row["unique_subjects"] == 2
    assert row["n_images"] == 2
    assert row["manifest_images"] == 407
    assert row["incomplete"] is True


def test_run_record_subjects_do_not_override_manifest(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        [
            _entry(1, "E_clean", ["Alice"], "a"),
            _entry(2, "E_clean", ["Bob"], "b"),
        ],
        strata_counts={"E_clean": {"images": 2, "unique_subjects_faces_gt0": 2}},
    )
    report = join_by_stratum(
        [
            {"media_id": 1, "subjects": ["Same Subject"]},
            {"media_id": 2, "subjects": ["Same Subject"]},
        ],
        load_stratum_index(path),
    )
    assert report.buckets["E_clean"].unique_subjects == 2


def test_subjects_fallback_when_manifest_omits_identities(tmp_path: Path) -> None:
    path = _write_manifest(
        tmp_path,
        [
            {"sha256": "a" * 64, "media_id": 1, "stratum": "E_clean"},
            {"sha256": "b" * 64, "media_id": 2, "stratum": "E_clean"},
        ],
        strata_counts={"E_clean": {"images": 2, "unique_subjects_faces_gt0": 2}},
    )
    report = join_by_stratum(
        [
            {"media_id": 1, "subjects": ["Alice"]},
            {"media_id": 2, "subjects": ["Bob"]},
        ],
        load_stratum_index(path),
    )
    assert report.buckets["E_clean"].unique_subjects == 2


def test_partial_run_marks_rows_incomplete_and_reports_gaps() -> None:
    raw = _raw_manifest()
    first = next(entry for entry in raw["entries"] if entry["stratum"] == "E_clean")
    report = join_by_stratum(
        [_face_item(first["media_id"])],
        load_stratum_index(_manifest_path()),
    )
    rows = {row["stratum"]: row for row in report.to_rows() if not row["declared_empty"]}
    assert rows["E_clean"]["n_images"] == 1
    assert rows["E_clean"]["manifest_images"] == 407
    assert rows["E_clean"]["incomplete"] is True
    for name, declared in _DECLARED_IMAGES.items():
        assert rows[name]["manifest_images"] == declared
        assert rows[name]["incomplete"] is True
        assert rows[name]["n_images"] < declared
    gaps = {gap["stratum"]: gap for gap in report.coverage_gaps()}
    assert set(gaps) == set(_DECLARED_IMAGES)
    assert gaps["E_clean"] == {
        "stratum": "E_clean",
        "joined_images": 1,
        "declared_images": 407,
    }
    assert gaps["A_true_occluder"] == {
        "stratum": "A_true_occluder",
        "joined_images": 0,
        "declared_images": 32,
    }
    assert gaps["B_eyewear"]["declared_images"] == 80
    assert gaps["C_pose"]["declared_images"] == 34
    assert gaps["D_capture"]["declared_images"] == 87
    assert all(cell not in gaps for cell in _EMPTY_CELLS)

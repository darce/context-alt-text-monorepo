"""FIR-12: join run records to the frozen selection-manifest strata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.strata_join import (
    StratumJoinError,
    join_by_stratum,
    load_stratum_index,
)


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


def test_unknown_record_key_raises() -> None:
    index = load_stratum_index(_manifest_path())
    with pytest.raises(StratumJoinError, match="absent from selection manifest"):
        join_by_stratum([{"sha256": "0" * 64, "subjects": ["Nobody"]}], index)
    with pytest.raises(StratumJoinError, match="absent from selection manifest"):
        join_by_stratum([{"media_id": 10**9, "subjects": ["Nobody"]}], index)


def test_declared_empty_cells_appear_in_to_rows() -> None:
    index = load_stratum_index(_manifest_path())
    report = join_by_stratum([], index)
    empty = [row for row in report.to_rows() if row["declared_empty"]]
    assert [row["stratum"] for row in empty] == [
        "mask_sufficient_n",
        "veil",
        "goggles",
        "hair_occl",
    ]
    assert all(row["declared_empty"] is True for row in empty)
    assert all(row["n_images"] == 0 and row["unique_subjects"] == 0 for row in empty)


def test_unique_subjects_counts_distinct_subjects_not_rows() -> None:
    raw = _raw_manifest()
    same_stratum = [entry for entry in raw["entries"] if entry["stratum"] == "E_clean"]
    first, second = same_stratum[0], same_stratum[1]
    index = load_stratum_index(_manifest_path())
    report = join_by_stratum(
        [
            {
                "sha256": first["sha256"],
                "media_id": first["media_id"],
                "subjects": ["Same Subject"],
            },
            {
                "sha256": second["sha256"],
                "media_id": second["media_id"],
                "subjects": ["Same Subject"],
            },
        ],
        index,
    )
    bucket = report.buckets["E_clean"]
    assert bucket.n_images == 2
    assert bucket.unique_subjects == 1
    rows = {row["stratum"]: row for row in report.to_rows()}
    assert rows["E_clean"]["unique_subjects"] == 1
    assert rows["E_clean"]["n_images"] == 2
    assert rows["E_clean"]["declared_empty"] is False

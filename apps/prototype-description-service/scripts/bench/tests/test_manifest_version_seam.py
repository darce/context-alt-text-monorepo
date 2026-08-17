"""Detection exhaustiveness outcomes + no present_identities subtraction in bench/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench.corpus import load_bench_manifest, non_exhaustive_ids
from scripts.bench.score_report import CrossbenchTier, assign_tier, stranger_faces_for
from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.manifest import ManifestError

FIXTURE = Path(__file__).parent / "fixtures" / "v3_boxed_detection.json"


def test_require_true_mismatch_raises() -> None:
    with pytest.raises(BenchError) as exc:
        load_bench_manifest(FIXTURE, None, require_detection_exhaustiveness=True, skip_hash_verification=True)
    assert exc.value.code == "gt_box_count_mismatch"


def test_exhaustive_stamp_refuses_count_mismatch(tmp_path: Path) -> None:
    """TEST-15: roster_only mismatch cannot hide under an exhaustive stamp."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["annotation_mode"] = "exhaustive"
    dest = tmp_path / "exhaustive-mismatch.json"
    dest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManifestError, match="boxes_cover_face_count"):
        load_bench_manifest(dest, None)


def test_v3_loader_refuses_unstamped_annotation_mode(tmp_path: Path) -> None:
    """TEST-15: omitting annotation_mode fails load; omission is not exhaustive."""
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    del raw["annotation_mode"]
    dest = tmp_path / "unstamped.json"
    dest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManifestError, match="annotation_mode is required"):
        load_bench_manifest(dest, None)


def test_default_flag_loads_mismatch_as_non_exhaustive() -> None:
    manifest = load_bench_manifest(FIXTURE, None, require_detection_exhaustiveness=False, skip_hash_verification=True)
    assert 3 in non_exhaustive_ids(manifest)
    mismatch = next(e for e in manifest.entries if e.media_id == 3)
    assert stranger_faces_for(mismatch) == 0


def test_exhaustive_stranger_faces_from_unnamed_boxes() -> None:
    manifest = load_bench_manifest(FIXTURE, None, require_detection_exhaustiveness=False, skip_hash_verification=True)
    multi = next(e for e in manifest.entries if e.media_id == 1)
    assert stranger_faces_for(multi) == 0  # both boxes named
    # zero-box entry cannot be scored for detection (boxes present is required)
    from scripts.bench.corpus import is_detection_exhaustive

    zero = next(e for e in manifest.entries if e.media_id == 2)
    assert zero.face_count == len(zero.face_boxes) == 0
    assert is_detection_exhaustive(zero) is False
    assert 2 in non_exhaustive_ids(manifest)


def test_detection_cell_directional_when_non_exhaustive_dropped() -> None:
    tier, reason = assign_tier(
        "detection_recall@frame_e2e/label_map_primary",
        {
            "named": True,
            "primary": True,
            "optimistic": False,
            "native_frame": False,
            "floor_ok": True,
            "ci_half_width": 0.0,
            "head_to_head_delta": 0.10,
            "holm_significant": True,
            "exhaustiveness_ok": False,
            "count_only": False,
        },
    )
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "detection_exhaustiveness_unasserted"


def test_identification_cell_directional_when_non_exhaustive() -> None:
    tier, reason = assign_tier(
        "identification_recall@frame_e2e/label_map_primary",
        {
            "named": True,
            "primary": False,
            "optimistic": False,
            "native_frame": False,
            "floor_ok": True,
            "ci_half_width": 0.0,
            "head_to_head_delta": 0.10,
            "holm_significant": True,
            "exhaustiveness_ok": False,
            "count_only": False,
        },
    )
    assert tier is CrossbenchTier.DIRECTIONAL
    assert reason == "detection_exhaustiveness_unasserted"


def test_no_present_identities_subtraction_in_bench_package() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for py in root.rglob("*.py"):
        if "tests" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        if "present_identities" in text and "len(" in text:
            for line in text.splitlines():
                if "len(" in line and "present_identities" in line and "-" in line:
                    offenders.append(f"{py.name}:{line.strip()}")
    assert offenders == []

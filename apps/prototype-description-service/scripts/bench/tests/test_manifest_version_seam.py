"""Detection exhaustiveness outcomes + no present_identities subtraction in bench/."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bench import score_report as score_report_module
from scripts.bench.corpus import load_bench_manifest, non_exhaustive_ids
from scripts.bench.score_report import CrossbenchTier, assign_tier, stranger_faces_for
from scripts.bench.stack_pair import BenchError
from scripts.eval_harness.face_metrics import ImageDetection, detection_pr_strict
from scripts.eval_harness.manifest import (
    AnnotationMode,
    FaceBox,
    ManifestError,
    ScoreInvariant,
)

FIXTURE = Path(__file__).parent / "fixtures" / "v3_boxed_detection.json"


def test_require_true_mismatch_raises() -> None:
    with pytest.raises(BenchError) as exc:
        load_bench_manifest(
            FIXTURE,
            None,
            require_detection_exhaustiveness=True,
            metadata_only=True,
            skip_hash_verification=True,
            hash_skip_reason="detection-exhaustiveness check is metadata-only",
        )
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
    """TEST-15: the bench seam loads the boxed v3 fixture through the v3 contract."""
    manifest = load_bench_manifest(
        FIXTURE,
        None,
        require_detection_exhaustiveness=False,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="detection-exhaustiveness check is metadata-only",
    )
    # A switch to the legacy v2 loader must not silently route this bench path.
    assert manifest.manifest_version == 3
    assert 3 in non_exhaustive_ids(manifest)
    mismatch = next(e for e in manifest.entries if e.media_id == 3)
    assert stranger_faces_for(mismatch) == 0


def test_exhaustive_stranger_faces_from_unnamed_boxes() -> None:
    manifest = load_bench_manifest(
        FIXTURE,
        None,
        require_detection_exhaustiveness=False,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="detection-exhaustiveness check is metadata-only",
    )
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


def _strict_detection_row(gt_box: dict[str, object]) -> ImageDetection:
    return ImageDetection(
        image="source-test.jpg",
        pred_faces=1,
        labeled_faces=1,
        detections_bbox_px=((40.0, 40.0, 20.0, 20.0),),
        gt_boxes=(gt_box,),
        image_size=(100, 100),
        detection_frame_size=(100, 100),
    )


@pytest.mark.parametrize(
    "missing_part",
    ["manifest_entry", "join_row", "stack_media_id"],
)
def test_strict_detection_inputs_rejects_missing_mapping(missing_part: str) -> None:
    manifest = load_bench_manifest(
        FIXTURE,
        None,
        require_detection_exhaustiveness=False,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="strict input join check is metadata-only",
    )
    entry = manifest.entries[0]
    detection_path = "orphan.jpg" if missing_part == "manifest_entry" else entry.path
    join: dict[int, dict[str, object]] = {}
    expected_code = "manifest_entry_missing"
    if missing_part == "join_row":
        expected_code = "join_row_missing"
    elif missing_part == "stack_media_id":
        join[entry.media_id] = {"image_width": 100, "image_height": 100}
        expected_code = "join_row_missing"

    with pytest.raises(BenchError) as exc:
        score_report_module._strict_detection_inputs(
            [ImageDetection(image=detection_path, pred_faces=0, labeled_faces=0)],
            manifest,
            {"media_identities": []},
            join,
        )

    assert exc.value.code == expected_code
    assert detection_path in str(exc.value)
    if missing_part != "manifest_entry":
        assert f"media_id={entry.media_id}" in str(exc.value)


def _adjudicated_gt_box() -> dict[str, object]:
    return {
        "x": 0.5,
        "y": 0.5,
        "w": 0.2,
        "h": 0.2,
        "name": "Alice Q",
        "source": "iptc",
        "lineage": {
            "labeler_id": "bench-test",
            "batch_id": "source-test",
            "capture_session_id": "source-test-session",
            "pass_index": 0,
            "labeled_at": "2026-08-16T00:00:00Z",
            "tool_version": "bench-test",
            "label_source": "operator_blind",
            "saw_machine_proposals": False,
            "decision": "named",
            "confidence": "high",
        },
    }


def _load_review_manifest(
    tmp_path: Path,
    *,
    review_record_id: str = "review-2026-17",
    record_changes: dict[str, object] | None = None,
) -> object:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["entries"][0]["face_boxes"][0]["adjudication_source"] = (
        f"human_adjudicated:{review_record_id}"
    )
    record: dict[str, object] = {
        "record_id": "review-2026-17",
        "media_id": 1,
        "box_index": 0,
        "reviewer_id": "independent-reviewer",
        "reviewer_kind": "human",
        "review_method": "independent_blind_review",
        "decision": "confirmed",
        "reviewed_at": "2026-08-18T12:30:00Z",
    }
    if record_changes:
        record.update(record_changes)
    raw["adjudication_records"] = [record]
    dest = tmp_path / "review-evidence.json"
    dest.write_text(json.dumps(raw), encoding="utf-8")
    return load_bench_manifest(
        dest,
        None,
        metadata_only=True,
        skip_hash_verification=True,
        hash_skip_reason="review evidence resolves from pinned manifest metadata",
    )


def test_adjudication_reference_resolves_to_independent_human_review(tmp_path: Path) -> None:
    manifest = _load_review_manifest(tmp_path)

    assert manifest.entries[0].face_boxes[0].adjudication_source == (
        "human_adjudicated:review-2026-17"
    )


def test_adjudication_reference_refuses_missing_record(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="human adjudication record .* is missing"):
        _load_review_manifest(tmp_path, review_record_id="fabricated-review-id")


def test_adjudication_reference_refuses_original_labeler_as_reviewer(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="not independent of the original labeler"):
        _load_review_manifest(tmp_path, record_changes={"reviewer_id": "bench-test"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reviewer_kind", "automated"),
        ("review_method", "proposal_assisted"),
        ("decision", "rejected"),
        ("reviewed_at", "2026-08-18T12:30:00"),
    ],
)
def test_adjudication_evidence_schema_rejects_unqualified_review(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(ManifestError, match=field):
        _load_review_manifest(tmp_path, record_changes={field: value})


@pytest.mark.parametrize("source", ["buffalo", "future_source"])
def test_face_box_source_schema_rejects_unsupported_source(source: str) -> None:
    raw = _adjudicated_gt_box()
    raw["source"] = source
    with pytest.raises(ValueError):
        FaceBox.model_validate(raw)


@pytest.mark.parametrize("source", ["buffalo", "future_source", None])
def test_strict_detection_refuses_missing_or_unsupported_gt_source(
    source: str | None,
) -> None:
    """TEST-15: raw report mappings cannot bypass the independent GT source gate."""
    box = _adjudicated_gt_box()
    if source is None:
        del box["source"]
    else:
        box["source"] = source

    with pytest.raises(ManifestError) as exc:
        detection_pr_strict(
            [_strict_detection_row(box)],
            annotation_mode=AnnotationMode.EXHAUSTIVE,
            run_manifest={"iou_threshold": 0.5},
        )

    assert exc.value.invariant == ScoreInvariant.DETECTION_REQUIRES_INDEPENDENT_GT_SOURCE


@pytest.mark.parametrize("source", ["iptc", "operator"])
def test_strict_detection_accepts_supported_independent_gt_source(source: str) -> None:
    box = _adjudicated_gt_box()
    box["source"] = source
    result = detection_pr_strict(
        [_strict_detection_row(box)],
        annotation_mode=AnnotationMode.EXHAUSTIVE,
        run_manifest={"iou_threshold": 0.5},
    )
    assert result.true_positives == 1
    assert result.false_positives == 0
    assert result.false_negatives == 0


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

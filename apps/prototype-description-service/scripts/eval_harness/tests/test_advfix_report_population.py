"""Regression tests for full-population and detection-ground-truth admission."""

from __future__ import annotations

import json

import pytest

from scripts.eval_harness.manifest import ManifestError, ScoreInvariant, load_manifest
from scripts.eval_harness.report import score_face_run_record


def _lineage(*, label_source: str = "operator_blind") -> dict:
    return {
        "labeler_id": "labeler-1",
        "batch_id": "batch-1",
        "capture_session_id": "capture-session-1",
        "pass_index": 0,
        "labeled_at": "2026-08-14T00:00:00Z",
        "tool_version": "test",
        "saw_machine_proposals": False,
        "label_source": label_source,
        "decision": "named",
        "confidence": "high",
        "arbitration_of": None,
    }


def _box(*, source: str = "operator", label_source: str = "operator_blind") -> dict:
    return {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": "Alice Example",
        "source": source,
        "lineage": _lineage(label_source=label_source),
    }


def _entry(media_id: int, *, box: dict | None = None) -> dict:
    return {
        "path": f"mock_images/{media_id}.jpg",
        "sha256": "a" * 64,
        "media_id": media_id,
        "face_count": 1 if box is not None else 0,
        "present_identities": ["Alice Example"] if box is not None else [],
        "context_pack": {"title": "test"},
        "base_caption": "Alice Example.",
        "must_right": ["Alice Example"] if box is not None else [],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "provenance": {"source": "fixture", "license": "fixture"},
        "face_boxes": [] if box is None else [box],
    }


def _record(media_ids: list[int]) -> dict:
    return {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "2026-08-14T00:00:00Z",
            "leg": "candidate",
        },
        "items": [
            {
                "media_id": media_id,
                "path": f"mock_images/{media_id}.jpg",
                "model_id": "fixture-model",
                "embedding_dim": 4,
                "image_size": [10, 10],
                "faces": [
                    {
                        "bbox_px": [4.0, 2.5, 2.0, 3.0],
                        "landmarks_px": [[0.0, 0.0]] * 5,
                        "embedding": [1.0, 0.0, 0.0, 0.0],
                        "det_score": 0.9,
                    }
                ],
            }
            for media_id in media_ids
        ],
    }


def _write_v3_manifest(tmp_path, box: dict):
    document = {
        "manifest_version": 3,
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": [_entry(1, box=box)],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_manifest(str(path), skip_hash_verification=True)


def test_face_score_refuses_run_record_that_covers_only_part_of_manifest() -> None:
    entries = []
    adjudication_records = []
    for media_id in range(1, 11):
        record_id = f"review-{media_id}"
        box = {**_box(), "adjudication_source": f"human_adjudicated:{record_id}"}
        entries.append({**_entry(media_id, box=box), "annotation_mode": "exhaustive"})
        adjudication_records.append(
            {
                "record_id": record_id,
                "media_id": media_id,
                "box_index": 0,
                "reviewer_id": "reviewer-1",
                "reviewer_kind": "human",
                "review_method": "independent_blind_review",
                "decision": "confirmed",
                "reviewed_at": "2026-08-14T01:00:00Z",
            }
        )
    manifest = {
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": entries,
        "adjudication_records": adjudication_records,
    }

    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_record([1]), manifest)

    assert exc_info.value.invariant == "face_run_population_mismatch"
    assert "missing_media_ids=[2, 3, 4, 5, 6, 7, 8, 9, 10]" in str(exc_info.value)


def test_face_score_refuses_detector_sourced_v3_ground_truth(tmp_path) -> None:
    manifest = _write_v3_manifest(
        tmp_path,
        _box(source="detector", label_source="legacy_import"),
    )

    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_record([1]), manifest)

    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_INDEPENDENT_GT_SOURCE


def test_face_score_refuses_legacy_import_lineage_without_human_adjudication(tmp_path) -> None:
    manifest = _write_v3_manifest(
        tmp_path,
        _box(source="operator", label_source="legacy_import"),
    )

    with pytest.raises(ManifestError) as exc_info:
        score_face_run_record(_record([1]), manifest)

    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_HUMAN_ADJUDICATED_GT_LINEAGE

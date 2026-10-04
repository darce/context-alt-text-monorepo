"""Regression tests for errored run items in strict face score populations."""

from __future__ import annotations

from scripts.eval_harness.report import score_face_run_record


def _lineage() -> dict:
    return {
        "labeler_id": "labeler-1",
        "batch_id": "batch-1",
        "capture_session_id": "capture-session-1",
        "pass_index": 0,
        "labeled_at": "2026-08-14T00:00:00Z",
        "tool_version": "test",
        "saw_machine_proposals": False,
        "label_source": "operator_blind",
        "decision": "named",
        "confidence": "high",
        "arbitration_of": None,
    }


def _box() -> dict:
    return {
        "x": 0.5,
        "y": 0.4,
        "w": 0.2,
        "h": 0.3,
        "name": "Alice Example",
        "source": "operator",
        "lineage": _lineage(),
    }


def _entry(media_id: int, box: dict) -> dict:
    return {
        "path": f"mock_images/{media_id}.jpg",
        "sha256": "a" * 64,
        "media_id": media_id,
        "annotation_mode": "exhaustive",
        "face_count": 1,
        "present_identities": ["Alice Example"],
        "context_pack": {"title": "test"},
        "base_caption": "Alice Example.",
        "must_right": ["Alice Example"],
        "easy_wrong": [],
        "policy": {"recognition_enabled": True},
        "provenance": {"source": "fixture", "license": "fixture"},
        "face_boxes": [box],
    }


def _manifest() -> dict:
    entries = []
    adjudication_records = []
    for media_id in range(1, 11):
        record_id = f"review-{media_id}"
        box = {**_box(), "adjudication_source": f"human_adjudicated:{record_id}"}
        entries.append(_entry(media_id, box))
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
    return {
        "annotation_mode": "exhaustive",
        "roster": ["Alice Example"],
        "entries": entries,
        "adjudication_records": adjudication_records,
    }


def _run_record() -> dict:
    success = {
        "media_id": 1,
        "path": "mock_images/1.jpg",
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
    errors = [
        {
            "media_id": media_id,
            "path": f"mock_images/{media_id}.jpg",
            "error": "decoder failed",
        }
        for media_id in range(2, 11)
    ]
    return {
        "schema": "acx-eval/v1",
        "kind": "face_run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "head_sha": "0" * 40,
            "started_at": "2026-08-14T00:00:00Z",
            "leg": "candidate",
        },
        "items": [success, *errors],
    }


def test_error_items_count_as_detection_and_full_corpus_identification_misses() -> None:
    report = score_face_run_record(_run_record(), _manifest())

    assert report["detection"]["tp"] == 1
    assert report["detection"]["fn"] == 9
    assert report["detection"]["recall"] == 0.1

    full_corpus_identification = report["slices"]["full_corpus_identification"]
    assert full_corpus_identification["missed_gt"] == 9
    assert full_corpus_identification["fn"] == 9
    assert len(report["failures"]) == 9

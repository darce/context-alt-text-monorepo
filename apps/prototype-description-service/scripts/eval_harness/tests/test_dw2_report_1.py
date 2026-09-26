from __future__ import annotations

import pytest

from scripts.eval_harness.manifest import ManifestError, ScoreInvariant
from scripts.eval_harness.report import score_run_record


def test_exhaustive_detection_uses_ratified_run_manifest_threshold() -> None:
    run_record = {
        "schema": "acx-eval/v1",
        "kind": "run_record",
        "provenance": {
            "manifest_sha256": "m" * 64,
            "base_url": "https://api.example.com",
            "head_sha": "0" * 40,
            "started_at": "2026-07-06T00:00:00Z",
        },
        "items": [
            {
                "media_id": 1,
                "path": "mock_images/empty.jpg",
                "describe": {
                    "alt_text_draft": "An empty scene.",
                    "visual_facts": {"objects": []},
                    "adapter": "seeded",
                    "model_id": "seeded-fixtures",
                    "model_version": "1",
                    "cached": False,
                },
                "identities": [],
                "face_count": 0,
                "error": None,
            }
        ],
    }
    entries = [
        {
            "path": "mock_images/empty.jpg",
            "media_id": 1,
            "face_count": 0,
            "present_identities": [],
            "must_right": [],
            "easy_wrong": [],
            "policy": {"recognition_enabled": True},
            "face_boxes": [],
            "annotation_mode": "exhaustive",
        }
    ]

    with pytest.raises(ManifestError) as exc_info:
        score_run_record(
            run_record,
            entries,
            run_manifest={"iou_threshold": 0.0},
        )

    assert exc_info.value.invariant == ScoreInvariant.DETECTION_REQUIRES_RATIFIED_IOU_THRESHOLD

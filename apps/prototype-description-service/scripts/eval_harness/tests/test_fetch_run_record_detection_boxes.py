from __future__ import annotations

import json
from typing import Any

from PIL import Image

from scripts.eval_harness.cli import fetch_run_record
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import score_run_record
from scripts.eval_harness.tests.test_cli_exit_gates import _manifest_doc, _named_box


class _FetchClient:
    base_url = "https://api.example.com"

    def describe(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "alt_text_draft": "Alice Example stands near a garden.",
            "visual_facts": {"objects": ["garden"]},
            "adapter": "seeded",
            "model_id": "seeded-fixtures",
            "model_version": "1",
            "cached": False,
        }

    def analyze(self, _items: list[tuple[int, str, bytes]]) -> str:
        return "job-1"

    def wait_job(self, _job_id: str) -> None:
        return None

    def media_identities(self, media_ids: list[int]) -> list[dict[str, Any]]:
        assert media_ids == [1]
        return [
            {
                "media_id": 1,
                "cluster_label": "Alice Example",
                "is_auto_label": False,
                "bbox": {"x": 40, "y": 25, "width": 20, "height": 30},
            },
            {
                "media_id": 1,
                "cluster_label": None,
                "is_auto_label": True,
                "bbox": {"x": 60, "y": 25, "width": 25, "height": 30},
            },
        ]


def test_fetch_run_record_keeps_detection_box_for_unrecognized_face(tmp_path) -> None:
    expected_boxes = [
        {"x": 40, "y": 25, "width": 20, "height": 30},
        {"x": 60, "y": 25, "width": 25, "height": 30},
    ]
    manifest_doc = _manifest_doc(
        mode="exhaustive",
        boxed=True,
        face_boxes_by_image=[
            [
                _named_box("Alice Example", x=0.5, y=0.4, w=0.2, h=0.3),
                _named_box(None, x=0.725, y=0.4, w=0.25, h=0.3),
            ]
        ],
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_doc), encoding="utf-8")
    manifest = load_manifest(str(manifest_path), skip_hash_verification=True)

    image_path = tmp_path / "mock_images" / "alice1.jpg"
    image_path.parent.mkdir()
    Image.new("RGB", (100, 100), color="white").save(image_path, format="JPEG")

    record = fetch_run_record(
        manifest,
        str(tmp_path),
        _FetchClient(),
        head_sha="0" * 40,
    )

    item = record["items"][0]
    assert item["face_count"] == 2
    assert len(item["identities"]) == 1
    assert item["identities"][0]["name"] == "Alice Example"
    assert item["detection_boxes"] == expected_boxes

    score_entries = [
        {**entry, "annotation_mode": manifest_doc["annotation_mode"]}
        for entry in manifest_doc["entries"]
    ]
    scored = score_run_record(
        record,
        score_entries,
        annotation_mode=manifest_doc["annotation_mode"],
        run_manifest=manifest_doc,
    )
    detection = scored["faces"]["detection"]
    assert detection.get("refused") is not True
    assert detection["tp"] == 2
    assert detection["fp"] == 0
    assert detection["fn"] == 0

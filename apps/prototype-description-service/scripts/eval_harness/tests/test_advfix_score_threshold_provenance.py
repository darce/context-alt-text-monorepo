"""Regression coverage for detector score-threshold run provenance."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from scripts.eval_harness import cli
from scripts.eval_harness.manifest import GoldenManifest
from scripts.eval_harness.report import score_face_run_record


class _ThresholdDetector:
    def __init__(self, score_threshold: float) -> None:
        self.score_threshold = score_threshold

    def detect(self, images: list[np.ndarray]) -> list[list[object]]:
        return [[] for _ in images]


class _EmptyEmbedder:
    embedding_dim = 8


@pytest.mark.parametrize("score_threshold", [0.6, 0.9])
def test_face_bakeoff_persists_effective_score_threshold_in_scored_provenance(
    tmp_path, monkeypatch, score_threshold: float
) -> None:
    image = np.zeros((16, 16, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "empty.jpg").write_bytes(encoded.tobytes())

    manifest = GoldenManifest.model_validate(
        {
            "manifest_version": 3,
            "annotation_mode": "exhaustive",
            "roster": ["Alice Example"],
            "entries": [
                {
                    "path": "empty.jpg",
                    "sha256": "a" * 64,
                    "media_id": 1,
                    "face_count": 0,
                    "present_identities": [],
                    "must_right": [],
                    "easy_wrong": [],
                    "policy": {"recognition_enabled": True},
                    "provenance": {"source": "fixture", "license": "fixture"},
                }
            ],
        }
    )
    detector = _ThresholdDetector(score_threshold)
    monkeypatch.setattr(
        cli,
        "build_candidate_leg",
        lambda **_kwargs: (detector, object(), _EmptyEmbedder()),
    )
    monkeypatch.setattr(cli, "load_manifest", lambda *_args, **_kwargs: manifest)
    monkeypatch.setattr(
        cli,
        "build_occlusion_twin_pairs",
        lambda *_args, **_kwargs: ({}, {"n_pairs": 0, "errors": []}),
    )
    monkeypatch.setattr(cli, "_head_sha", lambda: "a" * 40)
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path / "out")
    monkeypatch.setenv("GOLDEN_IMAGES_DIR", str(images_dir))

    cli.main(
        [
            "face-bakeoff",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--score-threshold",
            str(score_threshold),
        ]
    )

    record_path = next((tmp_path / "out").glob("face-run-*.json"))
    record = json.loads(record_path.read_text())
    assert record["provenance"]["detector_score_threshold"] == score_threshold

    scored = score_face_run_record(record, manifest, score_manifest_sha256="a" * 64)
    assert scored["provenance"]["detector_score_threshold"] == score_threshold

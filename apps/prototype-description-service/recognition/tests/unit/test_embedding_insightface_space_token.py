"""CVUP1-GR-03: InsightFace incumbent model_id includes the OpenCV space token."""

from __future__ import annotations

import cv2

from recognition.application.embedding.manifest import incumbent_embedding_model_manifest


def test_incumbent_model_id_includes_opencv_space_token() -> None:
    manifest = incumbent_embedding_model_manifest()

    assert f"+cv{cv2.__version__}@" in manifest.model_id
    assert manifest.model_id.startswith("insightface-")
    assert manifest.name.endswith(f"+cv{cv2.__version__}")


def test_incumbent_model_id_partitions_on_opencv_version(monkeypatch) -> None:
    import recognition.application.embedding.manifest as manifest_mod

    monkeypatch.setattr(cv2, "__version__", "4.13.0")
    first = manifest_mod.incumbent_embedding_model_manifest().model_id
    monkeypatch.setattr(cv2, "__version__", "5.0.0")
    second = manifest_mod.incumbent_embedding_model_manifest().model_id

    assert first != second
    assert "+cv4.13.0@" in first
    assert "+cv5.0.0@" in second

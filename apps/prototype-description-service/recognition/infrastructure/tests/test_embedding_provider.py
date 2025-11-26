import asyncio
import sys
import types

import numpy as np
import pytest
from PIL import Image

from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider


def _make_normalized_embedding() -> np.ndarray:
    """Create a unit-normalized 512D embedding (like InsightFace produces)."""
    raw = np.ones(512, dtype=np.float32)
    return raw / np.linalg.norm(raw)


class DummyFace:
    def __init__(self) -> None:
        self.bbox = np.array([10, 12, 64, 80], dtype=int)
        self.det_score = 0.95
        # InsightFace produces L2-normalized embeddings
        self.normed_embedding = _make_normalized_embedding()
        self.kps = np.zeros((5, 2), dtype=np.float32)
        self.age = 32.0
        self.gender = 0.4


class DummyFaceAnalysis:
    def __init__(self, *args, **kwargs):
        self._prepared = False

    def prepare(self, *args, **kwargs) -> None:
        self._prepared = True

    def get(self, image):
        return [DummyFace()]


@pytest.fixture(autouse=True)
def fake_insightface(monkeypatch):
    module = types.ModuleType("insightface")
    app_module = types.ModuleType("insightface.app")
    app_module.FaceAnalysis = DummyFaceAnalysis  # type: ignore[attr-defined]
    module.app = app_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "insightface", module)
    monkeypatch.setitem(sys.modules, "insightface.app", app_module)
    yield


def test_analyze_returns_composite_embedding():
    provider = FaceEmbeddingProvider()
    image = Image.new("RGB", (128, 128))
    embeddings = asyncio.run(provider.analyze(image))

    assert len(embeddings) == 1
    vector = embeddings[0].embedding
    assert vector.shape == (1024,)
    # Face embedding is preserved in first 512 dims (already normalized by InsightFace)
    expected_face = _make_normalized_embedding()
    assert vector[:512].tolist() == pytest.approx(expected_face.tolist())
    assert np.linalg.norm(vector[512:]) > 0
    assert embeddings[0].detection.confidence == pytest.approx(0.95)

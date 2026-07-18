"""FIR-4 S5: license isolation — insightface not imported on face_pipeline paths.

Default install must load ``runtime_factory`` and ``face_pipeline_adapter`` without
pulling ``insightface`` into ``sys.modules``. Incumbent construction may import
lazily only when the insightface branch runs.

Heuristics: [SERVE-03][RLSE-08]
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def _block_insightface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove insightface and refuse any re-import for the duration of the test."""
    for key in list(sys.modules):
        if key == "insightface" or key.startswith("insightface."):
            monkeypatch.delitem(sys.modules, key, raising=False)

    real_import = __import__

    def _guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):  # noqa: ANN001
        if name == "insightface" or name.startswith("insightface."):
            raise ModuleNotFoundError(
                f"blocked insightface import for S5 isolation test: {name}",
                name=name,
            )
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _guarded_import)


def test_face_pipeline_modules_import_without_insightface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import runtime_factory + face_pipeline_adapter with insightface absent."""
    _block_insightface(monkeypatch)

    # Drop cached modules so re-import exercises the import graph under the block.
    for key in list(sys.modules):
        if key in {
            "recognition.infrastructure.embeddings.runtime_factory",
            "recognition.infrastructure.embeddings.face_pipeline_adapter",
        } or key.startswith("recognition.infrastructure.embeddings.runtime_factory"):
            monkeypatch.delitem(sys.modules, key, raising=False)
        if key.startswith("recognition.infrastructure.embeddings.face_pipeline_adapter"):
            monkeypatch.delitem(sys.modules, key, raising=False)

    rf = importlib.import_module("recognition.infrastructure.embeddings.runtime_factory")
    fpa = importlib.import_module("recognition.infrastructure.embeddings.face_pipeline_adapter")

    assert isinstance(rf, ModuleType)
    assert isinstance(fpa, ModuleType)
    assert callable(rf.build_embedding_runtime)
    assert hasattr(fpa, "FacePipelineFaceDetector")
    assert "insightface" not in sys.modules
    assert not any(k.startswith("insightface.") for k in sys.modules)


@pytest.mark.asyncio
async def test_face_pipeline_factory_branch_without_insightface(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Selecting face_pipeline must not require insightface to be importable."""
    from pathlib import Path
    from types import SimpleNamespace

    from recognition.application.embedding.detector import UnavailableFaceDetector
    from recognition.application.embedding.generator import UnavailableEmbeddingGenerator
    from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
    from recognition.infrastructure.embeddings import runtime_factory as rf

    _block_insightface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    # Empty models dir → fail-closed Unavailable* without ever touching insightface.
    settings = SimpleNamespace(
        runtime_mode="production",
        face_pipeline=SimpleNamespace(
            profile="face_pipeline",
            resolved_models_dir=Path(tmp_path),
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
            timeout_s=5.0,
        ),
        identity_detection=SimpleNamespace(embedding_dimension=128),
    )

    det, gen = await rf.build_embedding_runtime(settings=settings)
    assert isinstance(det, UnavailableFaceDetector)
    assert isinstance(gen, UnavailableEmbeddingGenerator)
    assert "insightface" not in sys.modules
    fpa.reset_shared_face_pipeline_runtime_for_tests()

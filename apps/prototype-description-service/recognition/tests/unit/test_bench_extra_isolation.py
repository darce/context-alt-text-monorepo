"""FIR-4 S5: license isolation — insightface not imported on face_pipeline paths.

Default install must load ``runtime_factory`` and ``face_pipeline_adapter`` without
pulling ``insightface`` into ``sys.modules``. Incumbent construction may import
lazily only when the insightface branch runs.

Heuristics: [SERVE-03][RLSE-08]
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
from types import ModuleType

import pytest

from recognition.tests.unit.face_pipeline_support import MODELS_PRESENT, MODELS_SKIP


class _InsightfaceBlockFinder(importlib.abc.MetaPathFinder):
    """sys.meta_path finder that refuses insightface* imports (S5CR-07)."""

    def find_spec(  # noqa: D102
        self,
        fullname: str,
        path: object = None,  # noqa: ARG002
        target: object = None,  # noqa: ARG002
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == "insightface" or fullname.startswith("insightface."):
            raise ModuleNotFoundError(
                f"blocked insightface import for S5 isolation test: {fullname}",
                name=fullname,
            )
        return None


def _block_insightface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove insightface and refuse any re-import via sys.meta_path for the test."""
    for key in list(sys.modules):
        if key == "insightface" or key.startswith("insightface."):
            monkeypatch.delitem(sys.modules, key, raising=False)

    finder = _InsightfaceBlockFinder()
    # Insert at front so we win over normal path finders.
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])


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


@pytest.mark.skipif(not MODELS_PRESENT, reason=MODELS_SKIP)
def test_face_pipeline_runtime_constructs_under_insightface_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S5CR-07: models-present success path must not import insightface."""
    from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
    from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR

    _block_insightface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    # Align dims so the three-way guard does not raise before model load.
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
    monkeypatch.setenv("PGVECTOR_DIM", "128")
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()

    runtime = fpa.get_shared_face_pipeline_runtime(
        profile="face_pipeline",
        models_dir=DEFAULT_MODELS_DIR,
    )
    assert isinstance(runtime, fpa.FacePipelineRuntime)
    assert "insightface" not in sys.modules
    assert not any(k.startswith("insightface.") for k in sys.modules)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    get_settings.cache_clear()
    get_database_settings.cache_clear()

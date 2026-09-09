"""FIR23-01: embedding_model enforcement on read paths + fail-closed readiness.

Unclustered rows fail closed to the active runtime id. All-unstamped batches
remain the legacy no-op; mixed or foreign stamps never pass through.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from recognition.application.embedding.manifest import (
    active_embedding_model_id,
    incumbent_embedding_model_manifest,
)
from recognition.application.health import check_active_embedding_model
from recognition.infrastructure.repositories.cluster_repository import (
    _choose_embedding_model,
    _filter_embedding_pairs_to_single_model,
    _filter_identity_models_to_single_embedding_model,
    _filter_rows_to_single_embedding_model,
)
from shared.health import HealthStatus


def test_active_embedding_model_id_insightface_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "production")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "insightface")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        model_id = active_embedding_model_id()
        assert model_id == incumbent_embedding_model_manifest().model_id
        assert "@" in model_id
    finally:
        get_settings.cache_clear()


def test_active_embedding_model_id_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        assert active_embedding_model_id() == "stub-detector@test"
    finally:
        get_settings.cache_clear()


def test_check_active_embedding_model_ok() -> None:
    result = check_active_embedding_model()
    assert result.name == "embedding_model"
    assert result.status is HealthStatus.OK
    assert result.detail.startswith("active_space=")


def test_check_active_embedding_model_public_detail_hides_model_id() -> None:
    """Unauthenticated /ready must not disclose the toolchain-bearing model_id.

    CVUP1-GR-15: ``space_token`` folds the resolved OpenCV and onnxruntime
    versions into ``model_id``, so echoing it on the public probe is version
    disclosure. The coarse form must still discriminate — two different active
    model_ids must not collapse to the same ``active_space``.
    """
    model_id = active_embedding_model_id()
    public = check_active_embedding_model()
    assert model_id not in public.detail

    with patch(
        "recognition.application.embedding.manifest.active_embedding_model_id",
        return_value=model_id + "-other",
    ):
        other = check_active_embedding_model()
    assert other.detail != public.detail


def test_check_active_embedding_model_verbose_keeps_model_id() -> None:
    verbose = check_active_embedding_model(verbose=True)
    assert verbose.status is HealthStatus.OK
    assert verbose.detail == f"active={active_embedding_model_id()}"


def test_check_active_embedding_model_fail_closed() -> None:
    with patch(
        "recognition.application.embedding.manifest.active_embedding_model_id",
        side_effect=RuntimeError("boom"),
    ):
        result = check_active_embedding_model()
    assert result.status is HealthStatus.UNHEALTHY
    assert "unresolved" in result.detail


def test_choose_embedding_model_majority_and_lex_tie() -> None:
    assert _choose_embedding_model(["b", "a", "b"]) == "b"
    # equal counts → lex min
    assert _choose_embedding_model(["b", "a"]) == "a"
    assert _choose_embedding_model([None, ""]) is None


def test_filter_embedding_pairs_single_model_is_noop() -> None:
    emb = np.ones(4, dtype=np.float32)
    rows = [(emb, "m1"), (emb * 2, "m1")]
    assert _filter_embedding_pairs_to_single_model(rows) == rows


def test_filter_embedding_pairs_mixed_keeps_majority() -> None:
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([0.0, 1.0], dtype=np.float32)
    rows = [(a, "keep"), (a, "keep"), (b, "drop")]
    kept = _filter_embedding_pairs_to_single_model(rows)
    assert len(kept) == 2
    assert all(model == "keep" for _, model in kept)


def test_filter_identity_models_single_model_noop() -> None:
    rows = [
        SimpleNamespace(embedding_model="m1", id="1"),
        SimpleNamespace(embedding_model="m1", id="2"),
    ]
    # helper expects MediaIdentity-like; attribute access only.
    assert _filter_identity_models_to_single_embedding_model(rows) == rows  # type: ignore[arg-type]


def test_filter_identity_models_mixed_majority() -> None:
    rows = [
        SimpleNamespace(embedding_model="keep"),
        SimpleNamespace(embedding_model="keep"),
        SimpleNamespace(embedding_model="drop"),
    ]
    kept = _filter_identity_models_to_single_embedding_model(rows)  # type: ignore[arg-type]
    assert len(kept) == 2
    assert all(r.embedding_model == "keep" for r in kept)


def test_filter_rows_unclustered_mixed_prefers_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        rows = [
            SimpleNamespace(embedding_model="stub-detector@test"),
            SimpleNamespace(embedding_model="other-model"),
            SimpleNamespace(embedding_model="other-model"),
        ]
        kept = _filter_rows_to_single_embedding_model(rows)  # type: ignore[arg-type]
        assert len(kept) == 1
        assert kept[0].embedding_model == "stub-detector@test"
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_single_foreign_model_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        rows = [
            SimpleNamespace(embedding_model="legacy-seed"),
            SimpleNamespace(embedding_model="legacy-seed"),
        ]
        assert _filter_rows_to_single_embedding_model(rows) == []  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_active_model_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        rows = [
            SimpleNamespace(embedding_model="stub-detector@test"),
            SimpleNamespace(embedding_model="stub-detector@test"),
        ]
        assert _filter_rows_to_single_embedding_model(rows) == rows  # type: ignore[arg-type]
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_unstamped_mixed_with_stamp_keeps_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "test")
    from recognition.config import get_settings

    get_settings.cache_clear()
    try:
        unstamped = SimpleNamespace(embedding_model=None)
        active = SimpleNamespace(embedding_model="stub-detector@test")
        foreign = SimpleNamespace(embedding_model="legacy-seed")
        kept = _filter_rows_to_single_embedding_model([unstamped, active, foreign])  # type: ignore[arg-type]
        assert kept == [active]
    finally:
        get_settings.cache_clear()


def test_filter_rows_unclustered_all_unstamped_is_legacy_noop() -> None:
    rows = [
        SimpleNamespace(embedding_model=None),
        SimpleNamespace(embedding_model=None),
    ]
    assert _filter_rows_to_single_embedding_model(rows) == rows  # type: ignore[arg-type]


def test_centroid_mv_sql_frames_by_embedding_model() -> None:
    """Migration MV definition must majority-frame by embedding_model (FIR23-01)."""
    from pathlib import Path

    migration = Path(__file__).resolve().parents[3] / "db" / "migrations" / "versions" / "001_identity_schema.py"
    text = migration.read_text(encoding="utf-8")
    assert "chosen_model" in text
    assert "embedding_model" in text
    assert "ORDER BY cluster_id, n DESC, embedding_model ASC" in text


def test_sqlite_refresh_sql_frames_by_embedding_model() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "infrastructure" / "repositories" / "cluster_repository.py"
    text = src.read_text(encoding="utf-8")
    assert "chosen_model" in text
    assert "FIR23-01" in text


def test_label_inference_nn_filters_embedding_model() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "application" / "suggestions" / "label_inference.py"
    text = src.read_text(encoding="utf-8")
    assert "embedding_model ==" in text or "MediaIdentity.embedding_model ==" in text
    assert "FIR23-01" in text


def test_orchestrator_fetch_filters_mixed_models() -> None:
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "application" / "orchestration" / "clustering" / "orchestrator.py"
    text = src.read_text(encoding="utf-8")
    assert "active_embedding_model_id" in text
    assert "FIR23-01" in text

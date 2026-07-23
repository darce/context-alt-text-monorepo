"""FIR23-02/03/04/05: skip counters, manifest validation, aligner, drop metrics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from prometheus_client import CollectorRegistry

from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.application.scan.capability import ScanWorkerCounters, format_capability_reason
from recognition.application.scan.service import ReconcileResult
from recognition.infrastructure.face_pipeline._common import FacePipelineInputError, ensure_bgr_u8
from recognition.infrastructure.face_pipeline.aligner import AlignmentError, FivePointAligner
from recognition.observability.face_pipeline_metrics import (
    FACE_DROP_REASON_ALIGN_EMBED,
    FACE_DROP_REASON_BBOX,
    FacePipelineMetrics,
)


def test_embedding_model_manifest_rejects_empty_framework() -> None:
    with pytest.raises(ValueError, match="framework"):
        EmbeddingModelManifest(
            framework="  ",
            name="sface",
            dimensions=128,
            normalization="l2",
            metric="cosine",
        )


def test_embedding_model_manifest_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        EmbeddingModelManifest(
            framework="opencv",
            name="sface",
            dimensions=0,
            normalization="l2",
            metric="cosine",
        )


def test_embedding_model_manifest_strips_and_accepts_valid() -> None:
    m = EmbeddingModelManifest(
        framework=" opencv ",
        name=" sface ",
        dimensions=128,
        normalization=" l2 ",
        metric=" cosine ",
    )
    assert m.framework == "opencv"
    assert m.name == "sface"
    assert m.model_id == "opencv-sface@128d/l2/cosine"


def test_aligner_delegates_float01_trap_to_ensure_bgr_u8() -> None:
    """FIR23-04: aligner uses shared coercion (same error class path as ensure_bgr_u8)."""
    aligner = FivePointAligner()
    img01 = np.zeros((64, 64, 3), dtype=np.float32)  # [0,1] trap
    landmarks = np.array(
        [[20.0, 20.0], [40.0, 20.0], [30.0, 30.0], [22.0, 45.0], [38.0, 45.0]],
        dtype=np.float64,
    )
    with pytest.raises(FacePipelineInputError):
        ensure_bgr_u8(img01, label="probe")
    with pytest.raises(AlignmentError, match="float"):
        aligner.align(img01, landmarks)


def test_aligner_uint8_path_matches_ensure_bgr_u8_shape() -> None:
    aligner = FivePointAligner()
    img = np.full((80, 80, 3), 40, dtype=np.uint8)
    landmarks = np.array(
        [[25.0, 25.0], [55.0, 25.0], [40.0, 40.0], [28.0, 55.0], [52.0, 55.0]],
        dtype=np.float64,
    )
    coerced = ensure_bgr_u8(img, label="probe")
    result = aligner.align(img, landmarks)
    assert coerced.dtype == np.uint8
    assert result.crop.shape == (112, 112, 3)
    assert result.crop.dtype == np.uint8


def test_scan_worker_counters_include_skip_and_mixed_model() -> None:
    """FIR23-02: heartbeat always surfaces skip + mixed-model zeros."""
    c = ScanWorkerCounters()
    reason = format_capability_reason(profile="insightface", counters=c)
    assert "faces_skipped=0" in reason
    assert "mixed_model_media=0" in reason

    c.record(detected=3, matched=1, new=1, skipped=1, mixed_model=True)
    assert c.faces_skipped == 1
    assert c.mixed_model_media == 1
    assert "faces_skipped=1" in c.format_suffix()
    assert "mixed_model_media=1" in c.format_suffix()


def test_reconcile_result_carries_skip_and_mixed_defaults() -> None:
    r = ReconcileResult(detected=2, matched=1, new=1)
    assert r.skipped == 0
    assert r.mixed_model is False
    assert r.total == 2


def test_face_pipeline_metrics_split_quality_drop_counters() -> None:
    """FIR23-05: quality drops metered and split by reason."""
    registry = CollectorRegistry()
    metrics = FacePipelineMetrics(registry=registry)
    metrics.record_faces_dropped(FACE_DROP_REASON_BBOX, 2)
    metrics.record_faces_dropped(FACE_DROP_REASON_ALIGN_EMBED, 1)

    samples = {
        (s.name, tuple(sorted(s.labels.items()))): s.value
        for metric in registry.collect()
        for s in metric.samples
        if s.name == "face_pipeline_faces_dropped_total"
    }
    assert samples[("face_pipeline_faces_dropped_total", (("reason", "bbox_degenerate"),))] == 2.0
    assert samples[("face_pipeline_faces_dropped_total", (("reason", "align_or_embed"),))] == 1.0


def test_hierarchical_split_filters_mixed_embedding_models() -> None:
    """FIR23-05: split never mixes embedding spaces; majority model kept."""
    from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering

    emb_a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    emb_b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    identities = [
        SimpleNamespace(id="1", embedding=emb_a, embedding_model="keep"),
        SimpleNamespace(id="2", embedding=emb_a * 0.9 + emb_b * 0.1, embedding_model="keep"),
        SimpleNamespace(id="3", embedding=emb_b, embedding_model="drop"),
        SimpleNamespace(id="4", embedding=None, embedding_model="keep"),
    ]
    hc = HierarchicalClustering(distance_threshold=0.30)
    groups = hc.split_identities(identities, n_clusters=0)  # type: ignore[arg-type]
    kept_ids = {str(i.id) for group in groups.values() for i in group}
    assert "3" not in kept_ids
    assert "4" not in kept_ids
    assert "1" in kept_ids
    assert "2" in kept_ids


def test_observe_faces_dropped_is_optional_on_partial_observer() -> None:
    """Structural observers without record_faces_dropped still work."""
    from recognition.infrastructure.embeddings.face_pipeline_adapter import _observe_faces_dropped

    class _Partial:
        def observe_submit_wait(self, wait_s: float) -> None:
            return None

        def record_admission_timeout(self) -> None:
            return None

    _observe_faces_dropped(_Partial(), reason=FACE_DROP_REASON_BBOX, count=3)  # type: ignore[arg-type]

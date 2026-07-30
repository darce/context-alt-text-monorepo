"""FIR23-01: discovery must not cosine across embedding spaces (CVUP1-GR-02)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.clustering.discovery_pipeline import (
    prepare_cluster_caches,
    run_discovery_pipeline,
)
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


def _make_settings(threshold: float = 0.5) -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=threshold,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        hdbscan_max_batch_size=None,
    )


def _make_identity(vec: np.ndarray) -> MediaIdentity:
    return MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vec,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )


def _cluster(
    cluster_id: str,
    *,
    embedding: np.ndarray,
    embedding_model: str | None,
    label: str | None = None,
    user_confirmed: bool = False,
    centroid: np.ndarray | None = None,
) -> SimpleNamespace:
    rep = SimpleNamespace(
        embedding=embedding,
        identity_id=str(generate_id()),
    )
    # Domain ClusterRepresentative has no embedding_model field; only set when
    # the test intentionally stamps provenance on the stub rep.
    if embedding_model is not None:
        rep.embedding_model = embedding_model
    return SimpleNamespace(
        id=cluster_id,
        label=label,
        user_confirmed=user_confirmed,
        representatives=[rep],
        centroid=centroid if centroid is not None else embedding,
    )


class _FakeWriter:
    def __init__(self, clusters: list[object]) -> None:
        self.cluster_repository = SimpleNamespace(
            get_by_tenant=AsyncMock(return_value=clusters),
            _session=None,
        )
        self._session = None


@pytest.mark.asyncio
async def test_prepare_cluster_caches_excludes_foreign_embedding_model() -> None:
    """Gallery cache keeps only reps in the active embedding space."""
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    vec_same = _normalize(np.array([1.0, 0.0, 0.0]))
    vec_foreign = _normalize(np.array([0.0, 1.0, 0.0]))

    clusters = [
        _cluster("c-same", embedding=vec_same, embedding_model=same_space, label="Alice", user_confirmed=True),
        _cluster("c-foreign", embedding=vec_foreign, embedding_model=foreign_space, label="Bob", user_confirmed=True),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, labeled = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert set(reps) == {"c-same"}
    assert "c-foreign" not in reps
    assert "c-foreign" not in centroids
    assert "c-same" in centroids
    assert labeled == {"c-same", "c-foreign"}


@pytest.mark.asyncio
async def test_run_discovery_produces_no_cross_space_candidates() -> None:
    """Probes must not match foreign-space cluster representatives.

    Fails against unfixed code that would cosine the probe against both
    same-space and foreign-space reps and emit a candidate for the foreign
    cluster when that garbage score clears the threshold.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    # Near-orthogonal vectors so a true same-space match is unambiguous, but
    # leave foreign rep close enough to pass a low threshold if wrongly kept.
    probe_vec = _normalize(np.array([1.0, 0.0, 0.0]))
    same_rep = _normalize(np.array([0.99, 0.01, 0.0]))
    foreign_rep = _normalize(np.array([0.95, 0.05, 0.0]))  # high cosine if compared

    clusters = [
        _cluster("c-same", embedding=same_rep, embedding_model=same_space),
        _cluster("c-foreign", embedding=foreign_rep, embedding_model=foreign_space),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, labeled = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert "c-foreign" not in reps

    settings = _make_settings(threshold=0.5)
    rep_discovery = RepresentativeDiscovery(settings=settings)
    # Centroid/graph stubs: only representative path is under test here.
    centroid_discovery = SimpleNamespace(discover=AsyncMock(return_value=[]))
    graph_discovery = SimpleNamespace(discover=AsyncMock(return_value=SimpleNamespace(candidates=[], new_clusters=[])))

    probe = _make_identity(probe_vec)
    candidates, _ = await run_discovery_pipeline(
        chunk=[probe],
        representative_discovery=rep_discovery,
        centroid_discovery=centroid_discovery,  # type: ignore[arg-type]
        graph_discovery=graph_discovery,  # type: ignore[arg-type]
        representatives_by_cluster=reps,
        centroids_by_cluster=centroids,
        labeled_cluster_ids=labeled,
    )

    assert all(c.cluster_id != "c-foreign" for c in candidates)
    assert any(c.cluster_id == "c-same" for c in candidates)


@pytest.mark.asyncio
async def test_prepare_cluster_caches_single_model_is_noop() -> None:
    """When every rep shares one model matching active, all stay (FIR23 no-op)."""
    model = "buffalo_l@insightface"
    clusters = [
        _cluster("c1", embedding=_normalize(np.array([1.0, 0.0])), embedding_model=model),
        _cluster("c2", embedding=_normalize(np.array([0.0, 1.0])), embedding_model=model),
    ]
    writer = _FakeWriter(clusters)

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=model,
    ):
        reps, centroids, _ = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert set(reps) == {"c1", "c2"}
    assert set(centroids) == {"c1", "c2"}


@pytest.mark.asyncio
async def test_prepare_cluster_caches_excludes_unresolvable_when_provenance_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CVUP1-GR-21: unresolvable reps must not silently enter the gallery.

    Domain representatives drop embedding_model. When target_model is known but
    provenance cannot be loaded (no session / empty map), the pre-fix path kept
    every rep and discovery resumed cosining across spaces with no operator
    signal. Fail closed: exclude the rep, drop its centroid, and warn.
    """
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))

    # Domain-like: no embedding_model on the rep (None → attribute omitted).
    clusters = [
        _cluster(
            "c-unresolved",
            embedding=vec,
            embedding_model=None,
            label="Mystery",
            user_confirmed=True,
        ),
    ]
    writer = _FakeWriter(clusters)

    with (
        patch(
            "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
            return_value=same_space,
        ),
        caplog.at_level(logging.WARNING),
    ):
        reps, centroids, labeled = await prepare_cluster_caches(writer, tenant_id=str(generate_id()))

    assert "c-unresolved" not in reps
    assert "c-unresolved" not in centroids
    # Labeled-status tracking is independent of gallery admission.
    assert labeled == {"c-unresolved"}
    assert any("provenance unavailable" in record.message and "excluded" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_prepare_cluster_caches_uses_explicit_session_for_provenance() -> None:
    """Explicit session param is preferred over private _session probing."""
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    foreign_space = "opencv-sface@128d/l2/cosine"
    vec_same = _normalize(np.array([1.0, 0.0, 0.0]))
    vec_foreign = _normalize(np.array([0.0, 1.0, 0.0]))

    same_id = str(generate_id())
    foreign_id = str(generate_id())

    # Domain-like reps: resolve via session-backed provenance map only.
    rep_same = SimpleNamespace(embedding=vec_same, identity_id=same_id)
    rep_foreign = SimpleNamespace(embedding=vec_foreign, identity_id=foreign_id)
    clusters = [
        SimpleNamespace(
            id="c-same",
            label="Alice",
            user_confirmed=True,
            representatives=[rep_same],
            centroid=vec_same,
        ),
        SimpleNamespace(
            id="c-foreign",
            label="Bob",
            user_confirmed=True,
            representatives=[rep_foreign],
            centroid=vec_foreign,
        ),
    ]
    writer = _FakeWriter(clusters)

    class _Rows:
        def all(self):
            return [(same_id, same_space), (foreign_id, foreign_space)]

    session = SimpleNamespace(execute=AsyncMock(return_value=_Rows()))

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, _ = await prepare_cluster_caches(
            writer,
            tenant_id=str(generate_id()),
            session=session,
        )

    assert set(reps) == {"c-same"}
    assert "c-foreign" not in reps
    assert "c-foreign" not in centroids
    session.execute.assert_awaited()

"""SVCSRC-R-01: all-unstamped gallery must fail closed before discovery mints clusters."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest

from recognition.application.discovery.representative import RepresentativeDiscovery
from recognition.application.orchestration.clustering.discovery_pipeline import (
    GalleryProvenanceUnavailableError,
    prepare_cluster_caches,
    run_discovery_pipeline,
)
from recognition.application.orchestration.clustering.orchestrator import IncrementalClusteringRunner
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id


def _normalize(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    return arr / float(np.linalg.norm(arr))


class _FakeWriter:
    def __init__(self, clusters: list[object]) -> None:
        self.cluster_repository = SimpleNamespace(
            get_by_tenant=AsyncMock(return_value=clusters),
            _session=None,
        )
        self._session = None


@pytest.mark.asyncio
async def test_all_unstamped_tenant_aborts_instead_of_minting_new_clusters() -> None:
    """prepare_cluster_caches + discovery: unstamped wipe must abort, not split identities."""
    same_space = "opencv-sface+cv5@128d/l2/cosine"
    vec = _normalize(np.array([1.0, 0.0, 0.0]))
    rep = SimpleNamespace(embedding=vec, identity_id=str(generate_id()))
    clusters = [
        SimpleNamespace(
            id="c-legacy",
            label="LegacyAlice",
            user_confirmed=True,
            representatives=[rep],
            centroid=vec,
        ),
    ]
    writer = _FakeWriter(clusters)

    class _EmptyRows:
        def all(self):
            return []

    session = SimpleNamespace(execute=AsyncMock(return_value=_EmptyRows()))

    with patch(
        "recognition.application.orchestration.clustering.discovery_pipeline._resolve_probe_embedding_model",
        return_value=same_space,
    ):
        reps, centroids, labeled, stats = await prepare_cluster_caches(
            writer,
            tenant_id=str(generate_id()),
            session=session,
        )

    assert stats.provenance_loaded is True
    assert stats.gallery_wiped is True
    assert stats.representatives_excluded_unresolvable == 1
    assert reps == {}
    assert centroids == {}
    reason = stats.abort_reason()
    assert reason is not None
    assert "legacy unstamped gallery excluded" in reason

    remaining: list[MediaIdentity] = []

    async def _graph_discover(chunk: list[MediaIdentity], _anchors: object) -> SimpleNamespace:
        remaining.extend(chunk)
        proposals = [(chunk, [1.0] * len(chunk))] if chunk else []
        return SimpleNamespace(candidates=[], new_clusters=proposals)

    probe = MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vec,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )
    candidates, new_clusters = await run_discovery_pipeline(
        chunk=[probe],
        representative_discovery=RepresentativeDiscovery(
            settings=ClusteringSettings(similarity_threshold=0.5)
        ),
        centroid_discovery=SimpleNamespace(discover=AsyncMock(return_value=[])),
        graph_discovery=SimpleNamespace(discover=_graph_discover),
        representatives_by_cluster=reps,
        centroids_by_cluster=centroids,
        labeled_cluster_ids=labeled,
    )

    assert candidates == []
    assert remaining
    assert new_clusters

    with pytest.raises(GalleryProvenanceUnavailableError, match="legacy unstamped gallery excluded"):
        IncrementalClusteringRunner._abort_on_unprovenanced_gallery("job-unstamped", stats)

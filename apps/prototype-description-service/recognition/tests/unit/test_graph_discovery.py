"""Tests for GraphDiscovery candidate generation with anchor matching."""

from __future__ import annotations

import numpy as np
import pytest

import recognition.application.discovery.graph as graph_module
from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.discovery.graph import GraphAlgorithm, GraphDiscovery
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.shared.ids import generate_id
from recognition.shared.similarity import FACE_EMBEDDING_DIM


class FakeGraphAlgorithm(GraphAlgorithm):
    """Graph algorithm that returns a fixed label set."""

    def __init__(self, labels: list[int]) -> None:
        self._labels = labels
        self.seen_embeddings: list[np.ndarray] | None = None
        self.seen_identities: list[MediaIdentity] | None = None

    def cluster(self, embeddings, identities=None):
        self.seen_embeddings = list(embeddings)
        self.seen_identities = list(identities or [])
        if len(embeddings) != len(self._labels):
            raise ValueError("Label count does not match embedding count")
        return self._labels


def make_settings(threshold: float = 0.8, hdbscan_max_batch_size: int | None = None) -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=threshold,
        complete_link_min_floor=0.75,
        complete_link_avg_threshold=0.85,
        min_representatives_for_maturity=2,
        member_validation_min_floor=0.8,
        member_validation_avg_threshold=0.85,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=5,
        hdbscan_max_batch_size=hdbscan_max_batch_size,
    )


def make_identity(vec: np.ndarray) -> MediaIdentity:
    return MediaIdentity(
        id=str(generate_id()),
        tenant_id=str(generate_id()),
        media_id=str(generate_id()),
        embedding=vec,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )


def normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec.astype(np.float32) / norm


@pytest.mark.asyncio
async def test_graph_discovery_matches_to_anchor_clusters() -> None:
    """Should create candidates for clusters matched via anchor embeddings."""
    cluster_a = str(generate_id())
    cluster_b = str(generate_id())
    identities = [
        make_identity(normalize(np.array([1.0, 0.0, 0.0]))),
        make_identity(normalize(np.array([0.9, 0.1, 0.0]))),
        make_identity(normalize(np.array([0.0, 1.0, 0.0]))),
    ]
    labels = [0, 0, 1]
    anchor_embeddings: dict[str, list[np.ndarray]] = {
        cluster_a: [normalize(np.array([1.0, 0.0, 0.0]))],
        cluster_b: [normalize(np.array([0.0, 1.0, 0.0]))],
    }

    discovery = GraphDiscovery(settings=make_settings(threshold=0.8), algorithm=FakeGraphAlgorithm(labels))
    result = await discovery.discover(identities, anchor_embeddings)
    candidates = result.candidates

    assert len(candidates) == 3
    assert {c.cluster_id for c in candidates} == {cluster_a, cluster_b}
    assert all(c.discovery_method is DiscoveryMethod.GRAPH for c in candidates)
    assert all(c.discovery_similarity >= 0.8 for c in candidates)


@pytest.mark.asyncio
async def test_graph_discovery_uses_face_embeddings() -> None:
    """GraphDiscovery should send face-only embeddings to the graph algorithm."""
    face = np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)
    meta = np.arange(FACE_EMBEDDING_DIM, dtype=np.float32) * 10.0
    identities = [
        make_identity(np.concatenate([face, meta])),
        make_identity(np.concatenate([face * 0.5, meta * 0.5])),
    ]

    labels = [0, 0]
    algo = FakeGraphAlgorithm(labels)
    anchor_embeddings: dict[str, list[np.ndarray]] = {"anchor": [face]}

    discovery = GraphDiscovery(settings=make_settings(threshold=0.8), algorithm=algo)
    result = await discovery.discover(identities, anchor_embeddings)
    candidates = result.candidates

    assert algo.seen_embeddings is not None
    assert all(len(vec) == FACE_EMBEDDING_DIM for vec in algo.seen_embeddings)
    assert candidates
    assert all(c.identity_vector.shape[0] == FACE_EMBEDDING_DIM for c in candidates)


@pytest.mark.asyncio
async def test_graph_discovery_selects_algorithm(monkeypatch) -> None:
    """Auto-select HDBSCAN for small batches and CW for large batches."""
    calls: list[str] = []

    class StubAlgorithm(GraphAlgorithm):
        def __init__(self, name: str) -> None:
            calls.append(name)

        def cluster(self, embeddings, identities=None):
            return [0 for _ in embeddings]

    import recognition.infrastructure.clustering as clustering_module

    monkeypatch.setattr(graph_module.GraphDiscovery, "_hdbscan_available", staticmethod(lambda: True))
    monkeypatch.setattr(clustering_module, "HdbscanGraphAlgorithm", lambda **_: StubAlgorithm("hdbscan"))
    monkeypatch.setattr(clustering_module, "DeterministicChineseWhispers", lambda threshold=None: StubAlgorithm("cw"))

    settings = make_settings(threshold=0.8, hdbscan_max_batch_size=3)
    discovery = graph_module.GraphDiscovery(settings=settings, algorithm=None)
    anchor_embeddings: dict[str, list[np.ndarray]] = {"anchor": [np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)]}

    small_batch = [make_identity(np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)) for _ in range(3)]
    large_batch = [make_identity(np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)) for _ in range(4)]

    await discovery.discover(small_batch, anchor_embeddings)
    await discovery.discover(large_batch, anchor_embeddings)

    assert calls == ["hdbscan", "cw"]


@pytest.mark.asyncio
async def test_graph_discovery_returns_new_clusters_when_no_anchor_match() -> None:
    """Unmatched graph clusters should surface as new clusters."""
    identities = [
        make_identity(normalize(np.array([1.0, 0.0, 0.0]))),
        make_identity(normalize(np.array([0.9, 0.1, 0.0]))),
    ]
    labels = [0, 0]
    discovery = GraphDiscovery(settings=make_settings(threshold=0.8), algorithm=FakeGraphAlgorithm(labels))

    result = await discovery.discover(identities, anchor_embeddings={})

    assert result.candidates == []
    assert len(result.new_clusters) == 1
    members, sims = result.new_clusters[0]
    assert members == identities
    assert len(sims) == len(members)
    assert all(sim > 0 for sim in sims)

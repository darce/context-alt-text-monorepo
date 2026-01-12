"""Tests for GraphDiscovery candidate generation with anchor matching."""

from __future__ import annotations

import numpy as np
import pytest

import recognition.application.discovery.graph as graph_module
import recognition.application.discovery.graph.selection as graph_selection
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


def make_settings(
    threshold: float = 0.8, hdbscan_max_batch_size: int | None = None, anchor_discovery_threshold: float = 0.6
) -> ClusteringSettings:
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
        anchor_discovery_threshold=anchor_discovery_threshold,
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
    result = await discovery.discover(identities, anchor_embeddings, inject_anchors=False)
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
    result = await discovery.discover(identities, anchor_embeddings, inject_anchors=False)
    candidates = result.candidates

    assert algo.seen_embeddings is not None
    assert all(len(vec) == FACE_EMBEDDING_DIM for vec in algo.seen_embeddings)
    assert candidates
    assert all(c.identity_vector.shape[0] == FACE_EMBEDDING_DIM for c in candidates)


@pytest.mark.asyncio
async def test_graph_discovery_selects_hdbscan(monkeypatch) -> None:
    """HDBSCAN is always selected when available."""
    calls: list[str] = []

    class StubAlgorithm(GraphAlgorithm):
        def __init__(self, name: str) -> None:
            calls.append(name)

        def cluster(self, embeddings, identities=None):
            return [0 for _ in embeddings]

    import recognition.infrastructure.clustering as clustering_module

    monkeypatch.setattr(graph_selection, "hdbscan_available", lambda: True)
    monkeypatch.setattr(clustering_module, "HdbscanGraphAlgorithm", lambda **_: StubAlgorithm("hdbscan"))

    settings = make_settings(threshold=0.8, hdbscan_max_batch_size=3)
    discovery = graph_module.GraphDiscovery(settings=settings, algorithm=None)
    anchor_embeddings: dict[str, list[np.ndarray]] = {"anchor": [np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)]}

    small_batch = [make_identity(np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)) for _ in range(3)]
    large_batch = [make_identity(np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)) for _ in range(10)]

    await discovery.discover(small_batch, anchor_embeddings, inject_anchors=False)
    await discovery.discover(large_batch, anchor_embeddings, inject_anchors=False)

    # HDBSCAN is always used regardless of batch size (Chinese Whispers removed)
    assert calls == ["hdbscan", "hdbscan"]


@pytest.mark.asyncio
async def test_graph_discovery_returns_new_clusters_when_no_anchor_match() -> None:
    """Unmatched graph clusters should surface as new clusters."""
    identities = [
        make_identity(normalize(np.array([1.0, 0.0, 0.0]))),
        make_identity(normalize(np.array([0.9, 0.1, 0.0]))),
    ]
    labels = [0, 0]
    discovery = GraphDiscovery(settings=make_settings(threshold=0.8), algorithm=FakeGraphAlgorithm(labels))

    result = await discovery.discover(identities, anchor_embeddings={}, inject_anchors=False)

    assert result.candidates == []
    assert len(result.new_clusters) == 1
    members, sims = result.new_clusters[0]
    assert members == identities
    assert len(sims) == len(members)
    assert all(sim > 0 for sim in sims)


@pytest.mark.asyncio
async def test_graph_discovery_matches_via_anchor_injection() -> None:
    """Should match new identity to anchor cluster if they end up in same graph component."""
    # Setup: Anchor and Identity are linked in the graph
    cluster_id = "existing-cluster-1"

    # New identity to cluster
    identity = make_identity(normalize(np.array([1.0, 0.0, 0.0])))

    # Existing anchor for the cluster
    # Must be similar enough to pass the threshold check in the end
    anchor_vec = normalize(np.array([0.9, 0.1, 0.0]))
    anchor_embeddings = {cluster_id: [anchor_vec]}

    # Fake algo: returns label 0 for both nodes (identity and anchor)
    # The discovery order is [identity, anchor], so we return [0, 0]
    discovery = GraphDiscovery(settings=make_settings(threshold=0.8), algorithm=FakeGraphAlgorithm([0, 0]))

    # Act: Discover with anchor injection (default)
    result = await discovery.discover([identity], anchor_embeddings, inject_anchors=True)

    # Assert: Candidate generated for the new identity pointing to the existing cluster
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.identity.id == identity.id
    assert candidate.cluster_id == cluster_id
    assert candidate.discovery_method is DiscoveryMethod.GRAPH
    assert candidate.discovery_similarity > 0.8


@pytest.mark.asyncio
async def test_graph_discovery_uses_relaxed_threshold_for_anchor_groups() -> None:
    """Anchor-linked groups should use anchor_discovery_threshold (0.60) not similarity_threshold (0.85)."""
    cluster_id = "existing-cluster"

    # New identity with only ~0.65 similarity to anchor (would fail 0.85 threshold)
    # Dot product of normalized [0.85, 0.55, 0] and [1.0, 0, 0] ≈ 0.84
    identity_vec = normalize(np.array([0.85, 0.55, 0.0]))
    identity = make_identity(identity_vec)

    # Anchor embedding
    anchor_vec = normalize(np.array([1.0, 0.0, 0.0]))
    anchor_embeddings = {cluster_id: [anchor_vec]}

    # Algo forces them into same label (simulating graph transitivity working)
    # The avg similarity between identity and anchor = 0.84 ≈ ~0.84
    # With strict threshold 0.85 this would fail. With anchor threshold 0.60 it passes.
    settings = make_settings(threshold=0.85, anchor_discovery_threshold=0.60)

    # [0, 0] means identity (index 0) and anchor (index 1) are in same component
    discovery = GraphDiscovery(settings=settings, algorithm=FakeGraphAlgorithm([0, 0]))
    result = await discovery.discover([identity], anchor_embeddings, inject_anchors=True)

    # Should emit candidate because anchor threshold (0.60) is used, not 0.85
    assert len(result.candidates) == 1
    assert result.candidates[0].cluster_id == cluster_id
    assert result.candidates[0].discovery_similarity >= 0.60


@pytest.mark.asyncio
async def test_graph_discovery_uses_strict_threshold_without_anchors() -> None:
    """Non-anchor groups should still use the strict similarity_threshold (0.85)."""
    cluster_id = "existing-cluster"

    # Two identities that cluster together but anchor doesn't link with them
    identity1 = make_identity(normalize(np.array([1.0, 0.0, 0.0])))
    identity2 = make_identity(normalize(np.array([0.95, 0.31, 0.0])))  # High sim to identity1

    # Anchor is in a different direction (won't end up in same component with threshold logic)
    anchor_vec = normalize(np.array([0.0, 0.0, 1.0]))
    anchor_embeddings = {cluster_id: [anchor_vec]}

    # Labels: identity1=0, identity2=0, anchor=1 (anchor in different component)
    settings = make_settings(threshold=0.85, anchor_discovery_threshold=0.60)
    discovery = GraphDiscovery(settings=settings, algorithm=FakeGraphAlgorithm([0, 0, 1]))
    result = await discovery.discover([identity1, identity2], anchor_embeddings, inject_anchors=True)

    # No anchor in component 0, so fallback matching uses strict threshold
    # Identities form new cluster since they don't match anchor at 0.85
    assert len(result.candidates) == 0
    assert len(result.new_clusters) == 1
    assert len(result.new_clusters[0][0]) == 2  # Both identities in new cluster

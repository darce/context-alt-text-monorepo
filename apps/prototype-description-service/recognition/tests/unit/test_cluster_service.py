"""Integration-style tests for ClusterService orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pytest

from recognition.application.assignment import (
    AssignmentCandidate,
    AssignmentDecision,
    AssignmentGate,
    AssignmentOutcome,
    DiscoveryMethod,
)
from recognition.application.discovery import CentroidDiscovery, GraphDiscovery, RepresentativeDiscovery
from recognition.application.discovery.graph import GraphDiscoveryResult
from recognition.application.orchestration import ClusterService
from recognition.application.persistence.assignment_writer import AssignmentWriter
from recognition.application.settings import ClusteringSettings
from recognition.domain.identity import MediaIdentity
from recognition.observability import ClusteringLogger, DecisionType
from recognition.shared.ids import generate_id


def make_settings() -> ClusteringSettings:
    return ClusteringSettings(
        similarity_threshold=0.7,
        complete_link_min_floor=0.7,
        complete_link_avg_threshold=0.8,
        min_representatives_for_maturity=1,
        member_validation_min_floor=0.7,
        member_validation_avg_threshold=0.8,
        early_stage_suggestion_enabled=True,
        early_stage_high_confidence_threshold=0.9,
        adaptive_threshold_maturity_point=1,
        hdbscan_max_batch_size=None,
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


class GateStub(AssignmentGate):
    """AssignmentGate stub that returns preset decisions."""

    def __init__(self, decisions: list[AssignmentOutcome]) -> None:
        self.decisions = decisions
        self.seen: list[AssignmentCandidate] = []

    async def evaluate(self, candidate: AssignmentCandidate) -> AssignmentDecision:
        outcome = self.decisions.pop(0)
        self.seen.append(candidate)
        return AssignmentDecision(
            outcome=outcome,
            candidate=candidate,
            checks_passed=[],
            checks_failed=[],
        )


class WriterStub(AssignmentWriter):
    def __init__(self) -> None:
        self.assigned: list[AssignmentDecision] = []
        self.created_clusters: list[tuple[str, list[MediaIdentity], list[float], str]] = []
        self.refresh_called = False

    async def persist_assignment(self, decision: AssignmentDecision) -> None:
        self.assigned.append(decision)

    async def persist_new_cluster(self, tenant_id: str, identities, similarities, algorithm="graph"):
        self.created_clusters.append((tenant_id, list(identities), list(similarities), algorithm))

    async def update_cluster_metadata(
        self, cluster_id: str, label: str | None = None, representative_id: str | None = None
    ):
        raise NotImplementedError

    async def refresh_centroids_view(self) -> None:
        self.refresh_called = True


class SuggestionStub:
    def __init__(self) -> None:
        self.created: list[tuple[AssignmentCandidate, float | None]] = []

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> None:
        self.created.append((candidate, confidence))


class LoggerStub(ClusteringLogger):
    def __init__(self) -> None:
        super().__init__()
        self.logged: list[tuple] = []

    def log_decision(
        self,
        identity_id,
        cluster_id,
        decision,
        similarity=None,
        reason=None,
        metadata=None,
        algorithm=None,
        job_id=None,
        timestamp=None,
        media_id=None,
    ):
        self.logged.append((identity_id, cluster_id, decision, similarity, reason, metadata, algorithm, job_id))
        return super().log_decision(
            identity_id,
            cluster_id,
            decision,
            similarity,
            reason,
            metadata,
            algorithm=algorithm,
            job_id=job_id,
            timestamp=timestamp,
            media_id=media_id,
        )

    def log_batch_start(self, identity_count, algorithm, tenant_id=None):
        return None

    def log_batch_complete(self, report):
        return None


class SessionStub:
    """Minimal async session stub to verify transaction boundaries."""

    def __init__(self) -> None:
        self.begin_called = False
        self.closed = False
        self.execute_called = False
        self.committed = False
        self.rolled_back = False

    class _Tx:
        def __init__(self, parent: SessionStub) -> None:
            self.parent = parent

        async def __aenter__(self):
            self.parent.begin_called = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def begin(self):
        return self._Tx(self)

    async def execute(self, _stmt):
        self.execute_called = True

        class Result:
            def scalars(self):
                return self

            def all(self):
                return []

        return Result()

    def add(self, _obj):
        return None

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_cluster_unclustered_identities_fetches_existing_clusters(monkeypatch) -> None:
    """cluster_unclustered_identities should fetch existing clusters for discovery inputs."""
    settings = make_settings()
    gate = GateStub([AssignmentOutcome.ACCEPT])
    writer = WriterStub()
    sugg = SuggestionStub()
    session = SessionStub()

    class ClusterRepoStub:
        def __init__(self) -> None:
            self.called_with: str | None = None

        async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0):
            self.called_with = tenant_id
            return []

    cluster_repo = ClusterRepoStub()

    service = ClusterService(
        gate=gate,
        representative_discovery=RepresentativeDiscovery(settings=settings),
        centroid_discovery=CentroidDiscovery(settings=settings),
        graph_discovery=GraphDiscovery(settings=settings, algorithm=None),
        assignment_writer=writer,
        suggestion_service=sugg,
        logger=None,
        session=cast(Any, session),
    )
    service.assignment_writer._clusters = cast(Any, cluster_repo)

    tenant_id = str(uuid.uuid4())
    result = await service.cluster_unclustered_identities(tenant_id)

    assert result.total == 0
    assert result.clusters_created == 0  # No unclustered identities means no clusters created
    # Verify that existing clusters were fetched for discovery inputs
    assert cluster_repo.called_with == tenant_id
    assert session.execute_called  # Session was used to query for unclustered identities


@pytest.mark.asyncio
async def test_cluster_service_routes_decisions_and_logs() -> None:
    settings = make_settings()
    identity_a = make_identity(normalize(np.array([1.0, 0.0, 0.0])))
    identity_b = make_identity(normalize(np.array([0.0, 1.0, 0.0])))
    cluster_id = str(generate_id())

    rep = RepresentativeDiscovery(settings=settings)
    centroid = CentroidDiscovery(settings=settings)
    graph = GraphDiscovery(settings=settings, algorithm=None)

    gate = GateStub([AssignmentOutcome.ACCEPT, AssignmentOutcome.SUGGEST])
    writer = WriterStub()
    sugg = SuggestionStub()
    logger = LoggerStub()

    service = ClusterService(
        gate=gate,
        representative_discovery=rep,
        centroid_discovery=centroid,
        graph_discovery=graph,
        assignment_writer=writer,
        suggestion_service=sugg,
        logger=logger,
    )

    reps = {cluster_id: [normalize(np.array([1.0, 0.0, 0.0]))]}
    centroids = {cluster_id: normalize(np.array([0.0, 1.0, 0.0]))}

    await service.cluster([identity_a, identity_b], reps, centroids, anchor_embeddings={})

    assert len(writer.assigned) == 1
    assert writer.assigned[0].candidate.identity.id == identity_a.id
    assert len(sugg.created) == 1
    assert sugg.created[0][0].identity.id == identity_b.id
    assert logger.logged
    logged_decisions = {entry[2] for entry in logger.logged}
    assert logged_decisions == {DecisionType.ACCEPT, DecisionType.SUGGEST}


@pytest.mark.asyncio
async def test_cluster_service_wraps_in_transaction() -> None:
    """ClusterService should honor provided session transaction."""
    settings = make_settings()
    identity = make_identity(normalize(np.array([1.0, 0.0, 0.0])))
    cluster_id = str(generate_id())

    service = ClusterService(
        gate=GateStub([AssignmentOutcome.ACCEPT]),
        representative_discovery=RepresentativeDiscovery(settings=settings),
        centroid_discovery=CentroidDiscovery(settings=settings),
        graph_discovery=GraphDiscovery(settings=settings, algorithm=None),
        assignment_writer=WriterStub(),
        suggestion_service=SuggestionStub(),
        logger=LoggerStub(),
    )

    reps = {cluster_id: [normalize(np.array([1.0, 0.0, 0.0]))]}
    centroids: dict[str, np.ndarray] = {}
    session = SessionStub()

    await service.cluster([identity], reps, centroids, anchor_embeddings={}, session=session)

    assert session.begin_called is True


@pytest.mark.asyncio
async def test_cluster_service_persists_new_graph_clusters() -> None:
    """Graph discovery new clusters should persist via AssignmentWriter."""
    settings = make_settings()
    identity = make_identity(normalize(np.array([1.0, 0.0, 0.0])))

    class GraphStub(GraphDiscovery):
        def __init__(self) -> None:
            super().__init__(settings=settings, algorithm=None)

        async def discover(self, identities, anchor_embeddings):
            return GraphDiscoveryResult(
                candidates=[],
                new_clusters=[(list(identities), [0.95 for _ in identities])],
            )

    writer = WriterStub()
    service = ClusterService(
        gate=GateStub([]),
        representative_discovery=RepresentativeDiscovery(settings=settings),
        centroid_discovery=CentroidDiscovery(settings=settings),
        graph_discovery=GraphStub(),
        assignment_writer=writer,
        suggestion_service=SuggestionStub(),
        logger=None,
    )

    await service.cluster([identity], representatives_by_cluster={}, centroids_by_cluster={}, anchor_embeddings={})

    assert len(writer.created_clusters) == 1
    tenant_id, members, sims, algo = writer.created_clusters[0]
    assert tenant_id == identity.tenant_id
    assert members == [identity]
    assert sims == [0.95]
    assert algo == "hybrid"

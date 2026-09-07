"""Integration-style tests for ClusterService orchestration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

import recognition.application.orchestration.cluster_service as cluster_service_module
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
from recognition.domain.repositories import ClusterRepository, MemberRepository, MvRefreshOutcome
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
    def __init__(
        self,
        *,
        cluster_repository: ClusterRepository | None = None,
        member_repository: MemberRepository | None = None,
    ) -> None:
        self._clusters = cast(ClusterRepository, cluster_repository)
        self._members = cast(MemberRepository, member_repository)
        self.assigned: list[AssignmentDecision] = []
        self.created_clusters: list[tuple[str, list[MediaIdentity], list[float], str]] = []
        self.refresh_called = False

    async def persist_assignment(self, decision: AssignmentDecision, batch_mode: bool = False) -> None:
        self.assigned.append(decision)

    async def persist_new_cluster(
        self, tenant_id: str, identities, similarities, algorithm="graph", cluster_id=None, clustering_logger=None
    ):
        self.created_clusters.append((tenant_id, list(identities), list(similarities), algorithm))

    async def update_cluster_metadata(
        self, cluster_id: str, label: str | None = None, representative_id: str | None = None
    ):
        raise NotImplementedError

    async def refresh_centroids_view(self) -> None:
        self.refresh_called = True

    async def refresh_centroids_view_concurrent(self) -> MvRefreshOutcome:
        return MvRefreshOutcome.REFRESHED


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

    async def get(self, _model, _id):
        """Return None to simulate no existing job."""
        return None

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

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@pytest.mark.asyncio
async def test_cluster_unclustered_refreshes_centroids_before_merge_suggestions(monkeypatch) -> None:
    """ClusterService should refresh centroids before generating merge suggestions."""
    calls: list[str] = []

    async def fake_cluster_unclustered_identities_op(**_kwargs):  # noqa: ANN001
        return object()

    monkeypatch.setattr(
        cluster_service_module, "cluster_unclustered_identities_op", fake_cluster_unclustered_identities_op
    )

    async def _refresh_centroids_view() -> None:
        calls.append("refresh")

    async def _generate_for_tenant(_tenant_id: str) -> int:
        calls.append("generate")
        return 0

    writer = Mock(spec=AssignmentWriter)
    writer.refresh_centroids_view = AsyncMock(side_effect=_refresh_centroids_view)

    merge_service = Mock()
    merge_service.generate_for_tenant = AsyncMock(side_effect=_generate_for_tenant)

    service = ClusterService(
        gate=Mock(),
        representative_discovery=Mock(),
        centroid_discovery=Mock(),
        graph_discovery=Mock(),
        assignment_writer=writer,
        suggestion_service=Mock(),
        merge_suggestion_service=merge_service,
        session=SessionStub(),
        logger=None,
    )

    await service.cluster_unclustered_identities("tenant-1", commit=True)

    assert calls == ["refresh", "generate"]

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_cluster_unclustered_identities_skips_existing_cluster_fetch_when_empty() -> None:
    """cluster_unclustered_identities should not fetch existing clusters when there is nothing to process."""
    settings = make_settings()
    gate = GateStub([AssignmentOutcome.ACCEPT])
    sugg = SuggestionStub()
    session = SessionStub()

    class ClusterRepoStub:
        def __init__(self) -> None:
            self.called_with: str | None = None

        async def get_by_tenant(self, tenant_id: str, *, limit: int = 100, offset: int = 0):
            self.called_with = tenant_id
            return []

        async def cleanup_orphaned_provisional_reps(self, *_args, **_kwargs) -> int:
            return 0

        async def get_singleton_identities(self, tenant_id: str, *, limit: int | None = None):
            return []

    cluster_repo = ClusterRepoStub()
    writer = WriterStub(cluster_repository=cluster_repo)

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
    tenant_id = str(uuid.uuid4())
    result = await service.cluster_unclustered_identities(tenant_id)

    assert result.total == 0
    assert result.clusters_created == 0  # No unclustered identities means no clusters created
    assert cluster_repo.called_with is None
    assert session.execute_called  # Session was used to query for unclustered identities

"""Tests for batch surfacing in SuggestionRefreshService."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.refresh_service import SuggestionRefreshService
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import SuggestionCreateData
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


class StubSuggestionRepository:
    def __init__(self) -> None:
        self.payloads: list[SuggestionCreateData] = []

    async def upsert_by_identity_cluster(self, tenant_id: str, payload: SuggestionCreateData) -> AssignmentSuggestion:
        self.payloads.append(payload)
        return AssignmentSuggestion(
            id="suggestion-1",
            identity_id=payload.identity_id,
            cluster_id=payload.cluster_id,
            representative_similarity=payload.representative_similarity,
            member_similarity=payload.member_similarity,
            status=SuggestionStatus.PENDING,
            created_at=datetime.now(tz=UTC),
        )


class StubClusterRepository:
    def __init__(self, identities_by_cluster: dict[str, list[MediaIdentity]]) -> None:
        self.identities_by_cluster = identities_by_cluster
        self.calls: list[list[str]] = []

    async def get_member_identities_for_clusters(self, cluster_ids: Sequence[str]) -> dict[str, list[MediaIdentity]]:
        self.calls.append(list(cluster_ids))
        return {cid: self.identities_by_cluster.get(cid, []) for cid in cluster_ids}


def _make_identity(identity_id: str) -> MediaIdentity:
    embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    return MediaIdentity(
        id=identity_id,
        tenant_id="tenant-1",
        media_id="media-1",
        embedding=embedding,
        confidence=0.99,
        bbox_width=10,
        bbox_height=10,
    )


@pytest.mark.asyncio
async def test_batch_surfacing_groups_by_cluster() -> None:
    identity = _make_identity("identity-1")
    cluster_repo = StubClusterRepository({"cluster-2": [identity]})
    suggestion_repo = StubSuggestionRepository()
    settings = ClusteringSettings(
        similarity_threshold=0.0,
        suggestion_floor=0.0,
        suggestion_ceiling=1.1,
    )

    service = SuggestionRefreshService(
        repository=suggestion_repo,
        tenant_id="tenant-1",
        cluster_repository=cluster_repo,
        session=object(),
        settings=settings,
    )

    representatives_by_cluster: dict[str, Any] = {"cluster-1": [identity.embedding]}
    created = await service.surface_for_newly_labeled_cluster(
        "cluster-1",
        cluster_label="Test Label",
        candidate_cluster_ids=["cluster-2"],
        representatives_by_cluster=representatives_by_cluster,
    )

    assert created == 1
    assert cluster_repo.calls == [["cluster-2"]]
    assert len(suggestion_repo.payloads) == 1


@pytest.mark.asyncio
async def test_batch_surfacing_handles_empty_clusters() -> None:
    cluster_repo = StubClusterRepository({})
    suggestion_repo = StubSuggestionRepository()
    settings = ClusteringSettings(
        similarity_threshold=0.0,
        suggestion_floor=0.0,
        suggestion_ceiling=1.1,
    )

    service = SuggestionRefreshService(
        repository=suggestion_repo,
        tenant_id="tenant-1",
        cluster_repository=cluster_repo,
        session=object(),
        settings=settings,
    )

    representatives_by_cluster: dict[str, Any] = {"cluster-1": [np.array([1.0, 0.0, 0.0], dtype=np.float32)]}
    created = await service.surface_for_newly_labeled_cluster(
        "cluster-1",
        cluster_label="Test Label",
        candidate_cluster_ids=[],
        representatives_by_cluster=representatives_by_cluster,
    )

    assert created == 0
    assert cluster_repo.calls == []


@pytest.mark.asyncio
async def test_batch_surfacing_handles_large_cluster_sets() -> None:
    cluster_ids = [f"cluster-{i}" for i in range(1, 51)]
    identities_by_cluster: dict[str, list[MediaIdentity]] = {}
    for idx, cluster_id in enumerate(cluster_ids):
        identities_by_cluster[cluster_id] = [
            _make_identity(f"identity-{idx}-a"),
            _make_identity(f"identity-{idx}-b"),
        ]

    cluster_repo = StubClusterRepository(identities_by_cluster)
    suggestion_repo = StubSuggestionRepository()
    settings = ClusteringSettings(
        similarity_threshold=0.0,
        suggestion_floor=0.0,
        suggestion_ceiling=1.1,
    )

    service = SuggestionRefreshService(
        repository=suggestion_repo,
        tenant_id="tenant-1",
        cluster_repository=cluster_repo,
        session=object(),
        settings=settings,
    )

    representatives_by_cluster: dict[str, Any] = {"cluster-0": [np.array([1.0, 0.0, 0.0], dtype=np.float32)]}
    created = await service.surface_for_newly_labeled_cluster(
        "cluster-0",
        cluster_label="Test Label",
        candidate_cluster_ids=cluster_ids,
        representatives_by_cluster=representatives_by_cluster,
    )

    assert created == 100
    assert len(suggestion_repo.payloads) == 100
    assert cluster_repo.calls == [cluster_ids]

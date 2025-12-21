"""Unit tests for SuggestionService filtering rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.settings import ClusteringSettings
from recognition.application.suggestions.service import SuggestionRefreshReason, SuggestionService
from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.repositories import ClusterRepository, SuggestionRepository
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionStatus


def _make_candidate(tenant_id: str, cluster_id: str) -> AssignmentCandidate:
    identity = MediaIdentity(
        id="identity-1",
        tenant_id=tenant_id,
        media_id="media-1",
        embedding=np.zeros(512, dtype=np.float32),
        confidence=0.9,
        bbox_width=1,
        bbox_height=1,
    )
    return AssignmentCandidate(
        identity=identity,
        identity_vector=np.zeros(512, dtype=np.float32),
        cluster_id=cluster_id,
        discovery_method=DiscoveryMethod.REPRESENTATIVE,
        discovery_similarity=0.88,
    )


@pytest.mark.asyncio
async def test_create_skips_unlabeled_clusters() -> None:
    tenant_id = "tenant-1"
    cluster_id = "cluster-1"

    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    suggestion_repo.create.return_value = AssignmentSuggestion(
        id="s-1",
        identity_id="identity-1",
        cluster_id=cluster_id,
        representative_similarity=0.88,
        member_similarity=0.88,
        status=SuggestionStatus.PENDING,
        created_at=datetime.now(tz=UTC),
    )

    cluster_repo = AsyncMock(spec=ClusterRepository)
    cluster_repo.get_by_id.return_value = IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        label=None,
        is_labeled=False,
        identity_count=1,
        user_confirmed=False,
        created_at=None,
    )

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, cluster_repository=cluster_repo)
    result = await service.create(_make_candidate(tenant_id, cluster_id))

    assert result is None
    suggestion_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_persists_for_user_labeled_clusters() -> None:
    tenant_id = "tenant-1"
    cluster_id = "cluster-1"

    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    expected = AssignmentSuggestion(
        id="s-1",
        identity_id="identity-1",
        cluster_id=cluster_id,
        representative_similarity=0.88,
        member_similarity=0.88,
        status=SuggestionStatus.PENDING,
        created_at=datetime.now(tz=UTC),
    )
    suggestion_repo.create.return_value = expected

    cluster_repo = AsyncMock(spec=ClusterRepository)
    cluster_repo.get_by_id.return_value = IdentityCluster(
        id=cluster_id,
        tenant_id=tenant_id,
        label="Ryann Wiseman",
        is_labeled=True,
        identity_count=10,
        user_confirmed=True,
        created_at=None,
    )

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, cluster_repository=cluster_repo)
    result = await service.create(_make_candidate(tenant_id, cluster_id), confidence=0.91)

    assert result is expected
    suggestion_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_for_identity_exclusive_accepts_and_rejects() -> None:
    tenant_id = "tenant-1"
    cluster_id = "cluster-1"
    other_cluster_id = "cluster-2"

    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    suggestion_repo.get_by_identity.return_value = [
        AssignmentSuggestion(
            id="s-1",
            identity_id="identity-1",
            cluster_id=cluster_id,
            representative_similarity=0.8,
            member_similarity=0.8,
            status=SuggestionStatus.PENDING,
            created_at=datetime.now(tz=UTC),
        ),
        AssignmentSuggestion(
            id="s-2",
            identity_id="identity-1",
            cluster_id=other_cluster_id,
            representative_similarity=0.7,
            member_similarity=0.7,
            status=SuggestionStatus.PENDING,
            created_at=datetime.now(tz=UTC),
        ),
    ]
    suggestion_repo.bulk_update_status.return_value = 1

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, cluster_repository=None)
    updated = await service.resolve_for_identity_exclusive(
        identity_id="identity-1",
        accepted_cluster_id=cluster_id,
        reason="manual_assign",
    )

    assert updated == 2
    suggestion_repo.update_status.assert_awaited_once_with(tenant_id, "s-1", SuggestionStatus.ACCEPTED)
    suggestion_repo.bulk_update_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_refresh_for_identity_creates_suggestion_for_band() -> None:
    tenant_id = str(uuid.uuid4())
    cluster_id = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())

    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    suggestion_repo.upsert_by_identity_cluster.return_value = AssignmentSuggestion(
        id="s-1",
        identity_id=identity_id,
        cluster_id=cluster_id,
        representative_similarity=0.75,
        member_similarity=0.75,
        status=SuggestionStatus.PENDING,
        created_at=datetime.now(tz=UTC),
    )

    class ClusterRepoStub:
        async def get_by_tenant(self, *_args, **_kwargs):
            return [
                IdentityCluster(
                    id=cluster_id,
                    tenant_id=tenant_id,
                    label="Avery Rhodes",
                    is_labeled=True,
                    identity_count=5,
                    user_confirmed=True,
                    created_at=None,
                )
            ]

        async def get_all_representatives(self, _cluster_id):
            rep_vec = np.array([0.75, np.sqrt(1 - 0.75**2)], dtype=np.float32)
            return [type("Rep", (), {"embedding": rep_vec})()]

    class SessionStub:
        async def get(self, _model, _identity_id):
            return type(
                "IdentityModel",
                (),
                {
                    "id": uuid.UUID(identity_id),
                    "tenant_id": uuid.UUID(tenant_id),
                    "media_id": "media-1",
                    "embedding": np.array([1.0, 0.0], dtype=np.float32),
                    "confidence": 0.9,
                    "bbox_width": 1,
                    "bbox_height": 1,
                },
            )()

    settings = ClusteringSettings(
        similarity_threshold=0.8,
        suggestion_floor=0.7,
        suggestion_ceiling=0.8,
    )
    service = SuggestionService(
        suggestion_repo,
        tenant_id=tenant_id,
        cluster_repository=ClusterRepoStub(),
        session=SessionStub(),
        settings=settings,
    )

    suggestions = await service.refresh_for_identity(
        identity_id=identity_id,
        reason=SuggestionRefreshReason.MANUAL_SPLIT,
    )

    assert len(suggestions) == 1
    suggestion_repo.upsert_by_identity_cluster.assert_awaited_once()

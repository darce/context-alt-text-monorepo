"""Unit tests for SuggestionService filtering rules."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.application.assignment.candidate import AssignmentCandidate, DiscoveryMethod
from recognition.application.suggestions.service import SuggestionService
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
        member_count=1,
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
        member_count=10,
        user_confirmed=True,
        created_at=None,
    )

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, cluster_repository=cluster_repo)
    result = await service.create(_make_candidate(tenant_id, cluster_id), confidence=0.91)

    assert result is expected
    suggestion_repo.create.assert_awaited_once()

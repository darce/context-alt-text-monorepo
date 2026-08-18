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
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    SuggestedLabel,
    SuggestedLabelSource,
    SuggestionStatus,
)
from recognition.domain.suggestion_details import SuggestionDetails


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
async def test_create_returns_none_for_unlabeled_clusters() -> None:
    """v4.12.0: Unlabeled clusters are not eligible for suggestions."""
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
        label=None,  # Unlabeled
        is_labeled=False,
        identity_count=1,
        user_confirmed=False,  # Not confirmed
        created_at=None,
    )

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, cluster_repository=cluster_repo)
    result = await service.create(_make_candidate(tenant_id, cluster_id))

    # v4.12.0: confirmed-only eligibility rejects unlabeled/unconfirmed clusters
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
        label="Muted Yarrow",
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
async def test_reject_creates_blocks_and_constraints() -> None:
    tenant_id = "tenant-1"
    suggestion_id = "s-1"
    identity_id = "identity-1"
    cluster_id = "cluster-1"
    rep_identity_id = "rep-identity-1"

    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    suggestion = AssignmentSuggestion(
        id=suggestion_id,
        identity_id=identity_id,
        cluster_id=cluster_id,
        representative_similarity=0.8,
        member_similarity=0.8,
        status=SuggestionStatus.REJECTED,
        created_at=datetime.now(tz=UTC),
    )
    suggestion_repo.update_status.return_value = suggestion

    cluster_repo = AsyncMock(spec=ClusterRepository)
    cluster_repo.get_by_id.return_value = type(
        "Cluster", (), {"id": cluster_id, "representative_identity_id": rep_identity_id}
    )()

    block_repo = AsyncMock()
    constraint_repo = AsyncMock()

    service = SuggestionService(
        suggestion_repo,
        tenant_id=tenant_id,
        cluster_repository=cluster_repo,
        block_repository=block_repo,
        constraint_repository=constraint_repo,
    )

    result = await service.reject(suggestion_id)

    assert result == suggestion
    suggestion_repo.update_status.assert_awaited_once_with(tenant_id, suggestion_id, SuggestionStatus.REJECTED)
    block_repo.add_block.assert_awaited_once_with(
        tenant_id=tenant_id,
        identity_id=identity_id,
        blocked_cluster_id=cluster_id,
        reason="manual_reject",
    )
    constraint_repo.create_cannot_link.assert_awaited_once_with(
        tenant_id=tenant_id,
        identity_a=identity_id,
        identity_b=rep_identity_id,
        source="manual_reject",
    )


@pytest.mark.asyncio
async def test_list_pending_enriches_suggested_label_from_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = "tenant-1"
    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    suggestion_repo.list_pending_with_details.return_value = [
        SuggestionDetails(
            id="s-1",
            identity_id="identity-1",
            cluster_id="cluster-1",
            representative_similarity=0.61,
            member_similarity=0.61,
            status="pending",
            cluster_label=None,
        )
    ]

    infer_mock = AsyncMock(
        return_value=SuggestedLabel(
            label="Slate Willow",
            source=SuggestedLabelSource.SIMILAR_CLUSTER,
            confidence=0.68,
        )
    )
    monkeypatch.setattr("recognition.application.suggestions.service.infer_suggested_label", infer_mock)

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, session=AsyncMock())
    pending = await service.list_pending(limit=25, offset=0)

    assert len(pending) == 1
    assert pending[0].suggested_label == "Slate Willow"
    assert pending[0].suggested_label_source == SuggestedLabelSource.SIMILAR_CLUSTER
    assert pending[0].suggested_label_confidence == 0.68
    infer_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_pending_skips_inference_for_labeled_clusters(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = "tenant-1"
    suggestion_repo = AsyncMock(spec=SuggestionRepository)
    suggestion_repo.list_pending_with_details.return_value = [
        SuggestionDetails(
            id="s-1",
            identity_id="identity-1",
            cluster_id="cluster-1",
            representative_similarity=0.78,
            member_similarity=0.78,
            status="pending",
            cluster_label="Known Person",
        )
    ]

    infer_mock = AsyncMock()
    monkeypatch.setattr("recognition.application.suggestions.service.infer_suggested_label", infer_mock)

    service = SuggestionService(suggestion_repo, tenant_id=tenant_id, session=AsyncMock())
    pending = await service.list_pending(limit=10, offset=0)

    assert len(pending) == 1
    assert pending[0].cluster_label == "Known Person"
    infer_mock.assert_not_awaited()

"""Integration tests for Proactive Label Suggestions (Phase 4).

Verifies that unlabeled clusters are surfaced as suggestions
and that identity removal triggers recalibration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from db.models import MediaIdentity as MediaIdentityModel
from recognition.domain.cluster import IdentityCluster
from recognition.infrastructure.repositories import SqlAlchemySuggestionRepository
from recognition.interface_adapters.http import dependencies


@pytest.mark.asyncio
async def test_unlabeled_clusters_are_surfaced_as_suggestions(db_session, tenant) -> None:
    """Unlabeled clusters should appear in suggestion list pending response."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    suggestion_repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    # 1. Create a cluster (unlabeled)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    # 2. Create an identity
    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=1001,
        media_url="http://example.test/1001.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity)
    await db_session.flush()

    await member_repo.add_member(cluster.id, identity_id=str(identity.id), similarity=0.95)

    # 3. Create a suggestion pointing to this cluster (as if from clustering process)
    # We need a new identity to be suggested
    suggestion_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=1002,
        media_url="http://example.test/1002.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,  # Similar to cluster member
    )
    db_session.add(suggestion_identity)
    await db_session.flush()

    from recognition.domain.repositories import SuggestionCreateData

    await suggestion_repo.create(
        tenant_id=str(tenant.id),
        payload=SuggestionCreateData(
            identity_id=str(suggestion_identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.92,
            member_similarity=0.90,
            confidence_score=0.92,
            refreshed_at=None,
            source="test",
        ),
    )

    await db_session.commit()

    # 4. List pending suggestions
    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)

    # 5. Verify unlabeled cluster is returned
    assert len(suggestions) == 1
    item = suggestions[0]
    assert item.cluster_id == cluster.id
    assert item.cluster_label is None
    assert item.identity_id == str(suggestion_identity.id)


@pytest.mark.asyncio
async def test_identity_removal_triggers_suggestion_refresh(db_session, tenant) -> None:
    """Removing an identity from a cluster should trigger suggestion refresh for that cluster."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    # We need to access the suggestion service to check if refresh was called,
    # or observe side effects. Since refresh is async/background, side effects are better.
    # However, for integration test, we can trust the service composition if we verified unrelated parts.
    # But ideally we check that updated suggestions reflect the change.

    # Actually, `remove_identity_from_cluster` calls `refresh_for_cluster`.
    # `refresh_for_cluster` recalculates centroid and finds new suggestions.
    # We can check if `refresh_for_cluster` logic is invoked by checking if suggestions change?
    # Or mock the refresh service if we want to confirm the CALL.
    # Given this is integration, let's just ensure the operation succeeds and suggestions remain consistent.

    # Mocking refresh service call is safer to confirm the wiring logic added in Phase 3.
    from unittest.mock import AsyncMock

    mock_refresh = AsyncMock()
    cluster_service.suggestion_refresh_service = mock_refresh

    # 1. Setup cluster with member
    cluster = await cluster_service.assignment_writer.cluster_repository.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Test Removal",
            is_labeled=True,
            identity_count=1,
            created_at=None,
        )
    )

    embedding = [0.0] * 512
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=2001,
        media_url="http://example.test/2001.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
    )
    db_session.add(identity)
    await db_session.flush()

    await cluster_service.assignment_writer.member_repository.add_member(
        cluster.id, identity_id=str(identity.id), similarity=0.9
    )
    await db_session.commit()

    # 2. Remove identity
    success = await cluster_service.remove_identity_from_cluster(str(identity.id), recompute=True)

    # 3. Verify success and refresh call
    assert success is True

    # Verify mock was called with cluster ID
    mock_refresh.refresh_for_cluster.assert_awaited_with(cluster.id)

"""Integration tests for merge suggestion repository behavior."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import MergeSuggestionCreateData
from recognition.domain.suggestion import SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemyMergeSuggestionRepository


@pytest.mark.asyncio
async def test_delete_by_cluster_removes_related_suggestions(db_session, tenant) -> None:
    """delete_by_cluster should remove suggestions involving the specified cluster."""
    tenant_id = str(tenant.id)
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    merge_repo = SqlAlchemyMergeSuggestionRepository(db_session)

    cluster_a = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    cluster_b = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    cluster_c = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    await db_session.commit()

    if cluster_a.id is None or cluster_b.id is None or cluster_c.id is None:
        raise AssertionError("Test setup requires cluster IDs")

    now = datetime.now(tz=UTC)
    await merge_repo.upsert_pending(
        tenant_id,
        MergeSuggestionCreateData(
            cluster_a_id=cluster_a.id,
            cluster_b_id=cluster_b.id,
            similarity=0.72,
            refreshed_at=now,
        ),
    )
    await merge_repo.upsert_pending(
        tenant_id,
        MergeSuggestionCreateData(
            cluster_a_id=cluster_a.id,
            cluster_b_id=cluster_c.id,
            similarity=0.73,
            refreshed_at=now,
        ),
    )
    await merge_repo.upsert_pending(
        tenant_id,
        MergeSuggestionCreateData(
            cluster_a_id=cluster_b.id,
            cluster_b_id=cluster_c.id,
            similarity=0.74,
            refreshed_at=now,
        ),
    )
    await db_session.commit()

    deleted = await merge_repo.delete_by_cluster(tenant_id, cluster_a.id)

    assert deleted == 2
    remaining = await merge_repo.list_pending_with_details(tenant_id, limit=10, offset=0)
    assert len(remaining) == 1
    remaining_pair = {remaining[0].cluster_a_id, remaining[0].cluster_b_id}
    assert remaining_pair == {cluster_b.id, cluster_c.id}


@pytest.mark.asyncio
async def test_delete_by_cluster_keeps_non_pending(db_session, tenant) -> None:
    """delete_by_cluster should keep accepted/rejected suggestions."""
    tenant_id = str(tenant.id)
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    merge_repo = SqlAlchemyMergeSuggestionRepository(db_session)

    cluster_a = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    cluster_b = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    cluster_c = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=tenant_id,
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )
    await db_session.commit()

    if cluster_a.id is None or cluster_b.id is None or cluster_c.id is None:
        raise AssertionError("Test setup requires cluster IDs")

    now = datetime.now(tz=UTC)
    await merge_repo.upsert_pending(
        tenant_id,
        MergeSuggestionCreateData(
            cluster_a_id=cluster_a.id,
            cluster_b_id=cluster_b.id,
            similarity=0.72,
            refreshed_at=now,
        ),
    )
    accepted = await merge_repo.upsert_pending(
        tenant_id,
        MergeSuggestionCreateData(
            cluster_a_id=cluster_a.id,
            cluster_b_id=cluster_c.id,
            similarity=0.74,
            refreshed_at=now,
        ),
    )
    await merge_repo.update_status(tenant_id, accepted.id, SuggestionStatus.ACCEPTED)
    await db_session.commit()

    deleted = await merge_repo.delete_by_cluster(tenant_id, cluster_a.id)

    assert deleted == 1
    remaining = await merge_repo.list_pending_with_details(tenant_id, limit=10, offset=0)
    assert len(remaining) == 0
    accepted_after = await merge_repo.get_by_id(tenant_id, accepted.id)
    assert accepted_after is not None

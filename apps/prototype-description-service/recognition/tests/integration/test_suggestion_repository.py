"""TDD-first tests for suggestion persistence (Phase 7.3, Task 53)."""

from __future__ import annotations

import uuid

import pytest

from db.models import Tenant
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import SuggestionCreateData
from recognition.domain.suggestion import SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemyClusterRepository, SqlAlchemySuggestionRepository


@pytest.mark.asyncio
async def test_create_persists_suggestion(db_session, tenant) -> None:
    """Creating a suggestion should persist and return a domain object."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Target",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        representative_similarity=0.91,
        member_similarity=0.82,
        confidence_score=0.87,
    )

    suggestion = await repo.create(str(tenant.id), payload)

    assert suggestion.id
    assert suggestion.identity_id == payload.identity_id
    assert suggestion.cluster_id == payload.cluster_id
    assert suggestion.status is SuggestionStatus.PENDING


@pytest.mark.asyncio
async def test_get_by_identity_returns_only_tenant_rows(db_session, tenant) -> None:
    """Suggestions should be filtered by tenant and identity."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        representative_similarity=0.9,
        member_similarity=0.8,
        confidence_score=0.85,
    )
    await repo.create(str(tenant.id), payload)

    other_tenant_id = str(uuid.uuid4())
    other_tenant = Tenant(id=uuid.UUID(other_tenant_id), site_url="http://other.example.test")
    db_session.add(other_tenant)
    await db_session.commit()
    other_repo = SqlAlchemySuggestionRepository(db_session, tenant_id=other_tenant_id)
    other_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=other_tenant_id,
            label="Other",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    other_payload = SuggestionCreateData(
        identity_id=payload.identity_id,
        cluster_id=other_cluster.id,
        representative_similarity=0.1,
        member_similarity=0.2,
        confidence_score=0.3,
    )
    await other_repo.create(other_tenant_id, other_payload)

    results = await repo.get_by_identity(str(tenant.id), payload.identity_id)
    assert len(results) == 1
    assert results[0].cluster_id == payload.cluster_id


@pytest.mark.asyncio
async def test_get_by_cluster_filters_tenant(db_session, tenant) -> None:
    """Fetching by cluster should not leak suggestions from other tenants."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        representative_similarity=0.92,
        member_similarity=0.83,
        confidence_score=0.88,
    )
    await repo.create(str(tenant.id), payload)

    other_tenant_id = str(uuid.uuid4())
    other_tenant = Tenant(id=uuid.UUID(other_tenant_id), site_url="http://other-tenant.test")
    db_session.add(other_tenant)
    await db_session.commit()

    other_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=other_tenant_id,
            label="Other",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )

    other_repo = SqlAlchemySuggestionRepository(db_session, tenant_id=other_tenant_id)
    other_payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=other_cluster.id,
        representative_similarity=0.5,
        member_similarity=0.4,
        confidence_score=0.45,
    )
    await other_repo.create(other_tenant_id, other_payload)

    results = await repo.get_by_cluster(str(tenant.id), cluster.id)
    assert len(results) == 1
    assert results[0].identity_id == payload.identity_id


@pytest.mark.asyncio
async def test_update_status_transitions(db_session, tenant) -> None:
    """PENDING suggestions should transition to accepted/rejected."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        representative_similarity=0.95,
        member_similarity=0.86,
        confidence_score=0.9,
    )
    suggestion = await repo.create(str(tenant.id), payload)

    accepted = await repo.update_status(str(tenant.id), suggestion.id, SuggestionStatus.ACCEPTED)
    assert accepted.status is SuggestionStatus.ACCEPTED

    rejected = await repo.update_status(str(tenant.id), suggestion.id, SuggestionStatus.REJECTED)
    assert rejected.status is SuggestionStatus.REJECTED


@pytest.mark.asyncio
async def test_create_upserts_pending_suggestion_scores(db_session, tenant) -> None:
    """Creating the same pending suggestion twice should update its score fields."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    identity_id = str(uuid.uuid4())

    original = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster.id,
            representative_similarity=0.9,
            member_similarity=0.8,
            confidence_score=0.85,
        ),
    )

    updated = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster.id,
            representative_similarity=0.6,
            member_similarity=0.55,
            confidence_score=0.58,
        ),
    )

    assert updated.id == original.id
    assert updated.representative_similarity == pytest.approx(0.6)
    assert updated.member_similarity == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_update_scores_updates_pending_suggestions(db_session, tenant) -> None:
    """update_scores should update stored similarity metrics for pending suggestions."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        representative_similarity=0.91,
        member_similarity=0.82,
        confidence_score=0.87,
    )
    suggestion = await repo.create(str(tenant.id), payload)

    rescored = await repo.update_scores(
        str(tenant.id),
        suggestion.id,
        representative_similarity=0.77,
        member_similarity=0.71,
        confidence_score=0.73,
    )

    assert rescored.id == suggestion.id
    assert rescored.representative_similarity == pytest.approx(0.77)
    assert rescored.member_similarity == pytest.approx(0.71)


@pytest.mark.asyncio
async def test_update_scores_does_not_modify_resolved_suggestions(db_session, tenant) -> None:
    """Resolved suggestions should preserve historical scores."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=False,
            identity_count=0,
            created_at=None,
        )
    )
    repo = SqlAlchemySuggestionRepository(db_session, tenant_id=str(tenant.id))
    payload = SuggestionCreateData(
        identity_id=str(uuid.uuid4()),
        cluster_id=cluster.id,
        representative_similarity=0.91,
        member_similarity=0.82,
        confidence_score=0.87,
    )
    suggestion = await repo.create(str(tenant.id), payload)
    await repo.update_status(str(tenant.id), suggestion.id, SuggestionStatus.ACCEPTED)

    rescored = await repo.update_scores(
        str(tenant.id),
        suggestion.id,
        representative_similarity=0.1,
        member_similarity=0.2,
        confidence_score=0.3,
    )

    assert rescored.id == suggestion.id
    assert rescored.representative_similarity == pytest.approx(payload.representative_similarity)
    assert rescored.member_similarity == pytest.approx(payload.member_similarity)

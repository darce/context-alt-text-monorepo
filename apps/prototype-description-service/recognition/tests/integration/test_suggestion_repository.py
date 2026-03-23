"""TDD-first tests for suggestion persistence (Phase 7.3, Task 53)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from db.models import IdentityClusteringJob, IdentityClusterRepresentative, IdentityMember, MediaIdentity, Tenant
from db.models.constraints import IdentitySuggestion
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

    repo = SqlAlchemySuggestionRepository(db_session)
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
    repo = SqlAlchemySuggestionRepository(db_session)
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
    other_repo = SqlAlchemySuggestionRepository(db_session)
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

    repo = SqlAlchemySuggestionRepository(db_session)
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

    other_repo = SqlAlchemySuggestionRepository(db_session)
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
    repo = SqlAlchemySuggestionRepository(db_session)
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
    repo = SqlAlchemySuggestionRepository(db_session)
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
    repo = SqlAlchemySuggestionRepository(db_session)
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
    repo = SqlAlchemySuggestionRepository(db_session)
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


@pytest.mark.asyncio
async def test_bulk_update_status_updates_multiple_rows(db_session, tenant) -> None:
    """bulk_update_status should update status for multiple suggestions."""
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
    repo = SqlAlchemySuggestionRepository(db_session)

    suggestion_a = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            representative_similarity=0.88,
            member_similarity=0.81,
            confidence_score=0.84,
        ),
    )
    suggestion_b = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(uuid.uuid4()),
            cluster_id=cluster.id,
            representative_similarity=0.86,
            member_similarity=0.8,
            confidence_score=0.82,
        ),
    )

    updated = await repo.bulk_update_status(
        str(tenant.id),
        [suggestion_a.id, suggestion_b.id],
        SuggestionStatus.REJECTED,
    )

    assert updated == 2

    # get_by_cluster only returns pending suggestions, so rejected ones should NOT appear
    results = await repo.get_by_cluster(str(tenant.id), cluster.id)
    assert len(results) == 0, "Rejected suggestions should not appear in pending results"


@pytest.mark.asyncio
async def test_upsert_updates_pending_and_skips_resolved(db_session, tenant) -> None:
    """upsert_by_identity_cluster should update pending suggestions, not resolved ones."""
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
    repo = SqlAlchemySuggestionRepository(db_session)
    identity_id = str(uuid.uuid4())
    source_job = IdentityClusteringJob(tenant_id=tenant.id, status="completed", progress=1.0)
    updated_source_job = IdentityClusteringJob(tenant_id=tenant.id, status="completed", progress=1.0)
    db_session.add_all([source_job, updated_source_job])
    await db_session.flush()

    pending = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster.id,
            representative_similarity=0.9,
            member_similarity=0.85,
            confidence_score=0.87,
            source_job_id=str(source_job.id),
        ),
    )
    original_source_job_id = pending.source_job_id
    assert original_source_job_id is not None

    updated = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster.id,
            representative_similarity=0.7,
            member_similarity=0.65,
            confidence_score=0.68,
            source_job_id=str(updated_source_job.id),
        ),
    )

    assert updated.id == pending.id
    assert updated.representative_similarity == pytest.approx(0.7)
    assert updated.member_similarity == pytest.approx(0.65)
    assert updated.source_job_id == str(updated_source_job.id)

    resolved = await repo.update_status(str(tenant.id), pending.id, SuggestionStatus.ACCEPTED)
    assert resolved.status is SuggestionStatus.ACCEPTED

    skipped = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=identity_id,
            cluster_id=cluster.id,
            representative_similarity=0.2,
            member_similarity=0.2,
            confidence_score=0.2,
        ),
    )
    assert skipped.status is SuggestionStatus.ACCEPTED


def _embedding() -> list[float]:
    return [1.0] + [0.0] * 511


@pytest.mark.asyncio
async def test_cluster_context_changed_false_for_future_cutoff(db_session, tenant) -> None:
    """No evidence newer than cutoff should return False."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )
    repo = SqlAlchemySuggestionRepository(db_session)

    future_cutoff = datetime.now(tz=UTC) + timedelta(minutes=5)
    changed = await repo._cluster_context_changed(uuid.UUID(cluster.id), future_cutoff)
    assert changed is False


@pytest.mark.asyncio
async def test_cluster_context_changed_true_for_newer_representative(db_session, tenant) -> None:
    """Representative evidence newer than cutoff should return True."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )
    cluster_uuid = uuid.UUID(cluster.id)

    cutoff = datetime.now(tz=UTC)
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9001,
        media_url="http://example.test/9001.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    db_session.add(identity)
    await db_session.flush()

    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant.id,
            cluster_id=cluster_uuid,
            identity_id=identity.id,
            embedding=_embedding(),
            quality_score=0.9,
            created_at=cutoff + timedelta(minutes=1),
        )
    )
    await db_session.commit()

    repo = SqlAlchemySuggestionRepository(db_session)
    changed = await repo._cluster_context_changed(cluster_uuid, cutoff)
    assert changed is True


@pytest.mark.asyncio
async def test_rejected_suggestion_with_null_resolved_at_does_not_reopen(db_session, tenant) -> None:
    """Rejected suggestions without resolved_at should not reopen as new evidence."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Cluster",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )
    cluster_uuid = uuid.UUID(cluster.id)
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9011,
        media_url="http://example.test/9011.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    db_session.add(identity)
    await db_session.flush()

    repo = SqlAlchemySuggestionRepository(db_session)
    created = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.8,
            member_similarity=0.8,
            confidence_score=0.8,
        ),
    )
    await repo.update_status(str(tenant.id), created.id, SuggestionStatus.REJECTED)

    stmt = select(IdentitySuggestion).where(IdentitySuggestion.id == uuid.UUID(created.id))
    model = (await db_session.execute(stmt)).scalar_one()
    model.resolved_at = None
    await db_session.flush()

    # Add evidence change that would normally satisfy reopen path.
    db_session.add(
        IdentityMember(
            tenant_id=tenant.id,
            cluster_id=cluster_uuid,
            identity_id=identity.id,
            similarity=0.91,
            assigned_at=datetime.now(tz=UTC) + timedelta(minutes=1),
        )
    )
    await db_session.commit()

    skipped = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.9,
            member_similarity=0.9,
            confidence_score=0.9,
        ),
    )
    assert skipped.id == created.id
    assert skipped.status is SuggestionStatus.REJECTED

    count_stmt = (
        select(func.count())
        .select_from(IdentitySuggestion)
        .where(IdentitySuggestion.identity_id == identity.id)
        .where(IdentitySuggestion.suggested_cluster_id == cluster_uuid)
    )
    total_rows = int((await db_session.execute(count_stmt)).scalar_one())
    assert total_rows == 1


@pytest.mark.asyncio
async def test_rejected_suggestion_skips_when_context_unchanged(db_session, tenant) -> None:
    """Rejected suggestion should remain unchanged when no new evidence is present."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Known Label",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )

    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9101,
        media_url="http://example.test/9101.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    db_session.add(identity)
    await db_session.flush()

    repo = SqlAlchemySuggestionRepository(db_session)
    original = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.7,
            member_similarity=0.7,
            confidence_score=0.7,
        ),
    )
    rejected = await repo.update_status(str(tenant.id), original.id, SuggestionStatus.REJECTED)
    await db_session.commit()

    same = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.9,
            member_similarity=0.9,
            confidence_score=0.9,
        ),
    )

    assert same.id == rejected.id
    assert same.status is SuggestionStatus.REJECTED
    assert same.evidence_generation == 0


@pytest.mark.asyncio
async def test_rejected_suggestion_reopens_with_new_evidence(db_session, tenant) -> None:
    """Rejected suggestion should create a new pending generation when context changes."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Known Label",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )
    cluster_uuid = uuid.UUID(cluster.id)

    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9201,
        media_url="http://example.test/9201.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    rep_identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9202,
        media_url="http://example.test/9202.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    db_session.add_all([identity, rep_identity])
    await db_session.flush()

    repo = SqlAlchemySuggestionRepository(db_session)
    original = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.7,
            member_similarity=0.7,
            confidence_score=0.7,
        ),
    )
    rejected = await repo.update_status(str(tenant.id), original.id, SuggestionStatus.REJECTED)

    stmt = select(IdentitySuggestion).where(IdentitySuggestion.id == uuid.UUID(rejected.id))
    rejected_model = (await db_session.execute(stmt)).scalar_one()
    resolved_at = rejected_model.resolved_at
    assert resolved_at is not None

    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant.id,
            cluster_id=cluster_uuid,
            identity_id=rep_identity.id,
            embedding=_embedding(),
            quality_score=0.95,
            created_at=resolved_at + timedelta(milliseconds=1),
        )
    )
    await db_session.commit()

    reopened = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=cluster.id,
            representative_similarity=0.91,
            member_similarity=0.91,
            confidence_score=0.91,
        ),
    )

    assert reopened.id != rejected.id
    assert reopened.status is SuggestionStatus.PENDING
    assert reopened.evidence_generation == 1

    model_stmt = select(IdentitySuggestion).where(IdentitySuggestion.id == uuid.UUID(reopened.id))
    reopened_model = (await db_session.execute(model_stmt)).scalar_one()
    assert reopened_model.source == "backfill_new_evidence"


@pytest.mark.asyncio
async def test_rejected_suggestion_generation_increments_across_reopens(db_session, tenant) -> None:
    """Repeated rejection+context-change cycles should increment evidence_generation."""
    cluster_repo = SqlAlchemyClusterRepository(db_session)
    cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Known Label",
            is_labeled=True,
            identity_count=0,
            created_at=None,
        )
    )
    cluster_uuid = uuid.UUID(cluster.id)

    subject = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9301,
        media_url="http://example.test/9301.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    rep_a = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9302,
        media_url="http://example.test/9302.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    rep_b = MediaIdentity(
        tenant_id=tenant.id,
        media_id=9303,
        media_url="http://example.test/9303.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=_embedding(),
    )
    db_session.add_all([subject, rep_a, rep_b])
    await db_session.flush()

    repo = SqlAlchemySuggestionRepository(db_session)
    gen0 = await repo.create(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(subject.id),
            cluster_id=cluster.id,
            representative_similarity=0.7,
            member_similarity=0.7,
            confidence_score=0.7,
        ),
    )
    await repo.update_status(str(tenant.id), gen0.id, SuggestionStatus.REJECTED)
    await db_session.flush()

    gen0_model = (
        await db_session.execute(select(IdentitySuggestion).where(IdentitySuggestion.id == uuid.UUID(gen0.id)))
    ).scalar_one()
    assert gen0_model.resolved_at is not None

    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant.id,
            cluster_id=cluster_uuid,
            identity_id=rep_a.id,
            embedding=_embedding(),
            quality_score=0.95,
            created_at=gen0_model.resolved_at + timedelta(milliseconds=1),
        )
    )
    await db_session.commit()

    gen1 = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(subject.id),
            cluster_id=cluster.id,
            representative_similarity=0.8,
            member_similarity=0.8,
            confidence_score=0.8,
        ),
    )
    assert gen1.evidence_generation == 1

    await repo.update_status(str(tenant.id), gen1.id, SuggestionStatus.REJECTED)
    await db_session.flush()
    gen1_model = (
        await db_session.execute(select(IdentitySuggestion).where(IdentitySuggestion.id == uuid.UUID(gen1.id)))
    ).scalar_one()
    assert gen1_model.resolved_at is not None

    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant.id,
            cluster_id=cluster_uuid,
            identity_id=rep_b.id,
            embedding=_embedding(),
            quality_score=0.96,
            created_at=gen1_model.resolved_at + timedelta(milliseconds=1),
        )
    )
    await db_session.commit()

    gen2 = await repo.upsert_by_identity_cluster(
        str(tenant.id),
        SuggestionCreateData(
            identity_id=str(subject.id),
            cluster_id=cluster.id,
            representative_similarity=0.85,
            member_similarity=0.85,
            confidence_score=0.85,
        ),
    )
    assert gen2.evidence_generation == 2
    assert gen2.id != gen1.id

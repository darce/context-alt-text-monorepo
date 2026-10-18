"""Persistence tests for tenant purge service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from db.models import (
    AssignmentDecision,
    AtlasDispositionAction,
    AtlasRunStatus,
    AuditEvent,
    ClusterCentroid,
    ClusteringFeedback,
    ClusteringJobReport,
    ClusterMergeSuggestion,
    CurationReplayRecord,
    IdentityAtlasPoint,
    IdentityAtlasQueueDisposition,
    IdentityAtlasRun,
    IdentityCluster,
    IdentityClusterBlock,
    IdentityClusteringJob,
    IdentityClusterRepresentative,
    IdentityConstraint,
    IdentityMember,
    IdentityScanJob,
    IdentityScanJobItem,
    IdentitySuggestion,
    MediaIdentity,
    NameSuggestion,
    RecognitionEvent,
    RecognitionRun,
    Tenant,
)
from recognition.application.services.purge_service import PurgeRowScope, TenantPurgeService
from recognition.domain.suggestion import SuggestedLabelSource


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


@pytest.mark.asyncio
async def test_purge_service_deletes_disposed_state_only(db_session, tenant: Tenant) -> None:
    disposed_identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=201,
        media_url="http://example.test/disposed.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=_unit_embedding(),
        embedding_model="buffalo_l@insightface",
        disposed_at=datetime.now(tz=UTC),
    )
    active_identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=202,
        media_url="http://example.test/active.jpg",
        bbox_x=1,
        bbox_y=1,
        bbox_width=10,
        bbox_height=10,
        confidence=0.96,
        embedding=_unit_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    disposed_cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Disposed",
        identity_count=1,
        disposed_at=datetime.now(tz=UTC),
    )
    active_cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Active",
        identity_count=1,
    )
    db_session.add_all([disposed_identity, active_identity, disposed_cluster, active_cluster])
    await db_session.flush()

    disposed_member = IdentityMember(
        tenant_id=tenant.id,
        cluster_id=disposed_cluster.id,
        identity_id=disposed_identity.id,
        similarity=0.9,
    )
    active_member = IdentityMember(
        tenant_id=tenant.id,
        cluster_id=active_cluster.id,
        identity_id=active_identity.id,
        similarity=0.92,
    )
    disposed_rep = IdentityClusterRepresentative(
        tenant_id=tenant.id,
        cluster_id=disposed_cluster.id,
        identity_id=disposed_identity.id,
        embedding=_unit_embedding(),
        quality_score=0.9,
        disposed_at=datetime.now(tz=UTC),
    )
    active_rep = IdentityClusterRepresentative(
        tenant_id=tenant.id,
        cluster_id=active_cluster.id,
        identity_id=active_identity.id,
        embedding=_unit_embedding(),
        quality_score=0.91,
    )
    suggestion = IdentitySuggestion(
        tenant_id=tenant.id,
        identity_id=disposed_identity.id,
        suggested_cluster_id=disposed_cluster.id,
        representative_similarity=0.7,
        avg_member_similarity=0.72,
        confidence_score=0.71,
    )
    name_suggestion = NameSuggestion(
        tenant_id=tenant.id,
        cluster_id=disposed_cluster.id,
        suggested_name="Disposed Cluster",
        confidence_score=0.89,
    )
    merge_suggestion = ClusterMergeSuggestion(
        tenant_id=tenant.id,
        cluster_a_id=min(disposed_cluster.id, active_cluster.id),
        cluster_b_id=max(disposed_cluster.id, active_cluster.id),
        similarity=0.6,
    )
    block = IdentityClusterBlock(
        tenant_id=tenant.id,
        identity_id=disposed_identity.id,
        blocked_cluster_id=disposed_cluster.id,
        reason="test",
    )
    constraint = IdentityConstraint(
        tenant_id=tenant.id,
        identity_a=min(disposed_identity.id, active_identity.id),
        identity_b=max(disposed_identity.id, active_identity.id),
        constraint_type="cannot_link",
        source="test",
    )
    db_session.add_all(
        [
            disposed_member,
            active_member,
            disposed_rep,
            active_rep,
            suggestion,
            name_suggestion,
            merge_suggestion,
            block,
            constraint,
        ]
    )
    await db_session.flush()
    await db_session.execute(
        text(
            "INSERT INTO mv_identity_cluster_centroids (cluster_id, tenant_id, identity_count, centroid) "
            "VALUES (:cluster_id, :tenant_id, 1, NULL)"
        ),
        {"cluster_id": str(disposed_cluster.id), "tenant_id": str(tenant.id)},
    )
    await db_session.commit()

    service = TenantPurgeService(db_session)

    result = await service.purge_tenant_data(str(tenant.id), "api_key:test", scope="disposed")

    assert result["scope"] == "disposed"
    assert result["deleted_counts"]["media_identities"] == 1
    assert result["deleted_counts"]["identity_clusters"] == 1
    assert result["deleted_counts"]["name_suggestions"] == 1
    assert await db_session.get(MediaIdentity, disposed_identity.id) is None
    assert await db_session.get(IdentityCluster, disposed_cluster.id) is None
    assert await db_session.get(NameSuggestion, name_suggestion.id) is None
    assert await db_session.get(MediaIdentity, active_identity.id) is not None
    assert await db_session.get(IdentityCluster, active_cluster.id) is not None
    centroid_rows = (
        (await db_session.execute(select(ClusterCentroid).where(ClusterCentroid.tenant_id == tenant.id)))
        .scalars()
        .all()
    )
    assert len(centroid_rows) == 1
    assert centroid_rows[0].cluster_id == active_cluster.id

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["purge_started", "purge_completed"]


@pytest.mark.asyncio
async def test_purge_service_disposed_scope_skips_name_suggestions_without_disposed_clusters(
    db_session, tenant: Tenant
) -> None:
    cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Active",
        identity_count=1,
    )
    db_session.add(cluster)
    await db_session.flush()
    suggestion = NameSuggestion(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Orphan",
        source=SuggestedLabelSource.IDENTITY.value,
        confidence_score=0.9,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add(suggestion)
    await db_session.flush()

    service = TenantPurgeService(db_session)
    result = await service.purge_tenant_data(str(tenant.id), "api_key:test", scope="disposed")

    assert result["deleted_counts"]["name_suggestions"] == 0
    assert await db_session.get(NameSuggestion, suggestion.id) is not None


@pytest.mark.asyncio
async def test_purge_service_disposed_scope_with_nothing_disposed_deletes_nothing(db_session, tenant: Tenant) -> None:
    """An empty disposed scope must delete zero rows, never the whole tenant.

    Every dependency predicate resolves to an empty id list here. When the empty
    case returned ``None`` that reached ``_list_batch_ids`` as "no extra WHERE",
    so this purge wiped the tenant's live identities, clusters, members,
    representatives, constraints, blocks, and suggestions.
    """
    identity_a = MediaIdentity(
        tenant_id=tenant.id,
        media_id=901,
        media_url="http://example.test/live-a.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=_unit_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    identity_b = MediaIdentity(
        tenant_id=tenant.id,
        media_id=902,
        media_url="http://example.test/live-b.jpg",
        bbox_x=1,
        bbox_y=1,
        bbox_width=10,
        bbox_height=10,
        confidence=0.94,
        embedding=_unit_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    cluster_a = IdentityCluster(tenant_id=tenant.id, label="Live A", identity_count=1)
    cluster_b = IdentityCluster(tenant_id=tenant.id, label="Live B", identity_count=1)
    db_session.add_all([identity_a, identity_b, cluster_a, cluster_b])
    await db_session.flush()

    member = IdentityMember(
        tenant_id=tenant.id,
        cluster_id=cluster_a.id,
        identity_id=identity_a.id,
        similarity=0.99,
    )
    representative = IdentityClusterRepresentative(
        tenant_id=tenant.id,
        cluster_id=cluster_a.id,
        identity_id=identity_a.id,
        embedding=_unit_embedding(),
        quality_score=0.96,
    )
    constraint = IdentityConstraint(
        tenant_id=tenant.id,
        identity_a=min(identity_a.id, identity_b.id),
        identity_b=max(identity_a.id, identity_b.id),
        constraint_type="cannot_link",
        source="test",
    )
    block = IdentityClusterBlock(
        tenant_id=tenant.id,
        identity_id=identity_a.id,
        blocked_cluster_id=cluster_b.id,
        reason="test",
    )
    identity_suggestion = IdentitySuggestion(
        tenant_id=tenant.id,
        identity_id=identity_b.id,
        suggested_cluster_id=cluster_a.id,
        representative_similarity=0.8,
        avg_member_similarity=0.81,
        confidence_score=0.82,
    )
    merge_suggestion = ClusterMergeSuggestion(
        tenant_id=tenant.id,
        cluster_a_id=min(cluster_a.id, cluster_b.id),
        cluster_b_id=max(cluster_a.id, cluster_b.id),
        similarity=0.7,
    )
    name_suggestion = NameSuggestion(
        tenant_id=tenant.id,
        cluster_id=cluster_a.id,
        suggested_name="Live Cluster",
        source=SuggestedLabelSource.IDENTITY.value,
        confidence_score=0.83,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add_all(
        [member, representative, constraint, block, identity_suggestion, merge_suggestion, name_suggestion]
    )
    await db_session.flush()

    atlas_run = IdentityAtlasRun(
        tenant_id=tenant.id,
        embedding_model="buffalo_l@insightface",
        status=AtlasRunStatus.COMPLETE.value,
        params={"umap": {"n_neighbors": 15}, "score_recipe": "margin_v1"},
        point_count=1,
    )
    db_session.add(atlas_run)
    await db_session.flush()
    atlas_point = IdentityAtlasPoint(
        run_id=atlas_run.id,
        tenant_id=tenant.id,
        identity_id=identity_a.id,
        media_id=identity_a.media_id,
        cluster_id=None,
        x=-0.5,
        y=0.25,
        queue_rank=0,
        uncertainty={"margin": 0.12, "composite": 0.41},
    )
    db_session.add(atlas_point)
    await db_session.flush()
    atlas_disposition = IdentityAtlasQueueDisposition(
        run_id=atlas_run.id,
        point_id=atlas_point.id,
        tenant_id=tenant.id,
        action=AtlasDispositionAction.REVIEWED.value,
        actor="admin:atlas-curator",
    )
    db_session.add(atlas_disposition)
    await db_session.commit()

    service = TenantPurgeService(db_session)

    result = await service.purge_tenant_data(str(tenant.id), "api_key:test", scope="disposed")

    deleted_counts = result["deleted_counts"]
    assert all(count == 0 for count in deleted_counts.values()), deleted_counts

    for row, model in (
        (identity_a, MediaIdentity),
        (identity_b, MediaIdentity),
        (cluster_a, IdentityCluster),
        (cluster_b, IdentityCluster),
        (member, IdentityMember),
        (representative, IdentityClusterRepresentative),
        (constraint, IdentityConstraint),
        (block, IdentityClusterBlock),
        (identity_suggestion, IdentitySuggestion),
        (merge_suggestion, ClusterMergeSuggestion),
        (name_suggestion, NameSuggestion),
        (atlas_run, IdentityAtlasRun),
        (atlas_point, IdentityAtlasPoint),
        (atlas_disposition, IdentityAtlasQueueDisposition),
    ):
        assert await db_session.get(model, row.id) is not None, f"{model.__name__} was purged out of scope"


@pytest.mark.asyncio
async def test_purge_service_rejects_non_sentinel_predicate(db_session, tenant: Tenant) -> None:
    """A bare ``None`` predicate must fail loudly, not widen to a tenant-wide delete."""
    service = TenantPurgeService(db_session)
    primary_key = service._primary_key_column(MediaIdentity)

    with pytest.raises(TypeError, match="PurgeRowScope member"):
        await service._list_batch_ids(
            MediaIdentity,
            primary_key,
            MediaIdentity.tenant_id == tenant.id,
            None,
        )

    assert (
        await service._list_batch_ids(
            MediaIdentity,
            primary_key,
            MediaIdentity.tenant_id == tenant.id,
            PurgeRowScope.NO_ROWS,
        )
        == []
    )


@pytest.mark.asyncio
async def test_purge_service_all_scope_deletes_all_machine_state(db_session, tenant: Tenant) -> None:
    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=301,
        media_url="http://example.test/all.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=12,
        bbox_height=12,
        confidence=0.93,
        embedding=_unit_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    cluster = IdentityCluster(tenant_id=tenant.id, label="All", identity_count=1)
    job = IdentityScanJob(tenant_id=tenant.id, media_ids=[301], total_media=1)
    clustering_job = IdentityClusteringJob(tenant_id=tenant.id, status="completed")
    preexisting_audit = AuditEvent(
        tenant_id=tenant.id,
        event_type="policy_updated",
        actor="api_key:test",
        scope="tenant",
        payload={"retention_mode": "retain_all"},
    )
    db_session.add_all([identity, cluster, job, clustering_job, preexisting_audit])
    await db_session.flush()
    recognition_run = RecognitionRun(
        tenant_id=tenant.id,
        status="completed",
        scan_job_id=job.id,
        clustering_job_id=clustering_job.id,
    )
    curation_replay = CurationReplayRecord(
        tenant_id=tenant.id,
        idempotency_key="replay-1",
        result_status="applied",
    )
    db_session.add_all([recognition_run, curation_replay])
    await db_session.flush()

    db_session.add_all(
        [
            IdentityMember(tenant_id=tenant.id, cluster_id=cluster.id, identity_id=identity.id, similarity=0.99),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=identity.id,
                embedding=_unit_embedding(),
                quality_score=0.97,
            ),
            IdentitySuggestion(
                tenant_id=tenant.id,
                identity_id=identity.id,
                suggested_cluster_id=cluster.id,
                representative_similarity=0.8,
                avg_member_similarity=0.81,
                confidence_score=0.82,
            ),
            NameSuggestion(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                suggested_name="All Scope Cluster",
                confidence_score=0.83,
            ),
            IdentityScanJobItem(
                job_id=job.id,
                tenant_id=tenant.id,
                media_id=301,
                media_url="http://example.test/all.jpg",
            ),
            RecognitionEvent(
                tenant_id=tenant.id,
                run_id=recognition_run.id,
                event_type="assignment_applied",
            ),
            ClusteringFeedback(
                tenant_id=tenant.id,
                identity_id=identity.id,
                cluster_id=cluster.id,
                decision_type="accepted",
            ),
            AssignmentDecision(
                tenant_id=tenant.id,
                identity_id=str(identity.id),
                cluster_id=str(cluster.id),
                decision="accept",
                timestamp=datetime.now(tz=UTC),
            ),
            ClusteringJobReport(
                tenant_id=tenant.id,
                job_id="job-1",
                algorithm="hdbscan",
                started_at=datetime.now(tz=UTC),
                total_identities=1,
                accept_count=1,
                suggest_count=0,
                reject_count=0,
                clusters_created=1,
                success_rate=1.0,
                duration_ms=10.0,
                payload={"tenant_id": str(tenant.id)},
            ),
        ]
    )
    await db_session.commit()

    service = TenantPurgeService(db_session)

    result = await service.purge_tenant_data(str(tenant.id), "api_key:test", scope="all")

    assert result["deleted_counts"]["media_identities"] == 1
    assert result["deleted_counts"]["identity_scan_jobs"] == 1
    assert result["deleted_counts"]["identity_clustering_jobs"] == 1
    assert result["deleted_counts"]["recognition_events"] == 1
    assert result["deleted_counts"]["recognition_runs"] == 1
    assert result["deleted_counts"]["clustering_feedback"] == 1
    assert result["deleted_counts"]["assignment_decisions"] == 1
    assert result["deleted_counts"]["clustering_job_reports"] == 1
    assert result["deleted_counts"]["curation_replay_records"] == 1
    assert result["deleted_counts"]["name_suggestions"] == 1
    assert await db_session.get(MediaIdentity, identity.id) is None
    assert await db_session.get(IdentityCluster, cluster.id) is None
    assert await db_session.get(RecognitionRun, recognition_run.id) is None
    assert await db_session.get(CurationReplayRecord, curation_replay.id) is None
    refreshed_tenant = await db_session.get(Tenant, tenant.id)
    assert refreshed_tenant is not None
    assert refreshed_tenant.last_purge_at is not None
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["policy_updated", "purge_started", "purge_completed"]


@pytest.mark.asyncio
async def test_purge_service_batches_large_table_deletes(
    db_session,
    tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add_all(
        [
            MediaIdentity(
                tenant_id=tenant.id,
                media_id=400 + index,
                media_url=f"http://example.test/batch-{index}.jpg",
                bbox_x=index,
                bbox_y=index,
                bbox_width=10,
                bbox_height=10,
                confidence=0.9,
                embedding=_unit_embedding(),
                embedding_model="buffalo_l@insightface",
            )
            for index in range(5)
        ]
    )
    await db_session.commit()

    service = TenantPurgeService(db_session, batch_size=2)
    original = service._list_batch_ids
    media_identity_batches: list[int] = []

    async def instrumented_list_batch_ids(
        model,
        primary_key,
        tenant_predicate,
        extra_predicate=PurgeRowScope.ALL_TENANT_ROWS,
    ) -> list[object]:
        batch = await original(model, primary_key, tenant_predicate, extra_predicate)
        if model is MediaIdentity:
            media_identity_batches.append(len(batch))
        return batch

    monkeypatch.setattr(service, "_list_batch_ids", instrumented_list_batch_ids)

    result = await service.purge_tenant_data(str(tenant.id), "api_key:test", scope="all")

    assert result["deleted_counts"]["media_identities"] == 5
    assert media_identity_batches == [2, 2, 1, 0]
    remaining = (
        (await db_session.execute(select(MediaIdentity).where(MediaIdentity.tenant_id == tenant.id))).scalars().all()
    )
    assert remaining == []


@pytest.mark.asyncio
async def test_purge_service_rejects_invalid_scope(db_session, tenant: Tenant) -> None:
    service = TenantPurgeService(db_session)

    with pytest.raises(ValueError, match="invalid purge scope"):
        await service.purge_tenant_data(str(tenant.id), "api_key:test", scope="nope")


@pytest.mark.asyncio
async def test_purge_service_rejects_missing_tenant(db_session) -> None:
    service = TenantPurgeService(db_session)

    with pytest.raises(LookupError, match="tenant not found"):
        await service.purge_tenant_data(str(uuid4()), "api_key:test")

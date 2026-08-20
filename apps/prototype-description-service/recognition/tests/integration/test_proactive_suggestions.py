"""Integration tests for Proactive Label Suggestions (Phase 4).

Verifies that unlabeled clusters are surfaced as suggestions
and that identity removal triggers recalibration.
"""

from __future__ import annotations

import math
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import numpy as np
import pytest
from sqlalchemy import select

from db.models import MediaIdentity as MediaIdentityModel
from db.models.identity import IdentityCluster as IdentityClusterModel
from recognition.application.orchestration.job_service import JobService
from recognition.application.tasks.clustering import (
    run_background_backfill_suggestions,
    run_background_surface_suggestions,
)
from recognition.domain.cluster import IdentityCluster
from recognition.domain.repositories import SuggestionCreateData
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import SuggestionStatus
from recognition.infrastructure.repositories import SqlAlchemySuggestionRepository
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.routers.clusters_snapshot import get_top_unlabeled_clusters
from recognition.tests.unit.job_repo_stub import InMemoryJobRepo
from roster.application.curation_sync_service import CurationSyncService


@pytest.mark.asyncio
async def test_unlabeled_clusters_are_filtered_from_suggestions(db_session, tenant) -> None:
    """v4.12.0: Unlabeled clusters should NOT appear in pending suggestions.

    Suggestions targeting unconfirmed clusters remain in DB but are filtered
    at query time. When the cluster becomes confirmed, the suggestion resurfaces.
    """
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    # 1. Create a cluster (unlabeled, unconfirmed)
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
        embedding_model="buffalo_l@insightface",
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
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(suggestion_identity)
    await db_session.flush()

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

    # 4. List pending suggestions - should be empty because cluster is unconfirmed
    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)

    # 5. v4.12.0: Unlabeled cluster suggestions are filtered out
    assert len(suggestions) == 0


@pytest.mark.asyncio
async def test_stale_accepted_suggestion_is_relisted_for_review(db_session, tenant) -> None:
    """Accepted suggestions with no membership move should resurface for manual review."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    target_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Slate Willow",
            is_labeled=True,
            identity_count=1,
            created_at=None,
            user_confirmed=True,
        )
    )

    source_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
            user_confirmed=False,
        )
    )

    embedding = [0.0] * 512
    embedding[0] = 1.0
    identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=1003,
        media_url="http://example.test/1003.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=0.99,
        embedding=embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(identity)
    await db_session.flush()

    await member_repo.add_member(source_cluster.id, identity_id=str(identity.id), similarity=0.92)

    suggestion = await suggestion_repo.create(
        tenant_id=str(tenant.id),
        payload=SuggestionCreateData(
            identity_id=str(identity.id),
            cluster_id=target_cluster.id,
            representative_similarity=0.62,
            member_similarity=0.62,
            confidence_score=0.62,
            refreshed_at=None,
            source="test",
        ),
    )
    await suggestion_repo.update_status(str(tenant.id), suggestion.id, SuggestionStatus.ACCEPTED)
    await db_session.commit()

    pending = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)
    matches = [item for item in pending if item.id == suggestion.id]

    assert len(matches) == 1
    assert matches[0].status == SuggestionStatus.PENDING.value


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
        embedding_model="buffalo_l@insightface",
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


@pytest.mark.asyncio
async def test_background_surfacing_after_label_creates_suggestions(db_session, tenant) -> None:
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)

    labeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    rep_embedding = [0.0] * 512
    rep_embedding[0] = 1.0
    rep_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3001,
        media_url="http://example.test/3001.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=120,
        bbox_height=120,
        confidence=0.99,
        embedding=rep_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep_identity)
    await db_session.flush()
    await member_repo.add_member(labeled_cluster.id, identity_id=str(rep_identity.id), similarity=0.9)

    await cluster_repo.add_representative(
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=labeled_cluster.id,
            identity_id=str(rep_identity.id),
            embedding=np.asarray(rep_identity.embedding, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            tenant_id=str(tenant.id),
        )
    )

    unlabeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    match_component = math.sqrt(1.0 - 0.5**2)
    candidate_embedding = [0.0] * 512
    candidate_embedding[0] = 0.5
    candidate_embedding[1] = match_component
    candidate_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3002,
        media_url="http://example.test/3002.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=48,
        bbox_height=48,
        confidence=0.5,
        embedding=candidate_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(candidate_identity)
    await db_session.flush()
    await member_repo.add_member(unlabeled_cluster.id, identity_id=str(candidate_identity.id), similarity=0.5)
    await db_session.commit()

    updated = await cluster_service.update_cluster(
        labeled_cluster.id,
        str(tenant.id),
        label="Confirmed Label",
        surface_suggestions=False,
    )
    assert updated is not None

    @asynccontextmanager
    async def _session_factory():
        yield db_session

    async def _builder(*, session, tenant_id):  # noqa: ANN001
        return await dependencies.build_cluster_service(session=session, tenant_id=tenant_id)

    await run_background_surface_suggestions(
        str(tenant.id),
        labeled_cluster.id,
        "Confirmed Label",
        session_factory=_session_factory,
        cluster_service_builder=_builder,
    )
    await db_session.commit()

    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)
    assert any(
        suggestion.identity_id == str(candidate_identity.id) and suggestion.cluster_id == labeled_cluster.id
        for suggestion in suggestions
    )


@pytest.mark.asyncio
async def test_update_cluster_surfaces_suggestions_for_existing_unlabeled_singletons(db_session, tenant) -> None:
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)

    labeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    rep_embedding = [0.0] * 512
    rep_embedding[0] = 1.0
    rep_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3003,
        media_url="http://example.test/3003.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=120,
        bbox_height=120,
        confidence=0.99,
        embedding=rep_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep_identity)
    await db_session.flush()
    await member_repo.add_member(labeled_cluster.id, identity_id=str(rep_identity.id), similarity=0.9)

    await cluster_repo.add_representative(
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=labeled_cluster.id,
            identity_id=str(rep_identity.id),
            embedding=np.asarray(rep_identity.embedding, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            tenant_id=str(tenant.id),
        )
    )

    unlabeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
        )
    )

    match_component = math.sqrt(1.0 - 0.5**2)
    candidate_embedding = [0.0] * 512
    candidate_embedding[0] = 0.5
    candidate_embedding[1] = match_component
    candidate_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3004,
        media_url="http://example.test/3004.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=48,
        bbox_height=48,
        confidence=0.5,
        embedding=candidate_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(candidate_identity)
    await db_session.flush()
    await member_repo.add_member(unlabeled_cluster.id, identity_id=str(candidate_identity.id), similarity=0.5)
    await db_session.commit()

    updated = await cluster_service.update_cluster(
        labeled_cluster.id,
        str(tenant.id),
        label="Confirmed Label",
        surface_suggestions=True,
    )

    assert updated is not None

    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)
    assert any(
        suggestion.identity_id == str(candidate_identity.id) and suggestion.cluster_id == labeled_cluster.id
        for suggestion in suggestions
    )


@pytest.mark.asyncio
async def test_replayed_cluster_bind_curation_job_surfaces_singleton_suggestions(db_session, tenant) -> None:
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)
    job_service = JobService(
        repository=InMemoryJobRepo(),
        cluster_service=cluster_service,
        scan_service=SimpleNamespace(analyze_media=AsyncMock()),
    )

    labeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
            user_confirmed=False,
        )
    )

    rep_embedding = [0.0] * 512
    rep_embedding[0] = 1.0
    rep_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3005,
        media_url="http://example.test/3005.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=120,
        bbox_height=120,
        confidence=0.99,
        embedding=rep_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep_identity)
    await db_session.flush()
    await member_repo.add_member(labeled_cluster.id, identity_id=str(rep_identity.id), similarity=0.9)

    await cluster_repo.add_representative(
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=labeled_cluster.id,
            identity_id=str(rep_identity.id),
            embedding=np.asarray(rep_identity.embedding, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            tenant_id=str(tenant.id),
        )
    )

    unlabeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
            user_confirmed=False,
        )
    )

    match_component = math.sqrt(1.0 - 0.5**2)
    candidate_embedding = [0.0] * 512
    candidate_embedding[0] = 0.5
    candidate_embedding[1] = match_component
    candidate_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3006,
        media_url="http://example.test/3006.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=48,
        bbox_height=48,
        confidence=0.5,
        embedding=candidate_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(candidate_identity)
    await db_session.flush()
    await member_repo.add_member(unlabeled_cluster.id, identity_id=str(candidate_identity.id), similarity=0.5)
    await db_session.commit()

    persisted_cluster = await db_session.scalar(
        select(IdentityClusterModel).where(IdentityClusterModel.id == uuid.UUID(labeled_cluster.id))
    )
    assert persisted_cluster is not None
    base_version = int(persisted_cluster.updated_at.timestamp() * 1_000_000) if persisted_cluster.updated_at else 0
    result = await CurationSyncService(session=db_session, job_service=job_service).apply(
        tenant_id=str(tenant.id),
        operation=SimpleNamespace(
            operation_type="cluster_person_bound",
            entity_type="cluster",
            entity_key=labeled_cluster.id,
            idempotency_key="bind-curation-loop-singleton-idem",
            expected_base_version=base_version,
            local_revision=1,
            payload={
                "cluster_uuid": labeled_cluster.id,
                "person_uuid": str(uuid.uuid4()),
                "person_name": "Confirmed Label",
            },
        ),
    )

    assert result.status == "acknowledged"

    queued_jobs = list(cast(InMemoryJobRepo, job_service.repository).jobs.values())
    assert len(queued_jobs) == 1

    processed = await job_service.process_curation_job(
        queued_jobs[0].id,
        str(tenant.id),
        cluster_ids=[],
        session=db_session,
    )

    assert processed.status.name == "COMPLETED"

    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)
    assert any(
        suggestion.identity_id == str(candidate_identity.id) and suggestion.cluster_id == labeled_cluster.id
        for suggestion in suggestions
    )


@pytest.mark.asyncio
async def test_merge_cleanup_curation_job_surfaces_singleton_suggestions_and_deletes_source_cluster(
    db_session, tenant
) -> None:
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)
    job_service = JobService(
        repository=InMemoryJobRepo(),
        cluster_service=cluster_service,
        scan_service=SimpleNamespace(analyze_media=AsyncMock()),
    )

    target_embedding = [0.0] * 512
    target_embedding[0] = 1.0
    target_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3007,
        media_url="http://example.test/3007.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=120,
        bbox_height=120,
        confidence=0.99,
        embedding=target_embedding,
        embedding_model="buffalo_l@insightface",
    )
    source_embedding = [0.0] * 512
    source_embedding[1] = 1.0
    source_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3008,
        media_url="http://example.test/3008.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=72,
        bbox_height=72,
        confidence=0.95,
        embedding=source_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add_all([target_identity, source_identity])
    await db_session.flush()

    target_cluster = await cluster_service.create_cluster_for_identity(
        identity_id=str(target_identity.id),
        label="Confirmed Label",
        tenant_id=str(tenant.id),
    )
    source_cluster = await cluster_service.create_cluster_for_identity(
        identity_id=str(source_identity.id),
        label="Source Label",
        tenant_id=str(tenant.id),
    )

    unlabeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
            user_confirmed=False,
        )
    )
    match_component = math.sqrt(1.0 - 0.5**2)
    candidate_embedding = [0.0] * 512
    candidate_embedding[0] = 0.5
    candidate_embedding[1] = match_component
    candidate_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3009,
        media_url="http://example.test/3009.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=48,
        bbox_height=48,
        confidence=0.5,
        embedding=candidate_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(candidate_identity)
    await db_session.flush()
    await member_repo.add_member(unlabeled_cluster.id, identity_id=str(candidate_identity.id), similarity=0.5)
    await db_session.commit()

    merged = await cluster_service.merge_cluster(
        source_cluster_id=source_cluster.id,
        tenant_id=str(tenant.id),
        target_cluster_id=target_cluster.id,
        target_label="Confirmed Label",
        defer_recompute=True,
    )

    assert merged is not None
    assert target_cluster.id is not None
    assert source_cluster.id is not None

    job = await job_service.queue_curation_followup(
        tenant_id=str(tenant.id),
        cluster_ids=[target_cluster.id],
        source_cluster_id=source_cluster.id,
    )

    processed = await job_service.process_curation_job(
        job.id,
        str(tenant.id),
        cluster_ids=[],
        session=db_session,
    )

    assert processed.status.name == "COMPLETED"
    assert await cluster_repo.get_by_id(source_cluster.id) is None

    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)
    assert any(
        suggestion.identity_id == str(candidate_identity.id) and suggestion.cluster_id == target_cluster.id
        for suggestion in suggestions
    )


@pytest.mark.asyncio
async def test_background_backfill_surfaces_suggestions_for_later_batch_cluster(db_session, tenant) -> None:
    """Later-batch unlabeled clusters should receive suggestions against existing confirmed labels."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository
    suggestion_repo = SqlAlchemySuggestionRepository(db_session)

    # Batch 1: confirmed labeled cluster exists.
    labeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label="Slate Willow",
            is_labeled=True,
            identity_count=1,
            created_at=None,
            user_confirmed=True,
        )
    )
    rep_embedding = [0.0] * 512
    rep_embedding[0] = 1.0
    rep_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3101,
        media_url="http://example.test/3101.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=96,
        bbox_height=96,
        confidence=0.99,
        embedding=rep_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(rep_identity)
    await db_session.flush()
    await member_repo.add_member(labeled_cluster.id, identity_id=str(rep_identity.id), similarity=0.95)
    await cluster_repo.add_representative(
        ClusterRepresentative(
            id=str(uuid.uuid4()),
            cluster_id=labeled_cluster.id,
            identity_id=str(rep_identity.id),
            embedding=np.asarray(rep_identity.embedding, dtype=np.float32),
            created_at=datetime.now(tz=UTC),
            tenant_id=str(tenant.id),
        )
    )
    await db_session.commit()

    # Batch 2: new unlabeled cluster appears later.
    unlabeled_cluster = await cluster_repo.save(
        IdentityCluster(
            id=None,
            tenant_id=str(tenant.id),
            label=None,
            is_labeled=False,
            identity_count=1,
            created_at=None,
            user_confirmed=False,
        )
    )
    candidate_embedding = [0.0] * 512
    candidate_embedding[0] = 0.52
    candidate_embedding[1] = math.sqrt(1.0 - 0.52**2)
    candidate_identity = MediaIdentityModel(
        tenant_id=tenant.id,
        media_id=3102,
        media_url="http://example.test/3102.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=64,
        bbox_height=64,
        confidence=0.93,
        embedding=candidate_embedding,
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(candidate_identity)
    await db_session.flush()
    await member_repo.add_member(unlabeled_cluster.id, identity_id=str(candidate_identity.id), similarity=0.52)
    await db_session.commit()

    @asynccontextmanager
    async def _session_factory():
        yield db_session

    async def _builder(*, session, tenant_id):  # noqa: ANN001
        return await dependencies.build_cluster_service(session=session, tenant_id=tenant_id)

    assert unlabeled_cluster.id is not None
    await run_background_backfill_suggestions(
        str(tenant.id),
        [unlabeled_cluster.id],
        fallback_window_minutes=0,
        session_factory=_session_factory,
        cluster_service_builder=_builder,
    )
    await db_session.commit()

    suggestions = await suggestion_repo.list_pending_with_details(tenant_id=str(tenant.id), limit=10, offset=0)
    assert any(
        suggestion.identity_id == str(candidate_identity.id) and suggestion.cluster_id == labeled_cluster.id
        for suggestion in suggestions
    )


@pytest.mark.asyncio
async def test_top_unlabeled_cards_show_known_label_ctas_for_later_batch_clusters(db_session, tenant) -> None:
    """Later-batch unlabeled cards should infer known labels (Sable/Jen-style), including low confidence."""
    cluster_service = await dependencies.build_cluster_service(session=db_session, tenant_id=str(tenant.id))
    cluster_repo = cluster_service.assignment_writer.cluster_repository
    member_repo = cluster_service.assignment_writer.member_repository

    confirmed_specs = [
        ("Laura", 4001, [1.0] + [0.0] * 511),
        ("Sable", 4002, [0.0, 1.0] + [0.0] * 510),
        ("Jen", 4003, [0.0, 0.0, 1.0] + [0.0] * 509),
    ]
    expected_labels_by_unlabeled_id: dict[str, str] = {}

    for label, media_id, rep_embedding in confirmed_specs:
        labeled_cluster = await cluster_repo.save(
            IdentityCluster(
                id=None,
                tenant_id=str(tenant.id),
                label=label,
                is_labeled=True,
                identity_count=1,
                created_at=None,
                user_confirmed=True,
            )
        )
        rep_identity = MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=media_id,
            media_url=f"http://example.test/{media_id}.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=96,
            bbox_height=96,
            confidence=0.99,
            embedding=rep_embedding,
            embedding_model="buffalo_l@insightface",
        )
        db_session.add(rep_identity)
        await db_session.flush()
        await member_repo.add_member(labeled_cluster.id, identity_id=str(rep_identity.id), similarity=0.95)
        await cluster_repo.add_representative(
            ClusterRepresentative(
                id=str(uuid.uuid4()),
                cluster_id=labeled_cluster.id,
                identity_id=str(rep_identity.id),
                embedding=np.asarray(rep_identity.embedding, dtype=np.float32),
                created_at=datetime.now(tz=UTC),
                tenant_id=str(tenant.id),
            )
        )

    # Later-batch unlabeled clusters. Jen stays in the low-confidence UI band (<0.6) but above inference floor.
    unlabeled_specs = [
        ("Laura", 4101, [0.95, math.sqrt(1.0 - 0.95**2)] + [0.0] * 510),
        ("Sable", 4102, [0.0, 0.9, math.sqrt(1.0 - 0.9**2)] + [0.0] * 509),
        ("Jen", 4103, [0.0, 0.0, 0.55, math.sqrt(1.0 - 0.55**2)] + [0.0] * 508),
    ]

    for expected_label, media_id, embedding in unlabeled_specs:
        unlabeled_cluster = await cluster_repo.save(
            IdentityCluster(
                id=None,
                tenant_id=str(tenant.id),
                label=None,
                is_labeled=False,
                identity_count=1,
                created_at=None,
                user_confirmed=False,
            )
        )
        assert unlabeled_cluster.id is not None
        candidate_identity = MediaIdentityModel(
            tenant_id=tenant.id,
            media_id=media_id,
            media_url=f"http://example.test/{media_id}.jpg",
            bbox_x=0,
            bbox_y=0,
            bbox_width=64,
            bbox_height=64,
            confidence=0.93,
            embedding=embedding,
            embedding_model="buffalo_l@insightface",
        )
        db_session.add(candidate_identity)
        await db_session.flush()
        await member_repo.add_member(unlabeled_cluster.id, identity_id=str(candidate_identity.id), similarity=0.6)
        expected_labels_by_unlabeled_id[unlabeled_cluster.id] = expected_label

    await db_session.commit()

    top_unlabeled = await get_top_unlabeled_clusters(
        tenant_id=str(tenant.id),
        limit=10,
        min_identity_count=1,
        repo=cluster_repo,
        session=db_session,
    )

    by_id = {cluster.id: cluster for cluster in top_unlabeled}
    assert set(expected_labels_by_unlabeled_id).issubset(set(by_id))

    for cluster_id, expected_label in expected_labels_by_unlabeled_id.items():
        card = by_id[cluster_id]
        assert card.suggested_label == expected_label
        assert card.suggested_label_source == "similar_cluster"
        assert card.suggested_label_confidence is not None

    jen_cluster_id = next(cid for cid, label in expected_labels_by_unlabeled_id.items() if label == "Jen")
    jen_confidence = by_id[jen_cluster_id].suggested_label_confidence
    assert jen_confidence is not None
    assert jen_confidence < 0.6

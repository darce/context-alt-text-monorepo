"""Unit tests for machine-proposal suggestion scaffolding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ClusterMergeSuggestion,
    IdentityCluster,
    IdentityClusteringJob,
    IdentitySuggestion,
    MediaIdentity,
    Tenant,
)
from db.models import NameSuggestion as NameSuggestionModel
from recognition.domain.services.suggestion_extension_service import SuggestionExtensionService
from recognition.domain.suggestion import SuggestedLabelSource, SuggestionStatus
from recognition.infrastructure.repositories.merge_suggestion_repository import SqlAlchemyMergeSuggestionRepository
from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


async def _create_name_suggestions_table(db_session: AsyncSession) -> None:
    await db_session.run_sync(
        lambda sync_session: cast(Table, NameSuggestionModel.__table__).create(
            bind=sync_session.connection(), checkfirst=True
        )
    )


async def _create_cluster(
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    cluster_id: UUID | None = None,
    label: str | None = None,
    user_confirmed: bool = False,
) -> IdentityCluster:
    cluster = IdentityCluster(
        id=cluster_id or uuid4(),
        tenant_id=tenant.id,
        label=label,
        identity_count=1,
        user_confirmed=user_confirmed,
    )
    db_session.add(cluster)
    await db_session.flush()
    return cluster


async def _create_identity(
    db_session: AsyncSession, tenant: Tenant, *, identity_id: UUID | None = None
) -> MediaIdentity:
    identity = MediaIdentity(
        id=identity_id or uuid4(),
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/media-101.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=_unit_embedding(),
    )
    db_session.add(identity)
    await db_session.flush()
    return identity


@pytest.mark.asyncio
async def test_list_name_suggestions_filters_expired_and_confidence(db_session: AsyncSession, tenant: Tenant) -> None:
    await _create_name_suggestions_table(db_session)
    cluster = await _create_cluster(db_session, tenant)
    job = IdentityClusteringJob(tenant_id=tenant.id, status="completed", progress=1.0)
    db_session.add(job)
    await db_session.flush()

    now = datetime.now(tz=UTC)
    keep = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Avery Rhodes",
        confidence_score=0.92,
        source=SuggestedLabelSource.IDENTITY.value,
        source_job_id=job.id,
        expires_at=now + timedelta(days=2),
    )
    low_confidence = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Low Confidence",
        confidence_score=0.55,
        source=SuggestedLabelSource.ROSTER.value,
        expires_at=now + timedelta(days=2),
    )
    expired = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Expired",
        confidence_score=0.99,
        source=SuggestedLabelSource.SIMILAR_CLUSTER.value,
        expires_at=now - timedelta(minutes=1),
    )
    db_session.add_all([keep, low_confidence, expired])
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    suggestions = await service.list_name_suggestions(str(tenant.id), min_confidence=0.8)

    assert [item.suggested_name for item in suggestions] == ["Avery Rhodes"]
    assert suggestions[0].source is SuggestedLabelSource.IDENTITY
    assert suggestions[0].source_job_id == str(job.id)


@pytest.mark.asyncio
async def test_list_name_suggestions_orders_null_confidence_last(db_session: AsyncSession, tenant: Tenant) -> None:
    await _create_name_suggestions_table(db_session)
    cluster = await _create_cluster(db_session, tenant)

    db_session.add_all(
        [
            NameSuggestionModel(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                suggested_name="No Score",
                confidence_score=None,
                source=SuggestedLabelSource.NONE.value,
                expires_at=datetime.now(tz=UTC) + timedelta(days=1),
            ),
            NameSuggestionModel(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                suggested_name="Scored",
                confidence_score=0.88,
                source=SuggestedLabelSource.IDENTITY.value,
                expires_at=datetime.now(tz=UTC) + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    suggestions = await service.list_name_suggestions(str(tenant.id))

    assert [item.suggested_name for item in suggestions] == ["Scored", "No Score"]


@pytest.mark.asyncio
async def test_accept_name_suggestion_applies_cluster_label(db_session: AsyncSession, tenant: Tenant) -> None:
    await _create_name_suggestions_table(db_session)
    cluster = await _create_cluster(db_session, tenant, label=None, user_confirmed=False)
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Jordan Lee",
        confidence_score=0.88,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    accepted = await service.accept_name_suggestion(str(tenant.id), str(suggestion.id))

    await db_session.refresh(cluster)
    await db_session.refresh(suggestion)

    assert accepted.status is SuggestionStatus.ACCEPTED
    assert cluster.label == "Jordan Lee"
    assert cluster.user_confirmed is True
    assert cluster.confirmation_count == 1
    assert cluster.confirmation_source == "label"
    assert suggestion.resolution == SuggestionStatus.ACCEPTED.value


@pytest.mark.asyncio
async def test_bulk_accept_and_expire_stale_cover_assignment_and_merge(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    await _create_name_suggestions_table(db_session)
    identity = await _create_identity(db_session, tenant)
    cluster_a_id, cluster_b_id = sorted([uuid4(), uuid4()], key=str)
    cluster_a = await _create_cluster(db_session, tenant, cluster_id=cluster_a_id)
    cluster_b = await _create_cluster(db_session, tenant, cluster_id=cluster_b_id)

    now = datetime.now(tz=UTC)
    accepted_assignment = IdentitySuggestion(
        tenant_id=tenant.id,
        identity_id=identity.id,
        suggested_cluster_id=cluster_a.id,
        representative_similarity=0.84,
        avg_member_similarity=0.82,
        confidence_score=0.93,
        expires_at=now + timedelta(days=1),
    )
    stale_assignment = IdentitySuggestion(
        tenant_id=tenant.id,
        identity_id=identity.id,
        suggested_cluster_id=cluster_b.id,
        representative_similarity=0.73,
        avg_member_similarity=0.71,
        confidence_score=0.74,
        expires_at=now - timedelta(minutes=5),
        evidence_generation=1,
    )
    accepted_merge = ClusterMergeSuggestion(
        tenant_id=tenant.id,
        cluster_a_id=cluster_a.id,
        cluster_b_id=cluster_b.id,
        similarity=0.86,
        confidence_score=0.87,
        expires_at=now + timedelta(days=1),
    )
    stale_name = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster_a.id,
        suggested_name="Expired Name",
        confidence_score=0.75,
        source=SuggestedLabelSource.NONE.value,
        expires_at=now - timedelta(minutes=5),
    )
    db_session.add_all([accepted_assignment, stale_assignment, accepted_merge, stale_name])
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    assignment_result = await service.bulk_accept(str(tenant.id), suggestion_type="assignment", min_confidence=0.9)
    merge_result = await service.bulk_accept(str(tenant.id), suggestion_type="merge", min_confidence=0.8)
    expired_count = await service.expire_stale(str(tenant.id))
    await db_session.commit()

    refreshed_assignment = await db_session.get(IdentitySuggestion, accepted_assignment.id)
    refreshed_merge = await db_session.get(ClusterMergeSuggestion, accepted_merge.id)
    refreshed_stale_assignment = await db_session.get(IdentitySuggestion, stale_assignment.id)
    refreshed_stale_name = await db_session.get(NameSuggestionModel, stale_name.id)

    assert assignment_result == {"accepted_count": 1, "skipped_count": 0}
    assert merge_result == {"accepted_count": 1, "skipped_count": 0}
    assert expired_count == 2
    assert refreshed_assignment is not None
    assert refreshed_assignment.resolution == SuggestionStatus.ACCEPTED.value
    assert refreshed_merge is not None
    assert refreshed_merge.resolution == SuggestionStatus.ACCEPTED.value
    assert refreshed_stale_assignment is not None
    assert refreshed_stale_assignment.resolution == SuggestionStatus.EXPIRED.value
    assert refreshed_stale_name is not None
    assert refreshed_stale_name.resolution == SuggestionStatus.EXPIRED.value


def test_assignment_repository_maps_machine_proposal_metadata() -> None:
    repo = SqlAlchemySuggestionRepository(cast(AsyncSession, AsyncMock()))
    source_job_id = uuid4()
    model = IdentitySuggestion(
        id=uuid4(),
        tenant_id=uuid4(),
        identity_id=uuid4(),
        suggested_cluster_id=uuid4(),
        representative_similarity=0.81,
        avg_member_similarity=0.8,
        confidence_score=0.79,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        source_job_id=source_job_id,
        resolution=SuggestionStatus.PENDING.value,
    )

    suggestion = repo._to_domain(model)

    assert suggestion.confidence_score == pytest.approx(0.79)
    assert suggestion.expires_at == model.expires_at
    assert suggestion.source_job_id == str(source_job_id)


def test_merge_repository_maps_machine_proposal_metadata() -> None:
    repo = SqlAlchemyMergeSuggestionRepository(cast(AsyncSession, AsyncMock()))
    source_job_id = uuid4()
    cluster_a_id, cluster_b_id = sorted([uuid4(), uuid4()], key=str)
    model = ClusterMergeSuggestion(
        id=uuid4(),
        tenant_id=uuid4(),
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.82,
        confidence_score=0.9,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        source_job_id=source_job_id,
        resolution=SuggestionStatus.PENDING.value,
    )

    suggestion = repo._to_domain(model)

    assert suggestion.confidence_score == pytest.approx(0.9)
    assert suggestion.expires_at == model.expires_at
    assert suggestion.source_job_id == str(source_job_id)

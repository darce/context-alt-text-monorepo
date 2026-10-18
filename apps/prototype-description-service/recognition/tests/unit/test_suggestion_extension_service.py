"""Unit tests for machine-proposal suggestion scaffolding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ClusterMergeSuggestion,
    IdentityCluster,
    IdentityClusteringJob,
    IdentityClusterRepresentative,
    IdentityMember,
    IdentitySuggestion,
    MediaIdentity,
    Tenant,
)
from db.models import NameSuggestion as NameSuggestionModel
from recognition.domain.suggestion import BulkAcceptResult, SuggestedLabelSource, SuggestionStatus
from recognition.infrastructure.repositories.merge_suggestion_repository import SqlAlchemyMergeSuggestionRepository
from recognition.infrastructure.repositories.suggestion_repository import SqlAlchemySuggestionRepository
from recognition.infrastructure.services.suggestion_extension_service import SuggestionExtensionService


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


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
    db_session: AsyncSession,
    tenant: Tenant,
    *,
    identity_id: UUID | None = None,
    media_id: int = 101,
    media_url: str = "http://example.test/media-101.jpg",
    bbox_x: int = 0,
    bbox_y: int = 0,
) -> MediaIdentity:
    identity = MediaIdentity(
        id=identity_id or uuid4(),
        tenant_id=tenant.id,
        media_id=media_id,
        media_url=media_url,
        bbox_x=bbox_x,
        bbox_y=bbox_y,
        bbox_width=10,
        bbox_height=10,
        confidence=0.95,
        embedding=_unit_embedding(),
        embedding_model="buffalo_l@insightface",
    )
    db_session.add(identity)
    await db_session.flush()
    return identity


@pytest.mark.asyncio
async def test_list_name_suggestions_filters_expired_and_confidence(db_session: AsyncSession, tenant: Tenant) -> None:
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
async def test_list_name_suggestions_includes_eager_loaded_representatives(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant)
    identity = await _create_identity(db_session, tenant)
    db_session.add(
        IdentityClusterRepresentative(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            identity_id=identity.id,
            embedding=_unit_embedding(),
            quality_score=0.94,
            is_user_selected=True,
        )
    )
    db_session.add(
        NameSuggestionModel(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            suggested_name="Avery Rhodes",
            confidence_score=0.91,
            source=SuggestedLabelSource.IDENTITY.value,
            expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    suggestions = await service.list_name_suggestions(str(tenant.id))

    assert len(suggestions) == 1
    assert len(suggestions[0].representatives) == 1
    rep = suggestions[0].representatives[0]
    assert rep.media_id == 101
    assert rep.media_url == "http://example.test/media-101.jpg"
    assert (rep.bbox_x, rep.bbox_y, rep.bbox_width, rep.bbox_height) == (0, 0, 10, 10)


@pytest.mark.asyncio
async def test_list_name_suggestions_without_representatives_returns_empty_list(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant)
    db_session.add(
        NameSuggestionModel(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            suggested_name="No Reps",
            confidence_score=0.88,
            source=SuggestedLabelSource.ROSTER.value,
            expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    suggestions = await service.list_name_suggestions(str(tenant.id))

    assert len(suggestions) == 1
    assert suggestions[0].representatives == []


@pytest.mark.asyncio
async def test_list_name_suggestions_member_fallback_when_no_pinned_representative(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant)
    # Two members: canonical order is similarity DESC, assigned_at ASC.
    # Lower similarity is assigned earlier so a wrong ORDER BY would pick it.
    low_sim = await _create_identity(
        db_session,
        tenant,
        identity_id=uuid4(),
        media_id=201,
        media_url="http://example.test/media-201.jpg",
        bbox_x=1,
    )
    high_sim = await _create_identity(
        db_session,
        tenant,
        identity_id=uuid4(),
        media_id=101,
        media_url="http://example.test/media-101.jpg",
        bbox_x=2,
    )
    earlier = datetime.now(tz=UTC) - timedelta(hours=2)
    later = datetime.now(tz=UTC) - timedelta(hours=1)
    db_session.add(
        IdentityMember(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            identity_id=low_sim.id,
            similarity=0.80,
            assigned_at=earlier,
        )
    )
    db_session.add(
        IdentityMember(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            identity_id=high_sim.id,
            similarity=0.97,
            assigned_at=later,
        )
    )
    db_session.add(
        NameSuggestionModel(
            tenant_id=tenant.id,
            cluster_id=cluster.id,
            suggested_name="Fallback Face",
            confidence_score=0.9,
            source=SuggestedLabelSource.IDENTITY.value,
            expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    suggestions = await service.list_name_suggestions(str(tenant.id))

    assert len(suggestions) == 1
    reps = suggestions[0].representatives
    assert len(reps) >= 1
    # MUT-H: first fallback member must be highest-similarity (similarity DESC, assigned_at ASC).
    assert reps[0].identity_id == str(high_sim.id)
    assert reps[0].media_id == 101
    assert reps[0].media_url == "http://example.test/media-101.jpg"
    assert (reps[0].bbox_x, reps[0].bbox_y, reps[0].bbox_width, reps[0].bbox_height) == (2, 0, 10, 10)
    if len(reps) > 1:
        assert reps[1].identity_id == str(low_sim.id)


@pytest.mark.asyncio
async def test_list_name_suggestions_orders_null_confidence_last(db_session: AsyncSession, tenant: Tenant) -> None:
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
async def test_name_suggestions_skip_disposed_rows(db_session: AsyncSession, tenant: Tenant) -> None:
    cluster = await _create_cluster(db_session, tenant)
    active = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Active",
        confidence_score=0.88,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    disposed = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Disposed",
        confidence_score=0.99,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        disposed_at=datetime.now(tz=UTC),
    )
    db_session.add_all([active, disposed])
    await db_session.commit()

    service = SuggestionExtensionService(db_session)

    suggestions = await service.list_name_suggestions(str(tenant.id))
    assert [item.suggested_name for item in suggestions] == ["Active"]

    with pytest.raises(LookupError, match="name suggestion not found"):
        await service.accept_name_suggestion(str(tenant.id), str(disposed.id))


@pytest.mark.asyncio
async def test_name_suggestions_skip_disposed_clusters(db_session: AsyncSession, tenant: Tenant) -> None:
    active_cluster = await _create_cluster(db_session, tenant)
    disposed_cluster = await _create_cluster(db_session, tenant)
    disposed_cluster.disposed_at = datetime.now(tz=UTC)
    active = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=active_cluster.id,
        suggested_name="Active",
        confidence_score=0.88,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    disposed = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=disposed_cluster.id,
        suggested_name="Disposed Cluster",
        confidence_score=0.99,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add_all([active, disposed])
    await db_session.commit()

    service = SuggestionExtensionService(db_session)

    suggestions = await service.list_name_suggestions(str(tenant.id))
    assert [item.suggested_name for item in suggestions] == ["Active"]

    with pytest.raises(LookupError, match="cluster not found for suggestion"):
        await service.accept_name_suggestion(str(tenant.id), str(disposed.id))


@pytest.mark.asyncio
async def test_accept_name_suggestion_applies_cluster_label(db_session: AsyncSession, tenant: Tenant) -> None:
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
async def test_accept_name_suggestion_raises_on_label_conflict(db_session: AsyncSession, tenant: Tenant) -> None:
    cluster = await _create_cluster(db_session, tenant, label="Confirmed Name", user_confirmed=True)
    cluster.confirmation_count = 2
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Stale Name",
        confidence_score=0.88,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)

    with pytest.raises(ValueError, match="label conflict"):
        await service.accept_name_suggestion(str(tenant.id), str(suggestion.id))


@pytest.mark.asyncio
async def test_accept_name_suggestion_rejects_reserved_label_without_write(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    """E21-17-R1-PY47-4: reserved suggested_name must raise and leave cluster untouched."""
    from recognition.domain.cluster import ReservedClusterLabelError

    cluster = await _create_cluster(db_session, tenant, label="Before", user_confirmed=False)
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="cluster-9",
        confidence_score=0.88,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)

    with pytest.raises(ReservedClusterLabelError):
        await service.accept_name_suggestion(str(tenant.id), str(suggestion.id))

    await db_session.refresh(cluster)
    await db_session.refresh(suggestion)
    assert cluster.label == "Before"
    assert cluster.user_confirmed is False
    assert suggestion.resolution == SuggestionStatus.PENDING.value


@pytest.mark.asyncio
async def test_reject_name_suggestion_marks_row_rejected_without_changing_cluster(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant, label="Before", user_confirmed=False)
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="After",
        confidence_score=0.84,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    rejected = await service.reject_name_suggestion(str(tenant.id), str(suggestion.id))

    await db_session.refresh(cluster)
    await db_session.refresh(suggestion)

    assert rejected.status is SuggestionStatus.REJECTED
    assert cluster.label == "Before"
    assert cluster.user_confirmed is False
    assert suggestion.resolution == SuggestionStatus.REJECTED.value


@pytest.mark.asyncio
async def test_reject_name_suggestion_returns_expired_on_expired_suggestion(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant, label="Before", user_confirmed=False)
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="After",
        confidence_score=0.84,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=datetime.now(tz=UTC) - timedelta(hours=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    result = await service.reject_name_suggestion(str(tenant.id), str(suggestion.id))

    await db_session.refresh(suggestion)

    assert result.status is SuggestionStatus.EXPIRED
    assert suggestion.resolution == SuggestionStatus.EXPIRED.value


@pytest.mark.asyncio
async def test_reject_name_suggestion_returns_unchanged_on_already_resolved(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant, label="Before", user_confirmed=False)
    now = datetime.now(tz=UTC)
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="After",
        confidence_score=0.84,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=now + timedelta(days=1),
        resolution=SuggestionStatus.ACCEPTED.value,
        resolved_at=now - timedelta(hours=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    result = await service.reject_name_suggestion(str(tenant.id), str(suggestion.id))

    await db_session.refresh(suggestion)

    assert result.status is SuggestionStatus.ACCEPTED
    assert suggestion.resolution == SuggestionStatus.ACCEPTED.value


@pytest.mark.asyncio
async def test_bulk_accept_name_suggestions_deduplicates_cluster_updates(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant, label=None, user_confirmed=False)
    now = datetime.now(tz=UTC)
    db_session.add_all(
        [
            NameSuggestionModel(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                suggested_name="Primary Name",
                confidence_score=0.96,
                source=SuggestedLabelSource.IDENTITY.value,
                expires_at=now + timedelta(days=1),
            ),
            NameSuggestionModel(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                suggested_name="Secondary Name",
                confidence_score=0.91,
                source=SuggestedLabelSource.ROSTER.value,
                expires_at=now + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    result = await service.bulk_accept(str(tenant.id), suggestion_type="name", min_confidence=0.8)

    await db_session.refresh(cluster)

    assert isinstance(result, BulkAcceptResult)
    assert result.accepted_count == 1
    assert result.skipped_count == 1
    assert cluster.label == "Primary Name"
    assert cluster.user_confirmed is True


@pytest.mark.asyncio
async def test_bulk_accept_name_suggestions_skips_disposed_clusters(db_session: AsyncSession, tenant: Tenant) -> None:
    active_cluster = await _create_cluster(db_session, tenant, label=None, user_confirmed=False)
    disposed_cluster = await _create_cluster(db_session, tenant, label=None, user_confirmed=False)
    disposed_cluster.disposed_at = datetime.now(tz=UTC)
    now = datetime.now(tz=UTC)
    db_session.add_all(
        [
            NameSuggestionModel(
                tenant_id=tenant.id,
                cluster_id=active_cluster.id,
                suggested_name="Active Name",
                confidence_score=0.96,
                source=SuggestedLabelSource.IDENTITY.value,
                expires_at=now + timedelta(days=1),
            ),
            NameSuggestionModel(
                tenant_id=tenant.id,
                cluster_id=disposed_cluster.id,
                suggested_name="Disposed Name",
                confidence_score=0.99,
                source=SuggestedLabelSource.ROSTER.value,
                expires_at=now + timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    result = await service.bulk_accept(str(tenant.id), suggestion_type="name", min_confidence=0.8)

    await db_session.refresh(active_cluster)
    await db_session.refresh(disposed_cluster)

    assert result.accepted_count == 1
    assert result.skipped_count == 1
    assert active_cluster.label == "Active Name"
    assert disposed_cluster.label is None


@pytest.mark.asyncio
async def test_bulk_accept_name_skips_confirmed_cluster_with_conflicting_label(
    db_session: AsyncSession, tenant: Tenant
) -> None:
    cluster = await _create_cluster(db_session, tenant, label="Official Name", user_confirmed=True)
    now = datetime.now(tz=UTC)
    suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        suggested_name="Different Name",
        confidence_score=0.96,
        source=SuggestedLabelSource.IDENTITY.value,
        expires_at=now + timedelta(days=1),
    )
    db_session.add(suggestion)
    await db_session.commit()

    service = SuggestionExtensionService(db_session)
    result = await service.bulk_accept(str(tenant.id), suggestion_type="name", min_confidence=0.8)

    await db_session.refresh(cluster)
    await db_session.refresh(suggestion)

    assert result.accepted_count == 0
    assert result.skipped_count == 1
    assert cluster.label == "Official Name"
    assert suggestion.resolution == SuggestionStatus.PENDING.value


@pytest.mark.asyncio
async def test_list_pending_candidates_and_expire_stale_cover_assignment_and_merge(
    db_session: AsyncSession, tenant: Tenant
) -> None:
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
        confidence_score=None,
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
    assignment_candidates = await service.list_pending_assignment_candidates(str(tenant.id), min_confidence=0.9)
    merge_candidates = await service.list_pending_merge_candidates(str(tenant.id), min_confidence=0.8)
    expired_count = await service.expire_stale(str(tenant.id))
    await db_session.commit()

    refreshed_stale_assignment = await db_session.get(IdentitySuggestion, stale_assignment.id)
    refreshed_stale_name = await db_session.get(NameSuggestionModel, stale_name.id)

    # list_pending_* returns candidates without modifying status; side effects are HTTP-layer concerns
    assert len(assignment_candidates) == 1
    assert str(assignment_candidates[0].cluster_id) == str(cluster_a.id)
    assert len(merge_candidates) == 1
    assert str(merge_candidates[0].cluster_a_id) == str(cluster_a.id)
    assert expired_count == 2
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


def test_name_suggestion_representatives_default_empty() -> None:
    """E21-17-R1-MUT-I/J: pin construction defaults instead of ripping call-site guards.

    Call sites already pass representatives; the default_factory=[] contract is what
    partial construction relies on — pin it rather than chase None-guards.
    """
    from recognition.domain.suggestion import NameSuggestion
    from recognition.interface_adapters.http.schemas.responses import NameSuggestionResponse

    domain = NameSuggestion(
        id=str(uuid4()),
        cluster_id=str(uuid4()),
        suggested_name="Ada",
        source=SuggestedLabelSource.IDENTITY,
        status=SuggestionStatus.PENDING,
    )
    assert domain.representatives == []

    response = NameSuggestionResponse(
        id=str(uuid4()),
        cluster_id=str(uuid4()),
        suggested_name="Ada",
        source="identity",
        status="pending",
    )
    assert response.representatives == []


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

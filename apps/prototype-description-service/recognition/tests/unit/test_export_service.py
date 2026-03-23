"""Persistence tests for tenant export service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select

from db.models import (
    AuditEvent,
    ClusterMergeSuggestion,
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    IdentityScanJob,
    IdentityScanJobItem,
    IdentitySuggestion,
    MediaIdentity,
    Tenant,
)
from db.models import (
    NameSuggestion as NameSuggestionModel,
)
from recognition.domain.services.export_service import EXPORT_SCHEMA_VERSION, TenantExportService


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


@pytest.mark.asyncio
async def test_export_service_returns_portable_payload_and_records_audit_events(db_session, tenant: Tenant) -> None:
    identity_id = uuid4()
    cluster_a_id, cluster_b_id, cluster_c_id = sorted([uuid4(), uuid4(), uuid4()], key=str)
    disposed_identity_id = uuid4()

    identity = MediaIdentity(
        id=identity_id,
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/media-101.jpg",
        bbox_x=10,
        bbox_y=20,
        bbox_width=30,
        bbox_height=40,
        confidence=0.97,
        embedding=_unit_embedding(),
        pose_pitch=1.0,
        pose_yaw=2.0,
        pose_roll=3.0,
        quality_score=0.91,
        age=33,
        gender=1,
        image_phash="abc123",
    )
    disposed_identity = MediaIdentity(
        id=disposed_identity_id,
        tenant_id=tenant.id,
        media_id=102,
        media_url="http://example.test/media-102.jpg",
        bbox_x=11,
        bbox_y=21,
        bbox_width=31,
        bbox_height=41,
        confidence=0.98,
        embedding=_unit_embedding(),
        disposed_at=datetime.now(tz=UTC),
    )
    cluster = IdentityCluster(
        id=cluster_a_id,
        tenant_id=tenant.id,
        label="Cluster A",
        identity_count=1,
        representative_identity_id=identity_id,
        user_confirmed=True,
        confirmation_count=2,
        last_exported_snapshot_id=uuid4(),
    )
    peer_cluster = IdentityCluster(id=cluster_b_id, tenant_id=tenant.id, label="Cluster B", identity_count=0)
    disposed_cluster = IdentityCluster(
        id=cluster_c_id,
        tenant_id=tenant.id,
        label="Disposed Cluster",
        identity_count=1,
        representative_identity_id=disposed_identity_id,
        disposed_at=datetime.now(tz=UTC),
    )
    suggestion = IdentitySuggestion(
        tenant_id=tenant.id,
        identity_id=identity_id,
        suggested_cluster_id=cluster_a_id,
        representative_similarity=0.88,
        avg_member_similarity=0.84,
        confidence_score=0.85,
    )
    disposed_suggestion = IdentitySuggestion(
        tenant_id=tenant.id,
        identity_id=disposed_identity_id,
        suggested_cluster_id=cluster_c_id,
        representative_similarity=0.87,
        avg_member_similarity=0.83,
        confidence_score=0.82,
    )
    merge_suggestion = ClusterMergeSuggestion(
        tenant_id=tenant.id,
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        similarity=0.81,
    )
    name_suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster_a_id,
        suggested_name="Cluster A",
        confidence_score=0.77,
        source="identity",
        last_exported_snapshot_id=uuid4(),
    )
    disposed_name_suggestion = NameSuggestionModel(
        tenant_id=tenant.id,
        cluster_id=cluster_c_id,
        suggested_name="Disposed Cluster",
        confidence_score=0.79,
        source="identity",
    )
    disposed_merge_suggestion = ClusterMergeSuggestion(
        tenant_id=tenant.id,
        cluster_a_id=min(cluster_a_id, cluster_c_id),
        cluster_b_id=max(cluster_a_id, cluster_c_id),
        similarity=0.8,
    )
    job = IdentityScanJob(
        tenant_id=tenant.id,
        status="completed",
        media_ids=[101],
        total_media=1,
        processed_media=1,
        identities_detected=1,
    )
    db_session.add_all(
        [
            identity,
            disposed_identity,
            cluster,
            peer_cluster,
            disposed_cluster,
            suggestion,
            name_suggestion,
            disposed_name_suggestion,
            disposed_suggestion,
            merge_suggestion,
            disposed_merge_suggestion,
            job,
        ]
    )
    await db_session.flush()

    member = IdentityMember(
        tenant_id=tenant.id,
        cluster_id=cluster_a_id,
        identity_id=identity_id,
        similarity=0.99,
    )
    disposed_member = IdentityMember(
        tenant_id=tenant.id,
        cluster_id=cluster_c_id,
        identity_id=disposed_identity_id,
        similarity=0.97,
    )
    representative = IdentityClusterRepresentative(
        tenant_id=tenant.id,
        cluster_id=cluster_a_id,
        identity_id=identity_id,
        embedding=_unit_embedding(),
        quality_score=0.94,
        is_user_selected=True,
        last_exported_snapshot_id=uuid4(),
    )
    disposed_representative = IdentityClusterRepresentative(
        tenant_id=tenant.id,
        cluster_id=cluster_c_id,
        identity_id=disposed_identity_id,
        embedding=_unit_embedding(),
        quality_score=0.93,
        disposed_at=datetime.now(tz=UTC),
    )
    job_item = IdentityScanJobItem(
        job_id=job.id,
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/media-101.jpg",
        status="completed",
        identities_detected=1,
    )
    db_session.add_all([member, disposed_member, representative, disposed_representative, job_item])
    await db_session.commit()

    service = TenantExportService(db_session)

    payload = await service.export_tenant_data(str(tenant.id), "api_key:test")
    clusters = cast(list[dict[str, Any]], payload["clusters"])
    media_identities = cast(list[dict[str, Any]], payload["media_identities"])
    identity_suggestions = cast(list[dict[str, Any]], payload["identity_suggestions"])
    name_suggestions = cast(list[dict[str, Any]], payload["name_suggestions"])
    scan_jobs = cast(list[dict[str, Any]], payload["scan_jobs"])

    assert payload["tenant_id"] == str(tenant.id)
    assert payload["retention_mode"] == "retain_all"
    assert payload["exported_at"] is not None
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert len(clusters) == 2
    exported_cluster = next(cluster_item for cluster_item in clusters if cluster_item["id"] == str(cluster_a_id))
    assert exported_cluster["label"] == "Cluster A"
    assert exported_cluster["members"][0]["identity"]["media_url"] == "http://example.test/media-101.jpg"
    assert exported_cluster["representatives"][0]["is_pinned"] is True
    assert exported_cluster["representatives"][0]["identity"]["bbox"]["width"] == 30
    assert "embedding" not in exported_cluster["representatives"][0]["identity"]
    assert len(media_identities) == 1
    assert {cluster_item["id"] for cluster_item in clusters} == {str(cluster_a_id), str(cluster_b_id)}
    assert media_identities[0]["id"] == str(identity_id)
    assert identity_suggestions[0]["confidence_score"] == pytest.approx(0.85)
    assert len(identity_suggestions) == 1
    assert len(name_suggestions) == 1
    assert name_suggestions[0]["suggested_name"] == "Cluster A"
    assert name_suggestions[0]["resolution"] == "pending"
    assert name_suggestions[0]["last_exported_snapshot_id"] is not None
    assert name_suggestions[0]["disposed_at"] is None
    assert len(cast(list[dict[str, Any]], payload["cluster_merge_suggestions"])) == 1
    assert len(scan_jobs[0]["items"]) == 1

    refreshed_tenant = await db_session.get(Tenant, tenant.id)
    assert refreshed_tenant is not None
    assert refreshed_tenant.last_export_at is not None

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["export_started", "export_completed"]
    assert events[1].payload["cluster_count"] == 2
    assert events[1].payload["identity_count"] == 1
    assert events[1].payload["name_suggestion_count"] == 1


@pytest.mark.asyncio
async def test_export_service_omits_disposed_nested_cluster_state(db_session, tenant: Tenant) -> None:
    active_identity_id = uuid4()
    disposed_identity_id = uuid4()
    cluster_id = uuid4()

    db_session.add_all(
        [
            MediaIdentity(
                id=active_identity_id,
                tenant_id=tenant.id,
                media_id=201,
                media_url="http://example.test/active.jpg",
                bbox_x=1,
                bbox_y=2,
                bbox_width=3,
                bbox_height=4,
                confidence=0.99,
                embedding=_unit_embedding(),
            ),
            MediaIdentity(
                id=disposed_identity_id,
                tenant_id=tenant.id,
                media_id=202,
                media_url="http://example.test/disposed.jpg",
                bbox_x=5,
                bbox_y=6,
                bbox_width=7,
                bbox_height=8,
                confidence=0.91,
                embedding=_unit_embedding(),
                disposed_at=datetime.now(tz=UTC),
            ),
            IdentityCluster(
                id=cluster_id,
                tenant_id=tenant.id,
                label="Mixed",
                identity_count=2,
                representative_identity_id=disposed_identity_id,
            ),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=cluster_id,
                identity_id=active_identity_id,
                similarity=0.95,
            ),
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=cluster_id,
                identity_id=disposed_identity_id,
                similarity=0.85,
            ),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=cluster_id,
                identity_id=disposed_identity_id,
                embedding=_unit_embedding(),
                quality_score=0.9,
                disposed_at=datetime.now(tz=UTC),
            ),
        ]
    )
    await db_session.commit()

    service = TenantExportService(db_session)

    payload = await service.export_tenant_data(str(tenant.id), "api_key:test")
    clusters = cast(list[dict[str, Any]], payload["clusters"])
    exported_cluster = next(cluster_item for cluster_item in clusters if cluster_item["id"] == str(cluster_id))

    assert exported_cluster["identity_count"] == 1
    assert exported_cluster["representative_identity_id"] is None
    assert len(exported_cluster["members"]) == 1
    assert exported_cluster["members"][0]["identity_id"] == str(active_identity_id)
    assert exported_cluster["representatives"] == []


@pytest.mark.asyncio
async def test_export_service_rejects_missing_tenant(db_session) -> None:
    service = TenantExportService(db_session)

    with pytest.raises(LookupError, match="tenant not found"):
        await service.export_tenant_data(str(uuid4()), "api_key:test")

"""Integration tests for retention lifecycle flows."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from db.models import (
    AuditEvent,
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    IdentityScanJob,
    IdentityScanJobItem,
    MediaIdentity,
    NameSuggestion,
    Tenant,
)
from recognition.domain.services.export_service import EXPORT_SCHEMA_VERSION, TenantExportService
from recognition.domain.services.purge_service import TenantPurgeService
from recognition.domain.services.retention_policy_service import RetentionPolicyService
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository


def _unit_embedding() -> list[float]:
    return [1.0] + [0.0] * 511


@pytest.mark.asyncio
async def test_retention_export_then_purge_all_records_audit_and_clears_machine_state(
    db_session, tenant: Tenant
) -> None:
    policy = await RetentionPolicyService(db_session).update_policy(
        str(tenant.id),
        "purge_on_demand",
        "api_key:test",
    )
    assert policy["retention_mode"] == "purge_on_demand"

    identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=901,
        media_url="http://example.test/export-all.jpg",
        bbox_x=2,
        bbox_y=3,
        bbox_width=20,
        bbox_height=21,
        confidence=0.97,
        embedding=_unit_embedding(),
    )
    cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Retention export cluster",
        identity_count=1,
    )
    job = IdentityScanJob(
        tenant_id=tenant.id,
        status="completed",
        media_ids=[901],
        total_media=1,
        processed_media=1,
        identities_detected=1,
    )
    db_session.add_all([identity, cluster, job])
    await db_session.flush()

    cluster.representative_identity_id = identity.id
    db_session.add_all(
        [
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=identity.id,
                similarity=0.99,
            ),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                identity_id=identity.id,
                embedding=_unit_embedding(),
                quality_score=0.96,
                is_user_selected=True,
            ),
            NameSuggestion(
                tenant_id=tenant.id,
                cluster_id=cluster.id,
                suggested_name="Retention export cluster",
                confidence_score=0.84,
            ),
            IdentityScanJobItem(
                job_id=job.id,
                tenant_id=tenant.id,
                media_id=901,
                media_url="http://example.test/export-all.jpg",
                status="completed",
                identities_detected=1,
            ),
        ]
    )
    await db_session.commit()

    export_payload = await TenantExportService(db_session).export_tenant_data(str(tenant.id), "api_key:test")

    assert export_payload["tenant_id"] == str(tenant.id)
    assert export_payload["retention_mode"] == "purge_on_demand"
    assert export_payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert len(export_payload["clusters"]) == 1
    assert len(export_payload["media_identities"]) == 1
    assert len(export_payload["scan_jobs"]) == 1

    refreshed_tenant = await db_session.get(Tenant, tenant.id)
    assert refreshed_tenant is not None
    assert refreshed_tenant.last_export_at is not None

    purge_result = await TenantPurgeService(db_session).purge_tenant_data(str(tenant.id), "api_key:test", scope="all")

    assert purge_result["scope"] == "all"
    assert purge_result["deleted_counts"]["media_identities"] == 1
    assert purge_result["deleted_counts"]["identity_clusters"] == 1
    assert purge_result["deleted_counts"]["identity_scan_jobs"] == 1
    assert purge_result["deleted_counts"]["identity_scan_job_items"] == 1
    assert purge_result["deleted_counts"]["name_suggestions"] == 1
    assert await db_session.get(MediaIdentity, identity.id) is None
    assert await db_session.get(IdentityCluster, cluster.id) is None
    assert await db_session.get(IdentityScanJob, job.id) is None

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
    assert [event.event_type for event in events] == [
        "policy_updated",
        "export_started",
        "export_completed",
        "purge_started",
        "purge_completed",
    ]
    assert events[-1].payload["scope"] == "all"
    assert events[-1].payload["deleted_counts"]["media_identities"] == 1


@pytest.mark.asyncio
async def test_dispose_after_ack_then_purge_disposed_only_removes_acknowledged_snapshot_rows(
    db_session, tenant: Tenant
) -> None:
    tenant.retention_mode = "dispose_after_ack"

    exported_identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=801,
        media_url="http://example.test/exported.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.98,
        embedding=_unit_embedding(),
    )
    exported_cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Exported cluster",
        identity_count=1,
        representative_identity_id=exported_identity.id,
    )
    db_session.add_all([exported_identity, exported_cluster])
    await db_session.flush()

    db_session.add_all(
        [
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=exported_cluster.id,
                identity_id=exported_identity.id,
                similarity=0.99,
            ),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=exported_cluster.id,
                identity_id=exported_identity.id,
                embedding=_unit_embedding(),
                quality_score=0.95,
            ),
            NameSuggestion(
                tenant_id=tenant.id,
                cluster_id=exported_cluster.id,
                suggested_name="Exported cluster",
                confidence_score=0.84,
            ),
        ]
    )
    await db_session.commit()

    repository = SqlAlchemyClusterRepository(db_session)
    clusters, members, _snapshot_version, snapshot_generation_id = await repository.get_snapshot(
        str(tenant.id),
        stamp_export=True,
    )

    assert snapshot_generation_id is not None
    assert len(clusters) == 1
    assert len(members) == 1

    disposal_result = await RetentionPolicyService(db_session).apply_disposal_after_ack(
        tenant_id=str(tenant.id),
        snapshot_generation_id=snapshot_generation_id,
        actor="tenant:test",
    )

    assert disposal_result["retention_mode"] == "dispose_after_ack"
    assert disposal_result["disposed_counts"] == {
        "media_identities": 1,
        "identity_clusters": 1,
        "identity_cluster_representatives": 1,
        "name_suggestions": 1,
    }

    exported_identity_refreshed = await db_session.get(MediaIdentity, exported_identity.id)
    exported_cluster_refreshed = await db_session.get(IdentityCluster, exported_cluster.id)
    exported_name_suggestion_refreshed = (
        await db_session.execute(
            select(NameSuggestion).where(
                NameSuggestion.tenant_id == tenant.id,
                NameSuggestion.cluster_id == exported_cluster.id,
            )
        )
    ).scalar_one()
    exported_rep_refreshed = (
        await db_session.execute(
            select(IdentityClusterRepresentative).where(
                IdentityClusterRepresentative.tenant_id == tenant.id,
                IdentityClusterRepresentative.cluster_id == exported_cluster.id,
            )
        )
    ).scalar_one()
    assert exported_identity_refreshed is not None and exported_identity_refreshed.disposed_at is not None
    assert exported_cluster_refreshed is not None and exported_cluster_refreshed.disposed_at is not None
    assert exported_name_suggestion_refreshed.disposed_at is not None
    assert exported_rep_refreshed.disposed_at is not None

    surviving_identity = MediaIdentity(
        tenant_id=tenant.id,
        media_id=802,
        media_url="http://example.test/active.jpg",
        bbox_x=1,
        bbox_y=1,
        bbox_width=12,
        bbox_height=12,
        confidence=0.97,
        embedding=_unit_embedding(),
    )
    surviving_cluster = IdentityCluster(
        tenant_id=tenant.id,
        label="Active cluster",
        identity_count=1,
        representative_identity_id=surviving_identity.id,
    )
    db_session.add_all([surviving_identity, surviving_cluster])
    await db_session.flush()
    db_session.add_all(
        [
            IdentityMember(
                tenant_id=tenant.id,
                cluster_id=surviving_cluster.id,
                identity_id=surviving_identity.id,
                similarity=0.98,
            ),
            IdentityClusterRepresentative(
                tenant_id=tenant.id,
                cluster_id=surviving_cluster.id,
                identity_id=surviving_identity.id,
                embedding=_unit_embedding(),
                quality_score=0.94,
            ),
        ]
    )
    await db_session.commit()

    purge_result = await TenantPurgeService(db_session).purge_tenant_data(
        str(tenant.id),
        "tenant:test",
        scope="disposed",
    )

    assert purge_result["scope"] == "disposed"
    assert purge_result["deleted_counts"]["media_identities"] == 1
    assert purge_result["deleted_counts"]["identity_clusters"] == 1
    assert purge_result["deleted_counts"]["identity_cluster_representatives"] == 1
    assert await db_session.get(MediaIdentity, exported_identity.id) is None
    assert await db_session.get(IdentityCluster, exported_cluster.id) is None
    assert await db_session.get(MediaIdentity, surviving_identity.id) is not None
    assert await db_session.get(IdentityCluster, surviving_cluster.id) is not None

    (
        current_clusters,
        current_members,
        _current_snapshot_version,
        current_snapshot_generation_id,
    ) = await repository.get_snapshot(str(tenant.id))
    assert current_snapshot_generation_id is None
    assert len(current_clusters) == 1
    assert len(current_members) == 1
    assert current_clusters[0].id == str(surviving_cluster.id)

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == [
        "disposal_completed",
        "purge_started",
        "purge_completed",
    ]
    assert events[0].payload["snapshot_generation_id"] == snapshot_generation_id
    assert events[2].payload["scope"] == "disposed"

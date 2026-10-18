from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MediaIdentity as MediaIdentityModel
from db.models.identity import CurationReplayRecord, IdentityCluster, IdentityMember
from db.models.tenant import Tenant
from recognition.tests.fakes import FakeJobService
from roster.application.curation_sync_service import CurationSyncService


def _operation(
    operation_type: str,
    *,
    entity_key: str,
    idempotency_key: str,
    expected_base_version: int,
    payload: dict[str, object],
) -> SimpleNamespace:
    return SimpleNamespace(
        operation_type=operation_type,
        entity_type="cluster",
        entity_key=entity_key,
        idempotency_key=idempotency_key,
        expected_base_version=expected_base_version,
        local_revision=1,
        payload=payload,
    )


async def _create_tenant(session: AsyncSession) -> Tenant:
    tenant = Tenant(id=uuid4(), site_url="http://example.test")
    session.add(tenant)
    await session.commit()
    return tenant


async def _load_replay_record(
    session: AsyncSession,
    *,
    tenant_id,
    idempotency_key: str,
) -> CurationReplayRecord:
    result = await session.execute(
        select(CurationReplayRecord).where(
            CurationReplayRecord.tenant_id == tenant_id,
            CurationReplayRecord.idempotency_key == idempotency_key,
        )
    )
    record = result.scalar_one_or_none()
    assert isinstance(record, CurationReplayRecord)
    return record


@pytest.mark.asyncio
async def test_person_operations_acknowledge_as_noop(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    service = CurationSyncService(session=db_session)

    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=SimpleNamespace(
            operation_type="person_updated",
            entity_type="person",
            entity_key=str(uuid4()),
            idempotency_key="person-noop-idem",
            expected_base_version=0,
            local_revision=5,
            payload={"person_uuid": str(uuid4()), "name": "Updated Name"},
        ),
    )

    assert result.status == "acknowledged"
    assert result.backend_version == 0


@pytest.mark.asyncio
async def test_cluster_bind_acknowledges_and_is_idempotent(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=0)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    person_uuid = str(uuid4())
    operation = _operation(
        "cluster_person_bound",
        entity_key=str(cluster.id),
        idempotency_key="bind-idem-key",
        expected_base_version=base_version,
        payload={"cluster_uuid": str(cluster.id), "person_uuid": person_uuid},
    )

    job_service = FakeJobService()
    service = CurationSyncService(session=db_session, job_service=job_service)
    first_result = await service.apply(tenant_id=str(tenant.id), operation=operation)
    await db_session.commit()

    # Replay through a new service instance to verify DB-backed idempotency.
    second_result = await CurationSyncService(session=db_session).apply(tenant_id=str(tenant.id), operation=operation)

    await db_session.refresh(cluster)

    assert first_result.status == "acknowledged"
    assert second_result == first_result
    assert str(cluster.roster_id) == person_uuid
    assert cluster.label == "Unassigned"

    replay_count = await db_session.scalar(
        select(func.count()).select_from(CurationReplayRecord).where(CurationReplayRecord.tenant_id == tenant.id)
    )
    assert replay_count == 1

    replay_record = await _load_replay_record(
        db_session,
        tenant_id=tenant.id,
        idempotency_key="bind-idem-key",
    )
    assert replay_record.machine_payload_json == json.dumps(
        {
            "cluster_uuid": str(cluster.id),
            "label": "Unassigned",
            "operation_type": "cluster_person_bound",
            "person_uuid": person_uuid,
        },
        sort_keys=True,
    )
    assert replay_record.refresh_status == "queued"
    assert replay_record.refresh_requested_at is not None
    assert replay_record.refresh_completed_at is None


@pytest.mark.asyncio
async def test_cluster_bind_queues_refresh_followup_with_idempotency_key(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=0)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    fake_job_service = FakeJobService()

    result = await CurationSyncService(session=db_session, job_service=fake_job_service).apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_person_bound",
            entity_key=str(cluster.id),
            idempotency_key="bind-refresh-queue-idem",
            expected_base_version=base_version,
            payload={"cluster_uuid": str(cluster.id), "person_uuid": str(uuid4())},
        ),
    )

    assert result.status == "acknowledged"
    assert fake_job_service.calls == [
        {
            "method": "queue_curation_followup",
            "tenant_id": str(tenant.id),
            "cluster_ids": [str(cluster.id)],
            "identity_ids": [],
            "source_cluster_id": None,
            "refresh_idempotency_key": "bind-refresh-queue-idem",
        }
    ]


@pytest.mark.asyncio
async def test_replayed_bind_queues_followup_once(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=0)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    operation = _operation(
        "cluster_person_bound",
        entity_key=str(cluster.id),
        idempotency_key="bind-refresh-replay-idem",
        expected_base_version=base_version,
        payload={"cluster_uuid": str(cluster.id), "person_uuid": str(uuid4())},
    )

    first_job_service = FakeJobService()
    first_result = await CurationSyncService(session=db_session, job_service=first_job_service).apply(
        tenant_id=str(tenant.id),
        operation=operation,
    )
    await db_session.commit()

    replay_job_service = FakeJobService()
    replay_result = await CurationSyncService(session=db_session, job_service=replay_job_service).apply(
        tenant_id=str(tenant.id),
        operation=operation,
    )

    assert replay_result == first_result
    assert first_job_service.calls == [
        {
            "method": "queue_curation_followup",
            "tenant_id": str(tenant.id),
            "cluster_ids": [str(cluster.id)],
            "identity_ids": [],
            "source_cluster_id": None,
            "refresh_idempotency_key": "bind-refresh-replay-idem",
        }
    ]
    assert replay_job_service.calls == []


@pytest.mark.asyncio
async def test_cluster_bind_queues_refresh_followup_with_bound_identity_ids(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=1)
    bound_identity = MediaIdentityModel(
        id=uuid4(),
        tenant_id=tenant.id,
        media_id=101,
        media_url="http://example.test/media/101.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=1,
        bbox_height=1,
        confidence=1.0,
        embedding=[0.0] * 512,
        embedding_model="buffalo_l@insightface",
    )
    cluster_member = IdentityMember(
        tenant_id=tenant.id,
        cluster_id=cluster.id,
        identity_id=bound_identity.id,
        similarity=0.99,
    )
    db_session.add_all([cluster, bound_identity, cluster_member])
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    fake_job_service = FakeJobService()

    result = await CurationSyncService(session=db_session, job_service=fake_job_service).apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_person_bound",
            entity_key=str(cluster.id),
            idempotency_key="bind-refresh-identity-idem",
            expected_base_version=base_version,
            payload={"cluster_uuid": str(cluster.id), "person_uuid": str(uuid4())},
        ),
    )

    assert result.status == "acknowledged"
    assert fake_job_service.calls == [
        {
            "method": "queue_curation_followup",
            "tenant_id": str(tenant.id),
            "cluster_ids": [str(cluster.id)],
            "identity_ids": [str(bound_identity.id)],
            "source_cluster_id": None,
            "refresh_idempotency_key": "bind-refresh-identity-idem",
        }
    ]


@pytest.mark.asyncio
async def test_cluster_unbind_marks_refresh_not_applicable_and_skips_followup_queue(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    person_uuid = uuid4()
    cluster = IdentityCluster(
        id=uuid4(),
        tenant_id=tenant.id,
        label="Known Person",
        identity_count=1,
        roster_id=person_uuid,
    )
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    fake_job_service = FakeJobService()

    result = await CurationSyncService(session=db_session, job_service=fake_job_service).apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_person_unbound",
            entity_key=str(cluster.id),
            idempotency_key="unbind-refresh-status-idem",
            expected_base_version=base_version,
            payload={"cluster_uuid": str(cluster.id), "person_uuid": str(person_uuid)},
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    replay_record = await _load_replay_record(
        db_session,
        tenant_id=tenant.id,
        idempotency_key="unbind-refresh-status-idem",
    )

    assert result.status == "acknowledged"
    assert cluster.roster_id is None
    assert replay_record.refresh_status == "not_applicable"
    assert replay_record.refresh_requested_at is None
    assert replay_record.refresh_completed_at is None
    assert fake_job_service.calls == []


@pytest.mark.asyncio
async def test_cluster_bind_replay_uses_authoritative_person_name_when_provided(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Stale Label", identity_count=1)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    person_uuid = str(uuid4())

    result = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_person_bound",
            entity_key=str(cluster.id),
            idempotency_key="bind-person-name-idem",
            expected_base_version=base_version,
            payload={
                "cluster_uuid": str(cluster.id),
                "person_uuid": person_uuid,
                "person_name": "Known Person",
            },
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert result.status == "acknowledged"
    assert str(cluster.roster_id) == person_uuid
    assert cluster.label == "Known Person"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "person_name_payload",
    [{}, {"person_name": ""}, {"person_name": "   "}],
)
async def test_cluster_bind_preserves_existing_label_when_person_name_missing_or_blank(
    db_session: AsyncSession,
    person_name_payload: dict[str, str],
) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Frank", identity_count=1)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    person_uuid = str(uuid4())

    result = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_person_bound",
            entity_key=str(cluster.id),
            idempotency_key=f"bind-person-name-fallback-{person_name_payload.get('person_name', 'missing') or 'blank'}",
            expected_base_version=base_version,
            payload={
                "cluster_uuid": str(cluster.id),
                "person_uuid": person_uuid,
                **person_name_payload,
            },
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert result.status == "acknowledged"
    assert str(cluster.roster_id) == person_uuid
    assert cluster.label == "Frank"


@pytest.mark.asyncio
async def test_cluster_bind_conflicts_when_expected_base_is_stale(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Assigned", identity_count=1)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    stale_base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    cluster.updated_at = datetime.now(tz=UTC) + timedelta(microseconds=30)
    await db_session.commit()
    await db_session.refresh(cluster)

    service = CurationSyncService(session=db_session)
    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_person_bound",
            entity_key=str(cluster.id),
            idempotency_key="stale-idem-key",
            expected_base_version=stale_base_version,
            payload={"cluster_uuid": str(cluster.id), "person_uuid": str(uuid4())},
        ),
    )

    assert result.status == "conflict"
    assert result.conflict_code == "version_conflict"
    assert result.backend_version >= stale_base_version
    assert result.machine_payload == {
        "cluster_uuid": str(cluster.id),
        "current_roster_id": None,
        "dismissed": False,
        "label": "Assigned",
    }


@pytest.mark.asyncio
async def test_cluster_bind_does_not_persist_replay_row_when_queue_enqueue_fails(db_session: AsyncSession) -> None:
    class ExplodingJobService:
        async def queue_curation_followup(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("queue boom")

    tenant = await _create_tenant(db_session)
    tenant_id = tenant.id
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=0)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0

    with pytest.raises(RuntimeError, match="queue boom"):
        await CurationSyncService(session=db_session, job_service=ExplodingJobService()).apply(
            tenant_id=str(tenant.id),
            operation=_operation(
                "cluster_person_bound",
                entity_key=str(cluster.id),
                idempotency_key="bind-enqueue-fail-idem",
                expected_base_version=base_version,
                payload={"cluster_uuid": str(cluster.id), "person_uuid": str(uuid4())},
            ),
        )

    await db_session.rollback()
    replay_count = await db_session.scalar(
        select(func.count())
        .select_from(CurationReplayRecord)
        .where(
            CurationReplayRecord.tenant_id == tenant_id,
            CurationReplayRecord.idempotency_key == "bind-enqueue-fail-idem",
        )
    )
    await db_session.refresh(cluster)

    assert replay_count == 0
    assert cluster.roster_id is None


@pytest.mark.asyncio
async def test_person_deleted_acknowledges_without_mutating_cluster_bindings(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    person_uuid = uuid4()
    keep_uuid = uuid4()
    bound_cluster = IdentityCluster(
        id=uuid4(), tenant_id=tenant.id, roster_id=person_uuid, label="Bound", identity_count=1
    )
    keep_cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, roster_id=keep_uuid, label="Keep", identity_count=1)
    db_session.add_all([bound_cluster, keep_cluster])
    await db_session.commit()

    service = CurationSyncService(session=db_session)
    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=SimpleNamespace(
            operation_type="person_deleted",
            entity_type="person",
            entity_key=str(person_uuid),
            idempotency_key="person-delete-idem",
            expected_base_version=0,
            local_revision=1,
            payload={"person_uuid": str(person_uuid)},
        ),
    )
    await db_session.commit()
    await db_session.refresh(bound_cluster)
    await db_session.refresh(keep_cluster)

    assert result.status == "acknowledged"
    assert bound_cluster.roster_id == person_uuid
    assert keep_cluster.roster_id == keep_uuid


@pytest.mark.asyncio
async def test_cluster_dismiss_and_undismiss_replay_mutate_backend_state(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    roster_id = uuid4()
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Review", identity_count=1, roster_id=roster_id)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    service = CurationSyncService(session=db_session, job_service=FakeJobService())

    dismissed = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_dismissed",
            entity_key=str(cluster.id),
            idempotency_key="dismiss-idem",
            expected_base_version=base_version,
            payload={"cluster_uuid": str(cluster.id)},
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert dismissed.status == "acknowledged"
    assert cluster.dismissed_at is not None
    assert cluster.roster_id == roster_id

    undismissed = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_undismissed",
            entity_key=str(cluster.id),
            idempotency_key="undismiss-idem",
            expected_base_version=dismissed.backend_version,
            payload={"cluster_uuid": str(cluster.id)},
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert undismissed.status == "acknowledged"
    assert cluster.roster_id == roster_id
    assert cluster.dismissed_at is None


@pytest.mark.asyncio
async def test_cluster_label_updated_replay_mutates_backend_label(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=1)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    service = CurationSyncService(session=db_session, job_service=FakeJobService())

    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_label_updated",
            entity_key=str(cluster.id),
            idempotency_key="label-idem",
            expected_base_version=base_version,
            payload={"cluster_uuid": str(cluster.id), "label": "Known Person"},
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert result.status == "acknowledged"
    assert cluster.label == "Known Person"


@pytest.mark.asyncio
async def test_cluster_label_updated_is_idempotent(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Unassigned", identity_count=1)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    operation = _operation(
        "cluster_label_updated",
        entity_key=str(cluster.id),
        idempotency_key="label-idempotent",
        expected_base_version=base_version,
        payload={"cluster_uuid": str(cluster.id), "label": "Known Person"},
    )

    first_result = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply(
        tenant_id=str(tenant.id), operation=operation
    )
    await db_session.commit()
    await db_session.refresh(cluster)
    first_updated_at = cluster.updated_at

    second_result = await CurationSyncService(session=db_session).apply(tenant_id=str(tenant.id), operation=operation)
    await db_session.refresh(cluster)

    assert second_result == first_result
    assert cluster.label == "Known Person"
    assert cluster.updated_at == first_updated_at


@pytest.mark.asyncio
async def test_cluster_label_updated_conflicts_when_expected_base_is_stale(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Old", identity_count=1)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    stale_base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    cluster.label = "Newer"
    cluster.updated_at = datetime.now(tz=UTC) + timedelta(microseconds=30)
    await db_session.commit()
    await db_session.refresh(cluster)

    service = CurationSyncService(session=db_session)
    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_label_updated",
            entity_key=str(cluster.id),
            idempotency_key="label-stale-idem",
            expected_base_version=stale_base_version,
            payload={"cluster_uuid": str(cluster.id), "label": "Local Label"},
        ),
    )

    assert result.status == "conflict"
    assert result.conflict_code == "version_conflict"
    assert result.machine_payload == {
        "cluster_uuid": str(cluster.id),
        "current_roster_id": None,
        "dismissed": False,
        "label": "Newer",
    }


@pytest.mark.asyncio
async def test_cluster_label_updated_with_null_label_clears_backend_label(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant.id, label="Tory Guzman", identity_count=2)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    base_version = int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0
    service = CurationSyncService(session=db_session, job_service=FakeJobService())

    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_label_updated",
            entity_key=str(cluster.id),
            idempotency_key="label-clear-null",
            expected_base_version=base_version,
            payload={"cluster_uuid": str(cluster.id), "label": None},
        ),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert result.status == "acknowledged"
    assert cluster.label is None

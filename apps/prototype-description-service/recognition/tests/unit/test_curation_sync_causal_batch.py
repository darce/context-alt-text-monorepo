from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import CurationReplayRecord, IdentityCluster
from recognition.tests.fakes import FakeJobService
from recognition.tests.unit.test_curation_sync_service import (
    _create_tenant,
    _load_replay_record,
    _operation,
)
from roster.application.curation_sync_service import CurationSyncService

_PERSON_NAME = "Ellyn Heald"


async def _seed_cluster(session: AsyncSession, tenant_id: UUID, *, label: str = "Unassigned") -> IdentityCluster:
    cluster = IdentityCluster(id=uuid4(), tenant_id=tenant_id, label=label, identity_count=0)
    session.add(cluster)
    await session.commit()
    await session.refresh(cluster)
    return cluster


def _version_of(cluster: IdentityCluster) -> int:
    return int(cluster.updated_at.timestamp() * 1_000_000) if cluster.updated_at else 0


def _label_op(cluster_id: UUID, *, key: str, base: int) -> SimpleNamespace:
    return _operation(
        "cluster_label_updated",
        entity_key=str(cluster_id),
        idempotency_key=key,
        expected_base_version=base,
        payload={"cluster_uuid": str(cluster_id), "label": _PERSON_NAME},
    )


def _person_created_op(person_uuid: str, *, key: str, base: int) -> SimpleNamespace:
    return SimpleNamespace(
        operation_type="person_created",
        entity_type="person",
        entity_key=person_uuid,
        idempotency_key=key,
        expected_base_version=base,
        local_revision=1,
        payload={"person_uuid": person_uuid, "name": _PERSON_NAME},
    )


def _bind_op(cluster_id: UUID, person_uuid: str, *, key: str, base: int) -> SimpleNamespace:
    return _operation(
        "cluster_person_bound",
        entity_key=str(cluster_id),
        idempotency_key=key,
        expected_base_version=base,
        payload={"cluster_uuid": str(cluster_id), "person_uuid": person_uuid, "person_name": _PERSON_NAME},
    )


def _same_intent_batch(cluster_id: UUID, *, person_uuid: str, base: int, key_prefix: str) -> list[SimpleNamespace]:
    from uuid import uuid5

    intent_id = str(uuid5(cluster_id, key_prefix))
    operations = [
        _label_op(cluster_id, key=f"{key_prefix}-label", base=base),
        _person_created_op(person_uuid, key=f"{key_prefix}-person", base=base),
        _bind_op(cluster_id, person_uuid, key=f"{key_prefix}-bind", base=base),
    ]
    for operation in operations:
        operation.payload["curation_intent_id"] = intent_id
    return operations


@pytest.mark.asyncio
async def test_same_intent_label_person_created_and_bind_share_base_without_self_conflict(
    db_session: AsyncSession,
) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _seed_cluster(db_session, tenant.id)
    base = _version_of(cluster)
    person_uuid = str(uuid4())
    job_service = FakeJobService()

    results = await CurationSyncService(session=db_session, job_service=job_service).apply_batch(
        tenant_id=str(tenant.id),
        operations=_same_intent_batch(cluster.id, person_uuid=person_uuid, base=base, key_prefix="same-intent"),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert [(result.status, result.conflict_code) for result in results] == [
        ("acknowledged", None),
        ("acknowledged", None),
        ("acknowledged", None),
    ]
    assert str(cluster.roster_id) == person_uuid
    assert cluster.user_confirmed is True
    assert cluster.label == _PERSON_NAME

    bind_record = await _load_replay_record(db_session, tenant_id=tenant.id, idempotency_key="same-intent-bind")
    assert bind_record.result_status == "acknowledged"
    assert bind_record.refresh_status == "queued"
    assert bind_record.refresh_requested_at is not None
    assert [call for call in job_service.calls if call["refresh_idempotency_key"] == "same-intent-bind"] == [
        {
            "method": "queue_curation_followup",
            "tenant_id": str(tenant.id),
            "cluster_ids": [str(cluster.id)],
            "identity_ids": [],
            "source_cluster_id": None,
            "refresh_idempotency_key": "same-intent-bind",
        }
    ]


@pytest.mark.asyncio
async def test_same_intent_bind_with_post_label_base_acknowledges(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _seed_cluster(db_session, tenant.id)
    base = _version_of(cluster)
    person_uuid = str(uuid4())
    service = CurationSyncService(session=db_session, job_service=FakeJobService())

    prefix_results = await service.apply_batch(
        tenant_id=str(tenant.id),
        operations=[
            _label_op(cluster.id, key="post-label-label", base=base),
            _person_created_op(person_uuid, key="post-label-person", base=base),
        ],
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert [result.status for result in prefix_results] == ["acknowledged", "acknowledged"]
    post_label_base = _version_of(cluster)
    assert post_label_base > base

    result = await service.apply(
        tenant_id=str(tenant.id),
        operation=_bind_op(cluster.id, person_uuid, key="post-label-bind", base=post_label_base),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert result.status == "acknowledged"
    assert str(cluster.roster_id) == person_uuid
    assert cluster.user_confirmed is True


@pytest.mark.asyncio
async def test_single_bind_confirms_cluster_and_queues_durable_followup(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _seed_cluster(db_session, tenant.id)
    base = _version_of(cluster)
    person_uuid = str(uuid4())
    job_service = FakeJobService()

    result = await CurationSyncService(session=db_session, job_service=job_service).apply(
        tenant_id=str(tenant.id),
        operation=_bind_op(cluster.id, person_uuid, key="single-bind", base=base),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert result.status == "acknowledged"
    assert str(cluster.roster_id) == person_uuid
    assert cluster.user_confirmed is True

    record = await _load_replay_record(db_session, tenant_id=tenant.id, idempotency_key="single-bind")
    assert record.refresh_status == "queued"
    assert record.refresh_requested_at is not None
    assert job_service.calls == [
        {
            "method": "queue_curation_followup",
            "tenant_id": str(tenant.id),
            "cluster_ids": [str(cluster.id)],
            "identity_ids": [],
            "source_cluster_id": None,
            "refresh_idempotency_key": "single-bind",
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_same_intent_batch_replays_stored_results_without_requeue(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _seed_cluster(db_session, tenant.id)
    base = _version_of(cluster)
    person_uuid = str(uuid4())

    first = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply_batch(
        tenant_id=str(tenant.id),
        operations=_same_intent_batch(cluster.id, person_uuid=person_uuid, base=base, key_prefix="dup-intent"),
    )
    await db_session.commit()

    replay_job_service = FakeJobService()
    replay = await CurationSyncService(session=db_session, job_service=replay_job_service).apply_batch(
        tenant_id=str(tenant.id),
        operations=_same_intent_batch(cluster.id, person_uuid=person_uuid, base=base, key_prefix="dup-intent"),
    )
    await db_session.commit()

    assert replay == first
    assert replay_job_service.calls == []
    replay_count = await db_session.scalar(
        select(func.count()).select_from(CurationReplayRecord).where(CurationReplayRecord.tenant_id == tenant.id)
    )
    assert replay_count == 3


@pytest.mark.asyncio
async def test_unrelated_write_after_shared_base_still_conflicts_inside_batch(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _seed_cluster(db_session, tenant.id)
    base = _version_of(cluster)
    person_uuid = str(uuid4())

    # Unrelated concurrent writer: bumps the cluster without any curation replay record.
    cluster.label = "Renamed Elsewhere"
    cluster.updated_at = datetime.now(tz=UTC) + timedelta(microseconds=30)
    await db_session.commit()
    await db_session.refresh(cluster)

    results = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply_batch(
        tenant_id=str(tenant.id),
        operations=_same_intent_batch(cluster.id, person_uuid=person_uuid, base=base, key_prefix="stale-batch"),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    bind_result = results[2]
    assert bind_result.status == "conflict"
    assert bind_result.conflict_code == "version_conflict"
    assert bind_result.machine_payload == {
        "cluster_uuid": str(cluster.id),
        "current_roster_id": None,
        "dismissed": False,
        "label": "Renamed Elsewhere",
    }
    assert cluster.roster_id is None
    assert cluster.user_confirmed is False


@pytest.mark.asyncio
async def test_other_intent_write_after_shared_base_still_conflicts_bind(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _seed_cluster(db_session, tenant.id)
    base = _version_of(cluster)
    person_uuid = str(uuid4())
    service = CurationSyncService(session=db_session, job_service=FakeJobService())

    other_intent = await service.apply(
        tenant_id=str(tenant.id),
        operation=_operation(
            "cluster_label_updated",
            entity_key=str(cluster.id),
            idempotency_key="other-intent-label",
            expected_base_version=base,
            payload={"cluster_uuid": str(cluster.id), "label": "Other Device"},
        ),
    )
    assert other_intent.status == "acknowledged"
    await db_session.commit()

    bind = await service.apply(
        tenant_id=str(tenant.id),
        operation=_bind_op(cluster.id, person_uuid, key="stale-other-intent-bind", base=base),
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert bind.status == "conflict"
    assert bind.conflict_code == "version_conflict"
    assert bind.machine_payload == {
        "cluster_uuid": str(cluster.id),
        "current_roster_id": None,
        "dismissed": False,
        "label": "Other Device",
    }
    assert cluster.roster_id is None
    assert cluster.user_confirmed is False

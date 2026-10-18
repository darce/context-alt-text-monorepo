from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.identity import CurationReplayRecord, IdentityCluster
from recognition.tests.fakes import FakeJobService
from recognition.tests.unit.test_curation_sync_causal_batch import _same_intent_batch, _version_of
from recognition.tests.unit.test_curation_sync_service import _create_tenant, _load_replay_record
from roster.application.curation_sync_service import CurationSyncService
from roster.interface_adapters.http.curation_router import CurationSyncBatchRequest, CurationSyncRequest

_CORRECTION = "Current Correction"
_STALE_NAME = "Stale Client Label"
_MISSING = object()


async def _corrected_cluster(session: AsyncSession, tenant_id: UUID, *, confirmed: bool = True) -> IdentityCluster:
    cluster = IdentityCluster(
        id=uuid4(), tenant_id=tenant_id, label="Previous Correction", identity_count=0,
        roster_id=uuid4(), user_confirmed=confirmed,
    )
    session.add(cluster)
    await session.commit()
    await session.refresh(cluster)
    return cluster


def _op(
    cluster_id: UUID,
    *,
    kind: str,
    base: int,
    intent: object = _MISSING,
    revision: int = 1,
    person_uuid: str | None = None,
) -> CurationSyncRequest:
    payload: dict[str, object] = {"cluster_uuid": str(cluster_id)}
    if kind == "cluster_label_updated":
        payload["label"] = _CORRECTION
    elif kind == "cluster_person_bound":
        payload.update(person_uuid=person_uuid or str(uuid4()), person_name=_STALE_NAME)
    if intent is not _MISSING:
        payload["curation_intent_id"] = intent
    return CurationSyncRequest(
        operation_type=kind, entity_type="cluster", entity_key=str(cluster_id),
        idempotency_key=str(uuid4()), expected_base_version=base, local_revision=revision, payload=payload,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True], ids=["unconfirmed", "confirmed"])
@pytest.mark.parametrize(
    "provenance",
    ["missing-both", "missing-label", "missing-bind", "different", "malformed", "null", "blank"],
)
async def test_independent_label_then_stale_bind_requires_explicit_shared_uuid(
    db_session: AsyncSession, provenance: str, confirmed: bool,
) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _corrected_cluster(db_session, tenant.id, confirmed=confirmed)
    base = _version_of(cluster)
    prior_roster_id = cluster.roster_id
    shared = str(uuid4())
    label_intent, bind_intent = {
        "missing-both": (_MISSING, _MISSING),
        "missing-label": (_MISSING, shared),
        "missing-bind": (shared, _MISSING),
        "different": (shared, str(uuid4())),
        "malformed": ("not-a-uuid", "not-a-uuid"),
        "null": (None, None),
        "blank": ("", ""),
    }[provenance]
    label = _op(cluster.id, kind="cluster_label_updated", base=base, intent=label_intent)
    bind = _op(cluster.id, kind="cluster_person_bound", base=base, intent=bind_intent)
    batch = CurationSyncBatchRequest.model_validate_json(
        CurationSyncBatchRequest(operations=[label, bind]).model_dump_json()
    )
    jobs = FakeJobService()
    results = await CurationSyncService(session=db_session, job_service=jobs).apply_batch(
        tenant_id=str(tenant.id), operations=batch.operations,
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert results[0].status == "acknowledged"
    label_record = await _load_replay_record(db_session, tenant_id=tenant.id, idempotency_key=label.idempotency_key)
    assert label_record.result_status == "acknowledged"
    assert label_record.backend_version > base
    # Equal base/revision fields belong to independent clients too; preserve the acknowledged correction.
    assert (
        results[1].status, results[1].conflict_code, cluster.label, cluster.roster_id, cluster.user_confirmed,
    ) == ("conflict", "version_conflict", _CORRECTION, prior_roster_id, confirmed)
    assert _version_of(cluster) == label_record.backend_version
    assert results[1].machine_payload == {
        "cluster_uuid": str(cluster.id), "current_roster_id": str(prior_roster_id),
        "dismissed": False, "label": _CORRECTION,
    }
    bind_record = await _load_replay_record(db_session, tenant_id=tenant.id, idempotency_key=bind.idempotency_key)
    assert bind_record.result_status == "conflict"
    assert not [call for call in jobs.calls if call["refresh_idempotency_key"] == bind.idempotency_key]


@pytest.mark.asyncio
async def test_explicit_shared_intent_ack_replay_and_durable_followup_control(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _corrected_cluster(db_session, tenant.id)
    person_uuid = str(uuid4())
    operations = [
        CurationSyncRequest.model_validate(vars(operation))
        for operation in _same_intent_batch(
            cluster.id, person_uuid=person_uuid, base=_version_of(cluster), key_prefix="provenance-control",
        )
    ]
    intents = {operation.payload["curation_intent_id"] for operation in operations}
    assert len(intents) == 1
    UUID(intents.pop())
    jobs = FakeJobService()
    first = await CurationSyncService(session=db_session, job_service=jobs).apply_batch(
        tenant_id=str(tenant.id), operations=operations,
    )
    await db_session.commit()
    await db_session.refresh(cluster)

    assert [(result.status, result.conflict_code) for result in first] == [("acknowledged", None)] * 3
    assert (str(cluster.roster_id), cluster.label, cluster.user_confirmed) == (person_uuid, "Ellyn Heald", True)
    record = await _load_replay_record(db_session, tenant_id=tenant.id, idempotency_key=operations[2].idempotency_key)
    assert record.result_status == "acknowledged"
    assert record.refresh_status == "queued"
    assert record.refresh_requested_at is not None
    assert len([call for call in jobs.calls if call["refresh_idempotency_key"] == operations[2].idempotency_key]) == 1

    replay_jobs = FakeJobService()
    replay = await CurationSyncService(session=db_session, job_service=replay_jobs).apply_batch(
        tenant_id=str(tenant.id), operations=operations,
    )
    await db_session.commit()
    assert replay == first
    assert replay_jobs.calls == []
    assert await db_session.scalar(
        select(func.count()).select_from(CurationReplayRecord).where(CurationReplayRecord.tenant_id == tenant.id)
    ) == 3


@pytest.mark.asyncio
async def test_shared_intent_second_bind_cannot_reuse_consumed_label_control(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _corrected_cluster(db_session, tenant.id)
    base, intent = _version_of(cluster), str(uuid4())
    person_uuid = str(uuid4())
    operations = [
        _op(cluster.id, kind="cluster_label_updated", base=base, intent=intent),
        _op(cluster.id, kind="cluster_person_bound", base=base, intent=intent, person_uuid=person_uuid),
        _op(cluster.id, kind="cluster_person_bound", base=base, intent=intent),
    ]
    results = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply_batch(
        tenant_id=str(tenant.id), operations=operations,
    )
    await db_session.commit()
    await db_session.refresh(cluster)
    assert [(result.status, result.conflict_code) for result in results] == [
        ("acknowledged", None), ("acknowledged", None), ("conflict", "version_conflict"),
    ]
    assert (str(cluster.roster_id), cluster.label, cluster.user_confirmed) == (person_uuid, _STALE_NAME, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("replay_label", [False, True], ids=["bind-only", "cached-label"])
async def test_shared_intent_cannot_continue_across_batches_control(
    db_session: AsyncSession, replay_label: bool,
) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _corrected_cluster(db_session, tenant.id)
    base, intent, prior_roster_id = _version_of(cluster), str(uuid4()), cluster.roster_id
    label = _op(cluster.id, kind="cluster_label_updated", base=base, intent=intent)
    bind = _op(cluster.id, kind="cluster_person_bound", base=base, intent=intent)
    service = CurationSyncService(session=db_session, job_service=FakeJobService())
    first = await service.apply_batch(tenant_id=str(tenant.id), operations=[label])
    await db_session.commit()
    assert first[0].status == "acknowledged"
    second = await service.apply_batch(tenant_id=str(tenant.id), operations=[label, bind] if replay_label else [bind])
    await db_session.commit()
    await db_session.refresh(cluster)
    assert (second[-1].status, second[-1].conflict_code) == ("conflict", "version_conflict")
    assert (cluster.label, cluster.roster_id, cluster.user_confirmed) == (_CORRECTION, prior_roster_id, True)


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["zero-revision", "different-revision", "different-base"])
async def test_shared_uuid_does_not_override_base_and_revision_control(
    db_session: AsyncSession, boundary: str,
) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _corrected_cluster(db_session, tenant.id)
    base, intent, prior_roster_id = _version_of(cluster), str(uuid4()), cluster.roster_id
    label_revision, bind_revision, bind_base = {
        "zero-revision": (0, 0, base),
        "different-revision": (1, 2, base),
        "different-base": (1, 1, base - 1),
    }[boundary]
    results = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply_batch(
        tenant_id=str(tenant.id), operations=[
            _op(cluster.id, kind="cluster_label_updated", base=base, intent=intent, revision=label_revision),
            _op(cluster.id, kind="cluster_person_bound", base=bind_base, intent=intent, revision=bind_revision),
        ],
    )
    await db_session.commit()
    await db_session.refresh(cluster)
    assert [(result.status, result.conflict_code) for result in results] == [
        ("acknowledged", None), ("conflict", "version_conflict"),
    ]
    assert (cluster.label, cluster.roster_id, cluster.user_confirmed) == (_CORRECTION, prior_roster_id, True)


@pytest.mark.asyncio
async def test_explicit_intent_requires_label_predecessor_not_any_cluster_write(db_session: AsyncSession) -> None:
    tenant = await _create_tenant(db_session)
    cluster = await _corrected_cluster(db_session, tenant.id)
    base, intent = _version_of(cluster), str(uuid4())
    results = await CurationSyncService(session=db_session, job_service=FakeJobService()).apply_batch(
        tenant_id=str(tenant.id), operations=[
            _op(cluster.id, kind="cluster_person_unbound", base=base, intent=intent),
            _op(cluster.id, kind="cluster_person_bound", base=base, intent=intent),
        ],
    )
    await db_session.commit()
    await db_session.refresh(cluster)
    assert results[0].status == "acknowledged"
    assert (results[1].status, results[1].conflict_code, cluster.roster_id, cluster.label) == (
        "conflict", "version_conflict", None, "Previous Correction",
    )

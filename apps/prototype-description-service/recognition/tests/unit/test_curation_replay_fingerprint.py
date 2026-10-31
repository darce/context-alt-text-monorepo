"""Persistent replay identity, using the actual HTTP operation producer."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import select

from db.models.identity import CurationReplayRecord
from db.models.tenant import Tenant
from roster.application.curation_sync_service import CurationSyncService
from roster.interface_adapters.http.curation_router import CurationSyncRequest


def operation():
    person = str(uuid4())
    return CurationSyncRequest(
        operation_type="person_updated",
        entity_type="person",
        entity_key=person,
        idempotency_key="immutable-step",
        expected_base_version=1234567890123456,
        local_revision=7,
        payload={
            "person_uuid": person,
            "name": "Ada",
            "binding_intent_id": str(uuid4()),
            "command_id": str(uuid4()),
            "step_id": str(uuid4()),
            "guards": {"revision": 3, "proof": {"score": 1, "members": ["a", "b"]}},
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"operation_type": "person_deleted"},
        {"entity_type": "cluster"},
        {"entity_key": "different-entity"},
        {"expected_base_version": 1234567890123457},
        {"local_revision": 8},
        {"payload_field": "name", "value": "Grace"},
        {"payload_field": "person_uuid", "value": str(uuid4())},
        {"payload_field": "binding_intent_id", "value": str(uuid4())},
        {"payload_field": "command_id", "value": str(uuid4())},
        {"payload_field": "step_id", "value": str(uuid4())},
        {"payload_field": "guards", "value": {"revision": 3, "proof": {"score": 1.0, "members": ["a", "b"]}}},
        {"payload_field": "guards", "value": {"revision": 3, "proof": {"score": True, "members": ["a", "b"]}}},
    ],
)
async def test_same_key_changed_full_identity_refuses_cached_ack(db_session, change):
    tenant = Tenant(id=uuid4(), site_url="https://replay.test")
    db_session.add(tenant)
    await db_session.commit()
    original = operation()
    first = await CurationSyncService(db_session).apply(str(tenant.id), original)
    await db_session.commit()
    changed = deepcopy(original.model_dump())
    if "payload_field" in change:
        changed["payload"][change["payload_field"]] = change["value"]
    else:
        changed.update(change)
    retry = await CurationSyncService(db_session).apply(str(tenant.id), CurationSyncRequest(**changed))
    assert first.status == "acknowledged"
    assert retry.status == "conflict", "changed immutable operation must not replay the cached ACK"
    assert retry.conflict_code == "replay_fingerprint_conflict"
    assert (await CurationSyncService(db_session).apply(str(tenant.id), original)) == first


@pytest.mark.asyncio
async def test_reordered_maps_replay_but_list_order_and_float_precision_do_not(db_session):
    tenant = Tenant(id=uuid4(), site_url="https://replay.test")
    db_session.add(tenant)
    await db_session.commit()
    original = operation().model_dump()
    original["payload"]["guards"]["proof"]["score"] = 0.1234567890123456
    first = await CurationSyncService(db_session).apply(str(tenant.id), original)
    await db_session.commit()
    reordered = deepcopy(original)
    reordered["payload"] = dict(reversed(list(reordered["payload"].items())))
    reordered["payload"]["guards"] = dict(reversed(list(reordered["payload"]["guards"].items())))
    assert await CurationSyncService(db_session).apply(str(tenant.id), reordered) == first
    for proof in [
        {"score": 0.1234567890123457, "members": ["a", "b"]},
        {"score": 0.1234567890123456, "members": ["b", "a"]},
    ]:
        changed = deepcopy(original)
        changed["payload"]["guards"]["proof"] = proof
        assert (
            await CurationSyncService(db_session).apply(str(tenant.id), changed)
        ).conflict_code == "replay_fingerprint_conflict"


@pytest.mark.asyncio
async def test_large_json_guard_integers_keep_exact_precision(db_session):
    tenant = Tenant(id=uuid4(), site_url="https://precision.test")
    db_session.add(tenant)
    await db_session.commit()
    original = operation().model_dump()
    original["payload"]["guard_counter"] = 9007199254740992
    await CurationSyncService(db_session).apply(str(tenant.id), original)
    await db_session.commit()
    changed = deepcopy(original)
    changed["payload"]["guard_counter"] += 1
    result = await CurationSyncService(db_session).apply(str(tenant.id), changed)
    assert result.conflict_code == "replay_fingerprint_conflict"


@pytest.mark.asyncio
async def test_legacy_row_without_fingerprint_refuses_and_remains_unadopted(db_session):
    tenant = Tenant(id=uuid4(), site_url="https://legacy.test")
    db_session.add(tenant)
    await db_session.flush()
    request = operation()
    row = CurationReplayRecord(
        tenant_id=tenant.id, idempotency_key=request.idempotency_key, result_status="acknowledged", backend_version=45
    )
    db_session.add(row)
    await db_session.commit()
    result = await CurationSyncService(db_session).apply(str(tenant.id), request)
    assert result.status == "conflict", "legacy authority cannot be inferred from the first retry"
    assert result.conflict_code == "replay_fingerprint_unavailable"
    assert row.request_fingerprint is None
    assert row.backend_version == 45


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), {1: "non-string-key"}, (1, 2), object()])
async def test_non_json_direct_payload_is_rejected_before_any_replay_or_write(db_session, invalid):
    tenant = Tenant(id=uuid4(), site_url="https://invalid.test")
    db_session.add(tenant)
    await db_session.commit()
    request = operation().model_dump()
    request["payload"]["guard"] = invalid
    with pytest.raises(ValueError, match="JSON"):
        await CurationSyncService(db_session).apply(str(tenant.id), request)
    assert (await db_session.execute(select(CurationReplayRecord))).scalars().all() == []

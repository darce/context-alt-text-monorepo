"""Service replay/effect atomicity against the real PG migration and queue writer."""

import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.models.identity import CurationReplayRecord, IdentityCluster
from db.models.jobs import IdentityClusteringJob
from db.models.tenant import Tenant
from recognition.application.orchestration.job_service import JobService
from recognition.infrastructure.repositories.job_repository import SqlAlchemyJobRepository
from recognition.tests.schema.test_curation_replay_fingerprint_pg import replay_pg_engine  # noqa: F401
from roster.application.curation_sync_service import CurationSyncService
from roster.interface_adapters.http.curation_router import CurationSyncRequest

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def replay_sessions(replay_pg_engine):
    engine = create_async_engine(
        replay_pg_engine.url.set(drivername="postgresql+asyncpg"), connect_args={"timeout": 5, "command_timeout": 10}
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def context(session, tenant):
    await session.execute(text("SELECT set_config('app.current_tenant',:t,true)"), {"t": str(tenant)})


def service(session):
    # queue_curation_followup only saves the pending job; no worker/inference runs.
    return CurationSyncService(session, JobService(SqlAlchemyJobRepository(session), None, None))


async def seeded(factory):
    tenant, cluster = uuid4(), uuid4()
    async with factory() as session:
        session.add(Tenant(id=tenant, site_url=f"https://{tenant}.fingerprint.test"))
        await session.flush()
        await context(session, tenant)
        model = IdentityCluster(id=cluster, tenant_id=tenant, roster_id=None, label="Before", identity_count=0)
        session.add(model)
        await session.flush()
        request = CurationSyncRequest(
            operation_type="cluster_person_bound",
            entity_type="cluster",
            entity_key=str(cluster),
            idempotency_key="bind-step",
            expected_base_version=int(model.updated_at.timestamp() * 1_000_000),
            local_revision=1,
            payload={
                "cluster_uuid": str(cluster),
                "person_uuid": str(uuid4()),
                "person_name": "Ada",
                "guards": {"membership": ["a", "b"]},
            },
        )
        await session.commit()
    return tenant, cluster, request


async def counts(session, tenant):
    return tuple(
        [
            await session.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant))
            for model in (CurationReplayRecord, IdentityClusteringJob)
        ]
    )


@pytest.mark.pg
async def test_ack_loss_replays_after_new_connection_and_changed_payload_cannot_mutate(replay_sessions):
    tenant, cluster, request = await seeded(replay_sessions)
    async with replay_sessions() as session:
        await context(session, tenant)
        first = await service(session).apply(str(tenant), request)
        await session.commit()  # ACK is "lost"; retry opens a different session.
    async with replay_sessions() as session:
        await context(session, tenant)
        assert await CurationSyncService(session).apply(str(tenant), request) == first
        for delta in [
            {"operation_type": "cluster_person_unbound"},
            {"payload": {**request.payload, "person_name": "Changed"}},
            {"payload": {**request.payload, "guards": {"membership": ["a"]}}},
            {"expected_base_version": request.expected_base_version + 1},
        ]:
            changed = CurationSyncRequest(**{**request.model_dump(), **delta})
            result = await service(session).apply(str(tenant), changed)
            assert result.conflict_code == "replay_fingerprint_conflict"
        model = await session.get(IdentityCluster, cluster)
        assert (str(model.roster_id), model.label) == (request.payload["person_uuid"], "Ada")
        assert await counts(session, tenant) == (1, 1)
        record = (
            await session.scalars(select(CurationReplayRecord).where(CurationReplayRecord.tenant_id == tenant))
        ).one()
        assert len(record.request_fingerprint) == 64
        assert record.machine_payload_json is not None


@pytest.mark.pg
async def test_concurrent_retry_is_bounded_and_cross_tenant_same_key_is_independent(replay_sessions):
    tenant, cluster, request = await seeded(replay_sessions)
    other, _, foreign_request = await seeded(replay_sessions)
    async with replay_sessions() as first, replay_sessions() as retry, replay_sessions() as foreign:
        await context(first, tenant)
        first_result = await service(first).apply(str(tenant), request)
        await context(retry, tenant)
        for attempt in [
            request,
            CurationSyncRequest(**{**request.model_dump(), "payload": {**request.payload, "person_name": "Changed"}}),
        ]:
            busy = await asyncio.wait_for(service(retry).apply(str(tenant), attempt), timeout=2)
            assert busy.conflict_code == "replay_in_progress"
            assert await counts(retry, tenant) == (0, 0)
        await context(foreign, other)
        assert (
            await asyncio.wait_for(service(foreign).apply(str(other), foreign_request), timeout=2)
        ).status == "acknowledged"
        await foreign.commit()
        await first.commit()
        await retry.rollback()
        await context(retry, tenant)
        assert await service(retry).apply(str(tenant), request) == first_result
        assert await counts(retry, tenant) == (1, 1)
        assert await retry.get(IdentityCluster, cluster) is not None


@pytest.mark.pg
async def test_cached_conflict_keeps_its_full_identity_after_cluster_appears(replay_sessions):
    tenant, _, request = await seeded(replay_sessions)
    missing = uuid4()
    request = CurationSyncRequest(
        **{
            **request.model_dump(),
            "entity_key": str(missing),
            "payload": {**request.payload, "cluster_uuid": str(missing)},
        }
    )
    async with replay_sessions() as session:
        await context(session, tenant)
        first = await service(session).apply(str(tenant), request)
        assert first.conflict_code == "cluster_not_found"
        await session.commit()
        await context(session, tenant)
        session.add(IdentityCluster(id=missing, tenant_id=tenant, label="Late", identity_count=0))
        await session.commit()
    async with replay_sessions() as session:
        await context(session, tenant)
        assert await service(session).apply(str(tenant), request) == first
        changed = CurationSyncRequest(**{**request.model_dump(), "expected_base_version": 0})
        assert (await service(session).apply(str(tenant), changed)).conflict_code == "replay_fingerprint_conflict"
        assert await counts(session, tenant) == (1, 0)
        assert (await session.get(IdentityCluster, missing)).roster_id is None


@pytest.mark.parametrize("fail_at_replay", [False, True])
@pytest.mark.pg
async def test_effect_queue_fingerprint_and_result_rollback_together(replay_sessions, fail_at_replay):
    tenant, cluster, request = await seeded(replay_sessions)
    async with replay_sessions() as session:
        await context(session, tenant)

        def fail_replay_flush(sync_session, flush_context, instances):
            if any(isinstance(obj, CurationReplayRecord) for obj in sync_session.new):
                raise RuntimeError("injected replay flush failure")

        if fail_at_replay:
            event.listen(session.sync_session, "before_flush", fail_replay_flush)
            with pytest.raises(RuntimeError, match="injected replay"):
                await service(session).apply(str(tenant), request)
            event.remove(session.sync_session, "before_flush", fail_replay_flush)
        else:
            assert (await service(session).apply(str(tenant), request)).status == "acknowledged"
        await session.rollback()
    async with replay_sessions() as session:
        await context(session, tenant)
        model = await session.get(IdentityCluster, cluster)
        assert model.roster_id is None and model.label == "Before"
        assert await counts(session, tenant) == (0, 0)
        # Transaction lock was also released; the original request can apply.
        assert (
            await asyncio.wait_for(service(session).apply(str(tenant), deepcopy(request)), timeout=2)
        ).status == "acknowledged"
        await session.commit()
        await context(session, tenant)
        assert await counts(session, tenant) == (1, 1)


async def test_sqlite_actual_queue_writer_replay_and_cross_tenant_effects(db_session):
    for name in ("Ada", "Grace"):
        tenant, cluster_id, person_id = uuid4(), uuid4(), uuid4()
        db_session.add(Tenant(id=tenant, site_url=f"https://{tenant}.local-replay.test"))
        await db_session.flush()
        cluster = IdentityCluster(id=cluster_id, tenant_id=tenant, label="Before", identity_count=0)
        db_session.add(cluster)
        await db_session.commit()
        request = CurationSyncRequest(
            operation_type="cluster_person_bound",
            entity_type="cluster",
            entity_key=str(cluster_id),
            idempotency_key="shared-key",
            expected_base_version=int(cluster.updated_at.timestamp() * 1_000_000),
            local_revision=1,
            payload={"cluster_uuid": str(cluster_id), "person_uuid": str(person_id), "person_name": name},
        )
        first = await service(db_session).apply(str(tenant), request)
        await db_session.commit()
        assert await CurationSyncService(db_session).apply(str(tenant), request) == first
        changed = CurationSyncRequest(
            **{**request.model_dump(), "payload": {**request.payload, "person_name": "Changed"}}
        )
        assert (await service(db_session).apply(str(tenant), changed)).conflict_code == "replay_fingerprint_conflict"
        await db_session.refresh(cluster)
        assert (cluster.roster_id, cluster.label) == (person_id, name)
        assert await counts(db_session, tenant) == (1, 1)


async def test_sqlite_replay_flush_failure_rolls_back_real_effect_and_queue(db_session):
    tenant, cluster_id = uuid4(), uuid4()
    db_session.add(Tenant(id=tenant, site_url="https://rollback.test"))
    await db_session.flush()
    cluster = IdentityCluster(id=cluster_id, tenant_id=tenant, label="Before", identity_count=0)
    db_session.add(cluster)
    await db_session.commit()
    request = CurationSyncRequest(
        operation_type="cluster_person_bound",
        entity_type="cluster",
        entity_key=str(cluster_id),
        idempotency_key="rollback-key",
        expected_base_version=int(cluster.updated_at.timestamp() * 1_000_000),
        payload={"cluster_uuid": str(cluster_id), "person_uuid": str(uuid4()), "person_name": "Ada"},
    )

    def fail_replay_flush(sync_session, flush_context, instances):
        if any(isinstance(obj, CurationReplayRecord) for obj in sync_session.new):
            raise RuntimeError("injected replay flush failure")

    event.listen(db_session.sync_session, "before_flush", fail_replay_flush)
    try:
        with pytest.raises(RuntimeError, match="injected replay"):
            await service(db_session).apply(str(tenant), request)
    finally:
        event.remove(db_session.sync_session, "before_flush", fail_replay_flush)
    await db_session.rollback()
    await db_session.refresh(cluster)
    assert cluster.roster_id is None and cluster.label == "Before"
    assert await counts(db_session, tenant) == (0, 0)
    assert (await service(db_session).apply(str(tenant), request)).status == "acknowledged"
    assert await counts(db_session, tenant) == (1, 1)

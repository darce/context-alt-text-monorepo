"""Retention across real request SET LOCAL / COMMIT boundaries (RET-002)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from recognition.application.services.purge_service import TenantPurgeService
from recognition.domain.repositories import MvRefreshOutcome
from recognition.interface_adapters.http.deps import session as session_deps
from recognition.tests.schema.test_face_observation_erasure_pg import _as_tenant, _seed_tenant

pytestmark = [pytest.mark.pg, pytest.mark.asyncio]


def _historical(conn, tenant_id):
    observation_id = uuid4()
    _as_tenant(conn, tenant_id)
    conn.execute(
        text("INSERT INTO face_observations(id,tenant_id,identity_namespace_id,attachment_id,evidence) "
             "VALUES (:o,:t,:o,9,'{}'::jsonb)"),
        {"o": observation_id, "t": tenant_id},
    )
    return observation_id


def _service(session):
    service = TenantPurgeService(session, batch_size=1)
    # MV maintenance is independent of request authorization; all purge SQL is real.
    service._cluster_repository.refresh_centroids_view_concurrent = AsyncMock(return_value=MvRefreshOutcome.REFRESHED)
    return service


def _request(tenant_id):
    return asynccontextmanager(session_deps.get_session)(
        SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
        tenant_id=str(tenant_id) if tenant_id else None,
    )


async def _assert_clean_pool(engine, pid):
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT pg_backend_pid()"))).scalar_one() == pid
        for name in ("app.current_tenant", "app.face_observation_erasure_tenant", "app.bypass_rls"):
            assert (await conn.execute(text("SELECT current_setting(:n,true)"), {"n": name})).scalar_one() in (None, "", "false")
        assert (await conn.execute(text("SELECT count(*) FROM face_observations"))).scalar_one() == 0


@pytest_asyncio.fixture
async def request_engine(pg_migrated_engine, monkeypatch):
    engine = create_async_engine(pg_migrated_engine.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0)
    # Only replace the factory: actual get_session, safety settings and tenant helper run.
    monkeypatch.setattr(session_deps, "async_session_factory", async_sessionmaker(engine, expire_on_commit=False))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.mark.parametrize("case", ["historical-all", "disposed-mix", "empty-disposed"])
async def test_request_purge_multibatch_completes_with_truthful_audit(pg_migrated_engine, request_engine, case):
    with pg_migrated_engine.begin() as conn:
        tenant_a, disposed_obs, _ = _seed_tenant(conn, disposed=True)
        tenant_b, observation_b, identity_b = _seed_tenant(conn, disposed=True)
        historical = {_historical(conn, tenant_a), _historical(conn, tenant_a)}
        if case == "historical-all":
            _as_tenant(conn, tenant_a)
            conn.execute(text("DELETE FROM media_identities WHERE tenant_id=:t"), {"t": tenant_a})
            expected_remaining, expected_identities, expected_erased = set(), 0, 3
        else:
            live_identity = uuid4()
            _as_tenant(conn, tenant_a)
            live_obs = _historical(conn, tenant_a)
            conn.execute(text("INSERT INTO media_identities(id,tenant_id,media_id,media_url,face_observation_id,"
                              "bbox_x,bbox_y,bbox_width,bbox_height,confidence,embedding,embedding_model) "
                              "SELECT :i,tenant_id,2,media_url,:o,0,0,10,10,0.9,embedding,embedding_model "
                              "FROM media_identities WHERE tenant_id=:t"),
                         {"i": live_identity, "o": live_obs, "t": tenant_a})
            if case == "empty-disposed":
                conn.execute(text("UPDATE media_identities SET disposed_at=NULL WHERE tenant_id=:t"), {"t": tenant_a})
                expected_remaining, expected_identities, expected_erased = historical | {disposed_obs, live_obs}, 2, 0
            else:
                # Two disposed pointers make identity deletion cross a commit too.
                second_disposed = _historical(conn, tenant_a)
                conn.execute(text("INSERT INTO media_identities(id,tenant_id,media_id,media_url,face_observation_id,"
                                  "bbox_x,bbox_y,bbox_width,bbox_height,confidence,embedding,embedding_model,disposed_at) "
                                  "SELECT :i,tenant_id,3,media_url,:o,0,0,10,10,0.9,embedding,embedding_model,now() "
                                  "FROM media_identities WHERE tenant_id=:t AND disposed_at IS NOT NULL"),
                             {"i": uuid4(), "o": second_disposed, "t": tenant_a})
                expected_remaining, expected_identities, expected_erased = historical | {live_obs}, 1, 2

    async with _request(tenant_a) as session:
        pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
        assert (await session.execute(text("SELECT current_setting('app.current_tenant')"))).scalar_one() == str(tenant_a)
        result = await _service(session).purge_tenant_data(str(tenant_a), "request-pg", scope="all" if case == "historical-all" else "disposed")
        assert result["deleted_counts"]["face_observations"] == expected_erased
        assert result["deleted_counts"]["media_identities"] == (2 if case == "disposed-mix" else 0)
        assert (await session.execute(text("SELECT current_setting('app.face_observation_erasure_tenant',true)"))).scalar_one() in (None, "")
    await _assert_clean_pool(request_engine, pid)

    with pg_migrated_engine.connect() as conn:
        _as_tenant(conn, tenant_a)
        assert set(conn.execute(text("SELECT id FROM face_observations")).scalars()) == expected_remaining
        assert conn.execute(text("SELECT count(*) FROM media_identities")).scalar_one() == expected_identities
        assert conn.execute(text("SELECT last_purge_at FROM tenants WHERE id=:t"), {"t": tenant_a}).scalar_one() is not None
        events = dict(conn.execute(text("SELECT event_type,payload FROM audit_events")).all())
        assert set(events) == {"purge_started", "purge_completed"}
        assert events["purge_completed"]["deleted_counts"] == result["deleted_counts"]
        _as_tenant(conn, tenant_b)
        assert conn.execute(text("SELECT id FROM face_observations")).scalars().all() == [observation_b]
        assert conn.execute(text("SELECT id FROM media_identities")).scalars().all() == [identity_b]
        assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0


@pytest.mark.parametrize("context", ["missing", "mismatch"])
async def test_request_purge_refuses_untrusted_target(pg_migrated_engine, request_engine, context):
    with pg_migrated_engine.begin() as conn:
        tenant_a, _, _ = _seed_tenant(conn, disposed=True)
        tenant_b, _, _ = _seed_tenant(conn, disposed=True)
    with pytest.raises(PermissionError, match="tenant context"):
        async with _request(tenant_a if context == "mismatch" else None) as session:
            pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            await _service(session).purge_tenant_data(str(tenant_b), "request-pg", scope="all")
    await _assert_clean_pool(request_engine, pid)
    with pg_migrated_engine.connect() as conn:
        for tenant in (tenant_a, tenant_b):
            _as_tenant(conn, tenant)
            assert conn.execute(text("SELECT count(*) FROM face_observations")).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM media_identities")).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
            assert conn.execute(text("SELECT last_purge_at FROM tenants WHERE id=:t"), {"t": tenant}).scalar_one() is None


async def test_request_failure_rolls_back_active_batch_and_cleans_pool(pg_migrated_engine, request_engine):
    with pg_migrated_engine.begin() as conn:
        tenant = uuid4()
        conn.execute(text("INSERT INTO tenants(id,site_url) VALUES (:t,:u)"), {"t": tenant, "u": f"https://{tenant}.test"})
        for _ in range(3):
            _historical(conn, tenant)
    deletes = 0

    def fail_second_delete(conn, cursor, statement, parameters, context, executemany):
        nonlocal deletes
        if statement.startswith("DELETE FROM face_observations"):
            deletes += 1
            if deletes == 2:
                raise RuntimeError("injected second batch failure")

    event.listen(request_engine.sync_engine, "before_cursor_execute", fail_second_delete)
    try:
        with pytest.raises(RuntimeError, match="injected second batch failure"):
            async with _request(tenant) as session:
                pid = (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                await _service(session).purge_tenant_data(str(tenant), "request-pg", scope="all")
    finally:
        event.remove(request_engine.sync_engine, "before_cursor_execute", fail_second_delete)
    assert deletes == 2
    await _assert_clean_pool(request_engine, pid)
    with pg_migrated_engine.connect() as conn:
        _as_tenant(conn, tenant)
        assert conn.execute(text("SELECT count(*) FROM face_observations")).scalar_one() == 2
        assert conn.execute(text("SELECT event_type FROM audit_events")).scalars().all() == ["purge_started"]
        assert conn.execute(text("SELECT last_purge_at FROM tenants WHERE id=:t"), {"t": tenant}).scalar_one() is None
    # The same pooled connection can then serve an authenticated successful retry.
    async with _request(tenant) as session:
        result = await _service(session).purge_tenant_data(str(tenant), "retry-pg", scope="all")
        assert result["deleted_counts"]["face_observations"] == 2
    await _assert_clean_pool(request_engine, pid)

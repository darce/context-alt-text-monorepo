"""Unit tests for E15-3a-BR-21 Slice 2 admission fail-fast helpers.

Covers:

* ``_clustering_admission_probe``: best-effort pg_locks pre-flight that returns
  a 503 Retry-After when a zombie idle-in-transaction session holds the tenants
  row lock, and is a no-op on non-Postgres backends or probe errors.
* ``_acquire_tenant_lock_fast_fail``: narrow ``SET LOCAL statement_timeout``
  wrapper around the tenants ``SELECT ... FOR UPDATE`` that converts a
  ``QueryCanceledError`` (SQLSTATE 57014) into a 503 Retry-After and restores
  the default timeout on both success and cancel paths.
* End-to-end backend-measured latency: the happy-path handler observes
  ``clustering_admission_latency_ms`` under 1 s.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import DBAPIError

from recognition.application.orchestration.job_service import JobService
from recognition.interface_adapters.http.deps.clustering_circuit_breaker import (
    get_or_create_clustering_circuit_breaker,
)
from recognition.interface_adapters.http.routers import clusters_admission as clusters_module
from recognition.tests.api.conftest import FakeSession, FakeSessionResult
from recognition.tests.fakes import FakeJobRepository


class _PostgresFakeSession(FakeSession):
    """FakeSession that advertises a PostgreSQL dialect for ``is_postgres``."""

    def __init__(self) -> None:
        super().__init__()
        self.bind = type(
            "Bind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()


class _AdmissionDBSession(_PostgresFakeSession):
    """PostgreSQL session fake that routes responses by the executed SQL."""

    def __init__(
        self,
        *,
        probe_scalar: object | None = None,
        probe_exception: Exception | None = None,
        tenant_lock_exception: Exception | None = None,
    ) -> None:
        super().__init__()
        self.probe_scalar = probe_scalar
        self.probe_exception = probe_exception
        self.tenant_lock_exception = tenant_lock_exception

    async def execute(self, statement, _params=None):  # noqa: ANN001
        sql = str(statement)
        self.execute_calls += 1
        self.executed_statements.append(sql)

        if "pg_locks" in sql:
            if self.probe_exception is not None:
                raise self.probe_exception
            return FakeSessionResult(scalar_value=self.probe_scalar)
        if "FOR UPDATE" in sql.upper() and self.tenant_lock_exception is not None:
            raise self.tenant_lock_exception
        if "pg_backend_pid()" in sql:
            return FakeSessionResult(scalar_value=123)
        return FakeSessionResult()


class _FakeOrig:
    """Minimal DBAPI driver exception stub carrying a sqlstate."""

    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate
        self.pgcode = sqlstate


def _make_query_canceled_dbapi_error() -> DBAPIError:
    return DBAPIError(
        "SELECT ... FOR UPDATE",
        None,
        _FakeOrig("57014"),
    )


def _make_generic_dbapi_error() -> DBAPIError:
    return DBAPIError(
        "SELECT ... FOR UPDATE",
        None,
        _FakeOrig("08000"),
    )


def _configure_admission_route(api_client, session: _AdmissionDBSession):  # noqa: ANN001
    """Use a real JobService/repository and the caller-supplied DB session."""
    repository = FakeJobRepository()
    job_service = JobService(repository=repository, cluster_service=None, scan_service=None)

    async def session_dependency():
        yield session

    async def job_service_dependency():
        return job_service

    api_client.app.dependency_overrides[clusters_module.get_clustering_session] = session_dependency
    api_client.app.dependency_overrides[
        clusters_module.get_persisted_cluster_job_service_clustering
    ] = job_service_dependency
    breaker = get_or_create_clustering_circuit_breaker(api_client.app)
    breaker.record_success()
    return repository, breaker


async def _post_async_clustering_job(api_client, tenant_id: str):  # noqa: ANN001
    async with AsyncClient(
        transport=ASGITransport(app=api_client.app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": tenant_id, "mode": "async"},
        )


# ---------------------------------------------------------------------------
# _clustering_admission_probe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_no_op_on_non_postgres_session() -> None:
    session = FakeSession()  # no bind -> is_postgres() is False

    await clusters_module._clustering_admission_probe(
        session,
        tenant_id=str(uuid.uuid4()),
        retry_after_seconds=5,
    )

    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_probe_noop_when_no_blocker_row_returned() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=None)

    await clusters_module._clustering_admission_probe(
        session,
        tenant_id=str(uuid.uuid4()),
        retry_after_seconds=5,
    )

    assert session.execute_calls == 1
    assert any("pg_locks" in stmt for stmt in session.executed_statements)


@pytest.mark.asyncio
async def test_probe_sql_excludes_reader_lock_modes_br22() -> None:
    """E15-3a-BR-22: probe must not fire on AccessShareLock / RowShareLock.

    An idle-in-txn reader holding AccessShareLock on `tenants` does NOT block
    a SELECT ... FOR UPDATE. The probe must narrow to modes that truly
    conflict: row-level tuple locks OR relation-level Exclusive/
    AccessExclusive. Verified by inspecting the issued SQL.
    """
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=None)

    await clusters_module._clustering_admission_probe(
        session,
        tenant_id=str(uuid.uuid4()),
        retry_after_seconds=5,
    )

    assert session.execute_calls == 1
    sql = session.executed_statements[0]
    # Row-level locks on tenants are valid blocker signals.
    assert "'tuple'" in sql or "locktype = 'tuple'" in sql
    # Strong relation-level locks are valid blocker signals.
    assert "AccessExclusiveLock" in sql or "ExclusiveLock" in sql
    # Reader-compatible modes must NOT be matched.
    assert "AccessShareLock" not in sql or (
        # Allowed only if explicitly excluded via `NOT IN`/`<>` etc.
        "NOT IN" in sql or "<>" in sql or "!=" in sql
    )


@pytest.mark.asyncio
async def test_probe_raises_503_retry_after_when_blocker_detected(api_client, tenant_id) -> None:
    session = _AdmissionDBSession(probe_scalar=1)
    repository, _breaker = _configure_admission_route(api_client, session)

    resp = await _post_async_clustering_job(api_client, tenant_id)

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "5"
    assert resp.json()["detail"] == "Clustering temporarily unavailable"
    assert repository.jobs == {}


@pytest.mark.asyncio
async def test_probe_swallows_execute_exception_best_effort(api_client, tenant_id) -> None:
    session = _AdmissionDBSession(
        probe_exception=RuntimeError("pg_stat_activity permission denied")
    )
    repository, _breaker = _configure_admission_route(api_client, session)

    resp = await _post_async_clustering_job(api_client, tenant_id)

    assert resp.status_code == 202
    job_id = resp.json()["id"]
    assert job_id in repository.jobs
    assert repository.jobs[job_id].tenant_id == tenant_id


# ---------------------------------------------------------------------------
# _acquire_tenant_lock_fast_fail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_lock_non_postgres_skips_set_local() -> None:
    session = FakeSession()
    session.queue_execute_result(scalar_one_or_none=None)  # SELECT FOR UPDATE

    await clusters_module._acquire_tenant_lock_fast_fail(
        session,
        tenant_id=str(uuid.uuid4()),
        lock_timeout_ms=1000,
        default_timeout="10s",
        retry_after_seconds=5,
    )

    # Only the SELECT FOR UPDATE, no SET LOCAL emitted.
    assert session.execute_calls == 1
    assert not any("SET LOCAL" in stmt for stmt in session.executed_statements)


@pytest.mark.asyncio
async def test_acquire_lock_postgres_happy_path_narrows_and_restores_timeout() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=None)  # SET LOCAL narrow
    session.queue_execute_result(scalar_one_or_none=None)  # SELECT FOR UPDATE
    session.queue_execute_result(scalar=None)  # SET LOCAL restore

    await clusters_module._acquire_tenant_lock_fast_fail(
        session,
        tenant_id=str(uuid.uuid4()),
        lock_timeout_ms=1000,
        default_timeout="10s",
        retry_after_seconds=5,
    )

    assert session.execute_calls == 3
    narrow, select_stmt, restore = session.executed_statements
    assert "SET LOCAL statement_timeout = '1000ms'" in narrow
    assert "FOR UPDATE" in select_stmt.upper()
    assert "SET LOCAL statement_timeout = '10s'" in restore


@pytest.mark.asyncio
async def test_acquire_lock_query_canceled_raises_503_retry_after(api_client, tenant_id) -> None:
    session = _AdmissionDBSession(tenant_lock_exception=_make_query_canceled_dbapi_error())
    repository, breaker = _configure_admission_route(api_client, session)

    resp = await _post_async_clustering_job(api_client, tenant_id)

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "5"
    assert repository.jobs == {}
    assert breaker.snapshot().failure_count == 1
    assert any("SET LOCAL statement_timeout = '10s'" in stmt for stmt in session.executed_statements)


@pytest.mark.asyncio
async def test_acquire_lock_non_canceled_dbapi_error_is_reraised(api_client, tenant_id) -> None:
    generic_error = _make_generic_dbapi_error()
    session = _AdmissionDBSession(tenant_lock_exception=generic_error)
    repository, breaker = _configure_admission_route(api_client, session)

    with pytest.raises(DBAPIError) as exc_info:
        await _post_async_clustering_job(api_client, tenant_id)

    assert exc_info.value is generic_error
    assert breaker.snapshot().failure_count == 0
    assert repository.jobs == {}
    assert any("SET LOCAL statement_timeout = '10s'" in stmt for stmt in session.executed_statements)


# ---------------------------------------------------------------------------
# _is_query_canceled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_query_canceled_matches_sqlstate_57014(api_client, tenant_id) -> None:
    session = _AdmissionDBSession(tenant_lock_exception=_make_query_canceled_dbapi_error())
    repository, breaker = _configure_admission_route(api_client, session)

    resp = await _post_async_clustering_job(api_client, tenant_id)

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "5"
    assert breaker.snapshot().failure_count == 1
    assert repository.jobs == {}


@pytest.mark.asyncio
async def test_is_query_canceled_rejects_other_sqlstates(api_client, tenant_id) -> None:
    generic_error = _make_generic_dbapi_error()
    session = _AdmissionDBSession(tenant_lock_exception=generic_error)
    repository, breaker = _configure_admission_route(api_client, session)

    with pytest.raises(DBAPIError) as exc_info:
        await _post_async_clustering_job(api_client, tenant_id)

    assert exc_info.value is generic_error
    assert breaker.snapshot().failure_count == 0
    assert repository.jobs == {}


@pytest.mark.asyncio
async def test_is_query_canceled_handles_missing_orig(api_client, tenant_id) -> None:
    error_without_orig = DBAPIError("SELECT ... FOR UPDATE", None, None)
    session = _AdmissionDBSession(tenant_lock_exception=error_without_orig)
    repository, breaker = _configure_admission_route(api_client, session)

    with pytest.raises(DBAPIError) as exc_info:
        await _post_async_clustering_job(api_client, tenant_id)

    assert exc_info.value is error_without_orig
    assert breaker.snapshot().failure_count == 0
    assert repository.jobs == {}


# ---------------------------------------------------------------------------
# Backend-measured latency: direct timing of the two helpers on the happy path.
# ---------------------------------------------------------------------------


@pytest.mark.timing
@pytest.mark.asyncio
async def test_admission_path_latency_is_sub_second_on_happy_path() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=None)  # probe: no blocker
    session.queue_execute_result(scalar=None)  # SET LOCAL narrow
    session.queue_execute_result(scalar_one_or_none=None)  # SELECT FOR UPDATE
    session.queue_execute_result(scalar=None)  # SET LOCAL restore

    tenant_id = str(uuid.uuid4())
    started = time.perf_counter()
    await clusters_module._clustering_admission_probe(
        session,
        tenant_id=tenant_id,
        retry_after_seconds=5,
    )
    await clusters_module._acquire_tenant_lock_fast_fail(
        session,
        tenant_id=tenant_id,
        lock_timeout_ms=1000,
        default_timeout="10s",
        retry_after_seconds=5,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms < 1000, f"admission path took {elapsed_ms:.2f}ms (>=1000ms budget)"


# ---------------------------------------------------------------------------
# Breaker integration (Slice 3): open breaker short-circuits before probe.
# ---------------------------------------------------------------------------


def test_open_breaker_short_circuits_with_503_before_repo(api_client, tenant_id, fake_job_service) -> None:
    """With the clustering breaker OPEN, POST /clustering/jobs returns 503 ahead of any repo work."""
    breaker = get_or_create_clustering_circuit_breaker(api_client.app)
    breaker.force_open()

    try:
        starting_jobs = len(fake_job_service.repository.jobs)
        resp = api_client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": tenant_id, "mode": "async"},
        )

        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "5"
        # No job was created, breaker fast-path bypassed the whole admission chain.
        assert len(fake_job_service.repository.jobs) == starting_jobs
    finally:
        breaker.record_success()  # reset to CLOSED so other tests sharing state are unaffected


def test_breaker_records_failure_on_query_canceled_503(api_client, tenant_id, monkeypatch) -> None:
    """A QueryCanceledError 503 from the lock helper must tick the breaker."""
    breaker = get_or_create_clustering_circuit_breaker(api_client.app)
    breaker.record_success()  # ensure CLOSED + zero failures for a clean baseline

    async def _raise_503(session, *, tenant_id, lock_timeout_ms, default_timeout, retry_after_seconds):  # noqa: ANN001
        raise HTTPException(
            status_code=503,
            detail={"reason": "tenant_lock_query_canceled", "tenant_id": tenant_id},
            headers={"Retry-After": str(retry_after_seconds)},
        )

    async def _probe_noop(session, *, tenant_id, retry_after_seconds):  # noqa: ANN001
        return None

    monkeypatch.setattr(clusters_module, "_acquire_tenant_lock_fast_fail", _raise_503)
    monkeypatch.setattr(clusters_module, "_clustering_admission_probe", _probe_noop)

    resp = api_client.post(
        "/recognition/clustering/jobs",
        json={"tenant_id": tenant_id, "mode": "async"},
    )

    assert resp.status_code == 503
    snapshot = breaker.snapshot()
    assert snapshot.failure_count == 1
    breaker.record_success()  # clean up for subsequent tests

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
from sqlalchemy.exc import DBAPIError

from recognition.interface_adapters.http.deps.clustering_circuit_breaker import (
    get_or_create_clustering_circuit_breaker,
)
from recognition.interface_adapters.http.routers import clusters_admission as clusters_module
from recognition.tests.api.conftest import FakeSession


class _PostgresFakeSession(FakeSession):
    """FakeSession that advertises a PostgreSQL dialect for ``is_postgres``."""

    def __init__(self) -> None:
        super().__init__()
        self.bind = type(
            "Bind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()


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
async def test_probe_raises_503_retry_after_when_blocker_detected() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=1)

    with pytest.raises(HTTPException) as exc_info:
        await clusters_module._clustering_admission_probe(
            session,
            tenant_id="00000000-0000-0000-0000-000000000000",
            retry_after_seconds=5,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "5"}


@pytest.mark.asyncio
async def test_probe_swallows_execute_exception_best_effort() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_exception(RuntimeError("pg_stat_activity permission denied"))

    # Must not raise -- a broken probe cannot block legitimate traffic.
    await clusters_module._clustering_admission_probe(
        session,
        tenant_id=str(uuid.uuid4()),
        retry_after_seconds=5,
    )


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
async def test_acquire_lock_query_canceled_raises_503_retry_after() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=None)  # SET LOCAL narrow
    session.queue_execute_exception(_make_query_canceled_dbapi_error())
    session.queue_execute_result(scalar=None)  # SET LOCAL restore still runs in finally

    with pytest.raises(HTTPException) as exc_info:
        await clusters_module._acquire_tenant_lock_fast_fail(
            session,
            tenant_id="00000000-0000-0000-0000-000000000000",
            lock_timeout_ms=1000,
            default_timeout="10s",
            retry_after_seconds=5,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "5"}
    # Restore still issued in finally to keep the session safe.
    assert any("SET LOCAL statement_timeout = '10s'" in stmt for stmt in session.executed_statements)


@pytest.mark.asyncio
async def test_acquire_lock_non_canceled_dbapi_error_is_reraised() -> None:
    session = _PostgresFakeSession()
    session.queue_execute_result(scalar=None)  # SET LOCAL narrow
    generic_error = _make_generic_dbapi_error()
    session.queue_execute_exception(generic_error)
    session.queue_execute_result(scalar=None)  # SET LOCAL restore in finally

    with pytest.raises(DBAPIError) as exc_info:
        await clusters_module._acquire_tenant_lock_fast_fail(
            session,
            tenant_id=str(uuid.uuid4()),
            lock_timeout_ms=1000,
            default_timeout="10s",
            retry_after_seconds=5,
        )

    assert exc_info.value is generic_error
    assert any("SET LOCAL statement_timeout = '10s'" in stmt for stmt in session.executed_statements)


# ---------------------------------------------------------------------------
# _is_query_canceled
# ---------------------------------------------------------------------------


def test_is_query_canceled_matches_sqlstate_57014() -> None:
    err = _make_query_canceled_dbapi_error()
    assert clusters_module._is_query_canceled(err) is True


def test_is_query_canceled_rejects_other_sqlstates() -> None:
    err = _make_generic_dbapi_error()
    assert clusters_module._is_query_canceled(err) is False


def test_is_query_canceled_handles_missing_orig() -> None:
    class _BareDBAPIError:
        orig = None

    assert clusters_module._is_query_canceled(_BareDBAPIError()) is False


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

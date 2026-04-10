"""API dependency override tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from recognition.domain.services.retention_policy_service import RetentionPolicyService
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps import session as session_module
from recognition.interface_adapters.http.deps.circuit_breaker import (
    BreakerState,
    SessionDependencyCircuitBreaker,
    initialize_session_dependency_circuit_breaker,
)
from recognition.tests.api.conftest import FakeSession


def test_clusters_router_respects_dependency_override(api_client, tenant_id, fake_cluster_service) -> None:
    resp = api_client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202
    assert any(call["method"] == "cluster_unclustered_identities" for call in fake_cluster_service.calls)


def test_clusters_router_invokes_cluster_service_dependency(tenant_id) -> None:
    """Default dependency should call build_cluster_service with request tenant and session."""
    called: dict[str, object] = {}

    def fake_cluster_service_builder():
        async def _builder(dep_tenant_id: str):
            called["tenant_id"] = dep_tenant_id

            class StubService:
                async def cluster_unclustered_identities(self, invoked_tenant_id: str):
                    called["invoke_tenant"] = invoked_tenant_id
                    dt = __import__("datetime")
                    now = dt.datetime.now(tz=dt.UTC)
                    return type(
                        "Result",
                        (),
                        {
                            "job_id": str(uuid.uuid4()),
                            "started_at": now,
                            "finished_at": now,
                            "completed": 0,
                            "total": 0,
                        },
                    )()

            return StubService()

        return _builder

    async def _session_override():
        yield FakeSession()

    async def fake_job_service_dep():
        from recognition.tests.fakes import FakeJobService

        return FakeJobService()

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_cluster_service_builder] = fake_cluster_service_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service] = fake_job_service_dep

    client = TestClient(app)
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202
    assert resp.json()["type"] == "clustering"
    assert called.get("tenant_id") == tenant_id
    assert called.get("invoke_tenant") == tenant_id


def test_clusters_router_does_not_resolve_scan_service_for_clustering_jobs(tenant_id) -> None:
    """Clustering job creation should not build scan-service dependencies."""

    def fake_cluster_service_builder():
        async def _builder(_tenant_id: str):
            class StubService:
                async def cluster_unclustered_identities(self, invoked_tenant_id: str):
                    dt = __import__("datetime")
                    now = dt.datetime.now(tz=dt.UTC)
                    return type(
                        "Result",
                        (),
                        {
                            "job_id": str(uuid.uuid4()),
                            "started_at": now,
                            "finished_at": now,
                            "completed": 0,
                            "total": 0,
                        },
                    )()

            return StubService()

        return _builder

    async def _session_override():
        yield FakeSession()

    async def fake_job_service_dep():
        from recognition.tests.fakes import FakeJobService

        return FakeJobService()

    def should_not_run_scan_builder():
        raise AssertionError("clustering jobs should not resolve scan-service dependencies")

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_session] = _session_override
    app.dependency_overrides[dependencies.get_optional_session] = _session_override
    app.dependency_overrides[dependencies.get_cluster_service_builder] = fake_cluster_service_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service] = fake_job_service_dep
    app.dependency_overrides[dependencies.get_scan_service_builder] = should_not_run_scan_builder

    client = TestClient(app)
    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "sync"})

    assert resp.status_code == 202


@pytest.mark.asyncio
async def test_retention_policy_service_factory_uses_provided_optional_session() -> None:
    session = FakeSession()

    service = await dependencies.get_retention_policy_service(session=session)

    assert isinstance(service, RetentionPolicyService)
    assert getattr(service, "_session", None) is session


class _TrackingSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0
        self.close_calls = 0
        self.execute_calls = 0
        self.executed_statements: list[str] = []
        self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "postgresql"})()})()

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def close(self) -> None:
        self.close_calls += 1

    async def execute(self, _statement, _params=None):  # noqa: ANN001
        self.execute_calls += 1
        self.executed_statements.append(str(_statement))
        return None

    async def connection(self):
        return type("AsyncConnection", (), {"sync_connection": object()})()


class _RequestClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _make_request(
    *,
    breaker: SessionDependencyCircuitBreaker | None = None,
) -> Request:
    app = FastAPI()
    initialize_session_dependency_circuit_breaker(app, breaker=breaker)
    return Request({"type": "http", "method": "GET", "path": "/test", "headers": [], "app": app})


@pytest.mark.asyncio
async def test_get_session_uses_async_session_factory_directly(monkeypatch) -> None:
    session = _TrackingSession()
    events: list[str] = []

    async def fake_set(_session, _tenant_id) -> None:
        events.append("set")

    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    monkeypatch.setattr(session_module, "set_tenant_context", fake_set)
    request = _make_request()

    yielded: list[object] = []
    async for item in session_module.get_session(request=request, tenant_id=str(uuid.uuid4())):
        yielded.append(item)

    assert yielded == [session]
    assert session.commit_calls == 1
    assert session.rollback_calls == 0
    assert session.close_calls == 1
    assert events == ["set"]


@pytest.mark.asyncio
async def test_get_optional_session_yields_none_on_probe_failure_and_closes(monkeypatch) -> None:
    class _FailingSession(_TrackingSession):
        async def execute(self, _statement, _params=None):  # noqa: ANN001
            self.execute_calls += 1
            raise RuntimeError("db unavailable")

    session = _FailingSession()
    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    request = _make_request()

    yielded: list[object | None] = []
    async for item in session_module.get_optional_session(request=request, tenant_id=None):
        yielded.append(item)

    assert yielded == [None]
    assert session.execute_calls == 1
    assert session.commit_calls == 0
    assert session.rollback_calls == 0
    assert session.close_calls == 1


@pytest.mark.asyncio
async def test_optional_session_applies_timeouts_and_logs_connection_identity(monkeypatch, caplog) -> None:
    session = _TrackingSession()
    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        session_module,
        "_db_settings",
        type(
            "Settings",
            (),
            {
                "statement_timeout": "9s",
                "idle_in_txn_timeout": "27s",
                "breaker_failure_threshold": 3,
                "breaker_half_open_after_seconds": 10,
            },
        )(),
    )
    request = _make_request()

    with caplog.at_level("INFO"):
        async for _ in session_module.get_optional_session(request=request, tenant_id=None):
            pass

    assert any("SET LOCAL statement_timeout = '9s'" in statement for statement in session.executed_statements)
    assert any(
        "SET LOCAL idle_in_transaction_session_timeout = '27s'" in statement
        for statement in session.executed_statements
    )
    assert any("conn_id=" in message for message in caplog.messages)


@pytest.mark.asyncio
async def test_optional_session_rejects_malformed_timeout_values(monkeypatch) -> None:
    session = _TrackingSession()
    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        session_module,
        "_db_settings",
        type(
            "Settings",
            (),
            {
                "statement_timeout": "9s'; RESET ALL; --",
                "idle_in_txn_timeout": "27s",
                "breaker_failure_threshold": 3,
                "breaker_half_open_after_seconds": 10,
            },
        )(),
    )
    request = _make_request()

    with pytest.raises(ValueError, match="DB_STATEMENT_TIMEOUT"):
        async for _ in session_module.get_optional_session(request=request, tenant_id=None):
            pass


@pytest.mark.asyncio
async def test_get_observability_session_degrades_without_raising(monkeypatch) -> None:
    class _FailingSession(_TrackingSession):
        async def execute(self, _statement, _params=None):  # noqa: ANN001
            self.execute_calls += 1
            raise RuntimeError("health probe failed")

    session = _FailingSession()
    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    request = _make_request()

    yielded: list[object | None] = []
    async for item in session_module.get_observability_session(request=request):
        yielded.append(item)

    assert yielded == [None]
    assert session.close_calls == 1


@pytest.mark.asyncio
async def test_get_session_fast_fails_when_breaker_is_open(monkeypatch) -> None:
    clock = _RequestClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
        time_source=clock,
    )
    breaker.force_open()
    request = _make_request(breaker=breaker)
    factory_called = False

    def _unexpected_factory():
        nonlocal factory_called
        factory_called = True
        return _TrackingSession()

    monkeypatch.setattr(session_module, "async_session_factory", _unexpected_factory)

    with pytest.raises(session_module.HTTPException) as exc_info:
        async for _ in session_module.get_session(request=request, tenant_id=None):
            pass

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers == {"Retry-After": "10"}
    assert factory_called is False


@pytest.mark.asyncio
async def test_optional_and_observability_sessions_fast_fail_when_breaker_is_open(monkeypatch) -> None:
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
    )
    breaker.force_open()
    request = _make_request(breaker=breaker)
    factory_called = False

    def _unexpected_factory():
        nonlocal factory_called
        factory_called = True
        return _TrackingSession()

    monkeypatch.setattr(session_module, "async_session_factory", _unexpected_factory)

    optional_items: list[object | None] = []
    async for item in session_module.get_optional_session(request=request, tenant_id=None):
        optional_items.append(item)

    observability_items: list[object | None] = []
    async for item in session_module.get_observability_session(request=request):
        observability_items.append(item)

    assert optional_items == [None]
    assert observability_items == [None]
    assert factory_called is False


@pytest.mark.asyncio
async def test_optional_session_half_open_success_closes_breaker(monkeypatch) -> None:
    clock = _RequestClock()
    breaker = SessionDependencyCircuitBreaker(
        failure_threshold=3,
        window_seconds=30,
        half_open_after_seconds=10,
        time_source=clock,
    )
    breaker.force_open()
    clock.now = 11.0
    request = _make_request(breaker=breaker)
    session = _TrackingSession()
    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)

    yielded: list[object | None] = []
    async for item in session_module.get_optional_session(request=request, tenant_id=None):
        yielded.append(item)

    assert yielded == [session]
    assert breaker.snapshot().state is BreakerState.CLOSED

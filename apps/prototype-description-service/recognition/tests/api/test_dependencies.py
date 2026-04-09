"""API dependency override tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.services.retention_policy_service import RetentionPolicyService
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http.deps import session as session_module
from recognition.interface_adapters.http import router as recognition_router
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


@pytest.mark.asyncio
async def test_get_session_uses_async_session_factory_directly(monkeypatch) -> None:
    session = _TrackingSession()
    events: list[str] = []

    async def fake_set(_session, _tenant_id) -> None:
        events.append("set")

    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)
    monkeypatch.setattr(session_module, "set_tenant_context", fake_set)

    yielded: list[object] = []
    async for item in session_module.get_session(tenant_id=str(uuid.uuid4())):
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

    yielded: list[object | None] = []
    async for item in session_module.get_optional_session(tenant_id=None):
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
        type("Settings", (), {"statement_timeout": "9s", "idle_in_txn_timeout": "27s"})(),
    )

    with caplog.at_level("INFO"):
        async for _ in session_module.get_optional_session(tenant_id=None):
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
        type("Settings", (), {"statement_timeout": "9s'; RESET ALL; --", "idle_in_txn_timeout": "27s"})(),
    )

    with pytest.raises(ValueError, match="DB_STATEMENT_TIMEOUT"):
        async for _ in session_module.get_optional_session(tenant_id=None):
            pass


@pytest.mark.asyncio
async def test_get_observability_session_degrades_without_raising(monkeypatch) -> None:
    class _FailingSession(_TrackingSession):
        async def execute(self, _statement, _params=None):  # noqa: ANN001
            self.execute_calls += 1
            raise RuntimeError("health probe failed")

    session = _FailingSession()
    monkeypatch.setattr(session_module, "async_session_factory", lambda: session)

    yielded: list[object | None] = []
    async for item in session_module.get_observability_session():
        yielded.append(item)

    assert yielded == [None]
    assert session.close_calls == 1

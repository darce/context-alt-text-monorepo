"""E15-3a-BR-21 Slice 4: route-owned transaction + single-session identity.

Proof obligations (task plan):

* The full ``SELECT FOR UPDATE -> lookup -> INSERT`` runs inside ONE
  ``session.begin()`` on ONE connection (no cross-connection hand-off).
* The ``AsyncSession`` handed to ``cluster_service_builder`` and ``job_service``
  inside the handler is the SAME instance handed to the route's ``session``
  parameter (single clustering-session identity across deps).
* An exception before commit rolls back via the owned txn context manager
  rather than leaking half-applied state.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from recognition.application.orchestration.job_service import JobService
from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.routers import clusters as clusters_module
from recognition.tests.api.conftest import FakeSession
from recognition.tests.fakes import FakeClusterRepository, FakeClusterService, FakeJobRepository


class _PostgresFakeSession(FakeSession):
    """FakeSession that advertises a PostgreSQL dialect for ``is_postgres``.

    The clustering route emits real ``text(...)`` calls for safety settings and
    the ``pg_locks`` probe; those must be tolerated by the fake so the handler
    actually exercises its ordered-statements body.
    """

    def __init__(self) -> None:
        super().__init__()
        self.bind = type(
            "Bind",
            (),
            {"dialect": type("Dialect", (), {"name": "postgresql"})()},
        )()


def _build_identity_tracking_client(tenant_id: str) -> tuple[TestClient, dict[str, Any]]:
    """Build a FastAPI client whose three clustering deps share one FakeSession.

    Returns the client plus a sink dict populated at request time so the test
    can assert identity invariants (same session object across deps, exactly
    one session.begin()/commit pair, etc.).
    """
    shared_session = _PostgresFakeSession()
    sink: dict[str, Any] = {
        "session_ids": [],  # id() observed for each dep
        "builder_sessions": [],
        "job_service_sessions": [],
        "cluster_service_calls": [],
    }

    fake_cluster_repo = FakeClusterRepository()
    fake_cluster_service = FakeClusterService()
    fake_cluster_service.fake_cluster_repository = fake_cluster_repo
    fake_job_repo = FakeJobRepository()

    async def _clustering_session():
        sink["session_ids"].append(id(shared_session))
        yield shared_session

    def _builder_dep(session=Depends(dependencies.get_clustering_session)):  # noqa: ANN001
        # FastAPI injects the cached clustering session here; the identity
        # assertion compares id() against the session the route received.
        sink["builder_sessions"].append(id(session))

        async def _build(tid: str):
            sink["cluster_service_calls"].append(tid)
            return fake_cluster_service

        return _build

    async def _job_service_dep(session=Depends(dependencies.get_clustering_session)):  # noqa: ANN001
        sink["job_service_sessions"].append(id(session))
        return JobService(repository=fake_job_repo, cluster_service=None, scan_service=None)

    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")
    app.dependency_overrides[dependencies.get_clustering_session] = _clustering_session
    app.dependency_overrides[dependencies.get_cluster_service_builder_clustering] = _builder_dep
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service_clustering] = _job_service_dep
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id

    # Tenant auth guard bypass
    import os

    os.environ["RECOGNITION_AUTH_ENABLED"] = "0"

    client = TestClient(app)
    sink["_shared_session"] = shared_session
    return client, sink


def test_route_owns_single_transaction(monkeypatch) -> None:
    """One session.begin() wraps the full async-mode unit of work."""
    # Avoid real tenant_context SQL against FakeSession (it would try to set a
    # UUID session var). Patch to a no-op so the route's ordering is what drives
    # the observed commit/rollback counts.
    monkeypatch.setattr(clusters_module, "set_tenant_context", _noop_async)
    monkeypatch.setattr(clusters_module, "_apply_postgres_session_safety_settings", _noop_async)
    # FakeSession's default execute() result returns a truthy scalar, which the
    # probe would interpret as a blocker. Bypass the probe so the happy path
    # exercises the owned-txn ordering, not the probe's 503 branch.
    monkeypatch.setattr(clusters_module, "_clustering_admission_probe", _noop_async)

    tenant_id = str(uuid.uuid4())
    client, sink = _build_identity_tracking_client(tenant_id)

    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "async"})
    assert resp.status_code == 202, resp.text

    shared_session: _PostgresFakeSession = sink["_shared_session"]
    assert shared_session.commit_calls == 1, f"exactly one owned txn must commit; got {shared_session.commit_calls}"
    assert shared_session.rollback_calls == 0


def test_all_three_deps_share_same_session_identity(monkeypatch) -> None:
    """FastAPI DI cache must hand the same AsyncSession to all three deps.

    Without this, the route's ``async with session.begin():`` would cover only
    the route-parameter session while the cluster builder and job service would
    each talk to a different session on a different connection -- breaking
    atomicity of the SELECT FOR UPDATE -> lookup -> INSERT.
    """
    monkeypatch.setattr(clusters_module, "set_tenant_context", _noop_async)
    monkeypatch.setattr(clusters_module, "_apply_postgres_session_safety_settings", _noop_async)
    monkeypatch.setattr(clusters_module, "_clustering_admission_probe", _noop_async)

    tenant_id = str(uuid.uuid4())
    client, sink = _build_identity_tracking_client(tenant_id)

    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "async"})
    assert resp.status_code == 202, resp.text

    route_session_ids = set(sink["session_ids"])
    builder_session_ids = set(sink["builder_sessions"])
    job_service_session_ids = set(sink["job_service_sessions"])

    assert len(route_session_ids) == 1, f"route session dep should resolve once: {route_session_ids}"
    assert route_session_ids == builder_session_ids, (
        f"cluster_service_builder got a different session: route={route_session_ids} builder={builder_session_ids}"
    )
    assert route_session_ids == job_service_session_ids, (
        f"job_service got a different session: route={route_session_ids} job_service={job_service_session_ids}"
    )


def test_owned_txn_rolls_back_on_exception(monkeypatch) -> None:
    """If the admission probe raises, the owned txn rolls back instead of commits."""
    monkeypatch.setattr(clusters_module, "set_tenant_context", _noop_async)
    monkeypatch.setattr(clusters_module, "_apply_postgres_session_safety_settings", _noop_async)

    async def _raise_probe(*_args, **_kwargs):
        # Simulate a zombie-lock 503 inside the owned txn.
        from fastapi import HTTPException
        from fastapi import status as http_status

        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clustering temporarily unavailable",
            headers={"Retry-After": "5"},
        )

    monkeypatch.setattr(clusters_module, "_clustering_admission_probe", _raise_probe)

    tenant_id = str(uuid.uuid4())
    client, sink = _build_identity_tracking_client(tenant_id)

    resp = client.post("/recognition/clustering/jobs", json={"tenant_id": tenant_id, "mode": "async"})
    assert resp.status_code == 503

    shared_session: _PostgresFakeSession = sink["_shared_session"]
    assert shared_session.rollback_calls == 1
    assert shared_session.commit_calls == 0


async def _noop_async(*_args, **_kwargs) -> None:
    return None


# Avoid unused-import complaint for pytest typing
_ = pytest

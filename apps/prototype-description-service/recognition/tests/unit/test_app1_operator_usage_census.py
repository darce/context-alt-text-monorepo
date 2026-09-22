"""G4 operator route census: beta/portal deny before mutation; status remains free.

Endpoint/method/auth classification (mounted paths below include router prefixes):

| Method | Path | Auth | Usage policy |
| --- | --- | --- | --- |
| POST | /scene/gpu/intent | require_write_access | beta/portal/demo deny (`gpu_control_forbidden`) before intent write |
| GET | /scene/gpu/status | require_auth | free polling; no reservation or intent mutation |
| POST | /recognition/clustering/jobs | require_write_access | beta/portal deny before sync compute or async job create |
| POST | /recognition/clusters/recover-orphans | require_write_access | beta/portal deny before recluster |
| POST | /recognition/clusters/{cluster_id}/revert-merge | require_write_access | beta/portal deny before revert |

Remaining gaps (not owned here): AuthContext has no entitlement field, so a beta
tenant API key without an explicit beta marker is indistinguishable from an
operator key; GET /recognition/jobs/{job_id} lives on the analyze router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from recognition.domain.cluster import IdentityCluster
from recognition.domain.portal_contracts import EntitlementStatus, PortalPrincipal, UsageTicket
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.tenant import get_tenant_id
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from recognition.interface_adapters.http.routers import cluster_revert as cluster_revert_module
from recognition.interface_adapters.http.routers import clusters_admission as clusters_admission_module
from recognition.tests.api.conftest import FakeSession
from recognition.tests.fakes import FakeJobService
from scene.interface_adapters.http.routers import gpu as gpu_routes

TENANT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
PORTAL_TENANT = UUID(TENANT_ID)
NOW = 1_786_125_000.0

OPERATOR_USAGE_CENSUS: tuple[tuple[str, str, str, str], ...] = (
    ("POST", "/scene/gpu/intent", "require_write_access", "beta_deny"),
    ("GET", "/scene/gpu/status", "require_auth", "free"),
    ("POST", "/recognition/clustering/jobs", "require_write_access", "beta_deny"),
    ("POST", "/recognition/clusters/recover-orphans", "require_write_access", "beta_deny"),
    ("POST", "/recognition/clusters/{cluster_id}/revert-merge", "require_write_access", "beta_deny"),
)


class _FakeAdmission:
    def __init__(self) -> None:
        self.reserves: list[dict[str, object]] = []
        self.commits: list[UsageTicket] = []
        self.releases: list[UsageTicket] = []

    async def reserve(self, tenant_id: object, **kwargs: object) -> UsageTicket:
        self.reserves.append({"tenant_id": tenant_id, **kwargs})
        return UsageTicket(uuid4(), PORTAL_TENANT, "key", 1)

    async def commit(self, ticket: UsageTicket) -> None:
        self.commits.append(ticket)

    async def release(self, ticket: UsageTicket) -> None:
        self.releases.append(ticket)


class _ClusterSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.assignment_writer = object()
        self.merge_suggestion_service = None

    async def cluster_unclustered_identities(self, tenant_id: str) -> SimpleNamespace:
        self.calls.append(tenant_id)
        now = datetime.now(tz=UTC)
        return SimpleNamespace(
            job_id=str(uuid4()),
            started_at=now,
            finished_at=now,
            completed=0,
            total=0,
            accepted=0,
            suggested=0,
            rejected=0,
            clusters_created=0,
        )


def _operator_auth(*, tenant_id: str = TENANT_ID) -> AuthContext:
    return AuthContext(
        token="operator-key",
        tenant_claim=tenant_id,
        api_key_id="key-operator",
        rate_limit_tier="STANDARD",
        enabled=True,
    )


def _demo_auth() -> AuthContext:
    return AuthContext(
        token="demo-key",
        tenant_claim=TENANT_ID,
        api_key_id="key-demo",
        rate_limit_tier="demo",
        enabled=True,
    )


def _beta_auth() -> AuthContext:
    return AuthContext(
        token="beta-key",
        tenant_claim=TENANT_ID,
        api_key_id="key-beta",
        rate_limit_tier="beta",
        enabled=True,
    )


def _beta_entitlement_auth() -> AuthContext:
    auth = _operator_auth()
    auth.entitlement_status = EntitlementStatus.BETA_ACTIVE  # type: ignore[attr-defined]
    return auth


def _portal_principal() -> PortalPrincipal:
    return PortalPrincipal(
        tenant_id=PORTAL_TENANT,
        issuer="https://issuer.example.test",
        subject="user_beta",
        email="beta@example.test",
    )


def _override_auth(app: FastAPI, auth: object) -> None:
    async def _auth() -> object:
        return auth

    async def _none() -> None:
        return None

    app.dependency_overrides[require_auth] = _auth
    app.dependency_overrides[require_write_access] = _auth
    app.dependency_overrides[enforce_rate_limit] = _none
    app.dependency_overrides[enforce_demo_quota] = _none


@asynccontextmanager
async def _gpu_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    *,
    auth: object,
    admission: _FakeAdmission | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, _FakeAdmission, list[tuple[tuple[Any, ...], dict[str, Any]]]]]:
    state_path = tmp_path / "gpu-state.json"
    load_path = tmp_path / "describe-load.json"
    intent_path = tmp_path / "gpu-intent.json"
    monkeypatch.setenv("ACX_GPU_STATE_PATH", str(state_path))
    monkeypatch.setenv("ACX_DESCRIBE_LOAD_PATH", str(load_path))
    monkeypatch.setenv("ACX_GPU_INTENT_PATH", str(intent_path))
    monkeypatch.setattr(gpu_routes, "_now", lambda: NOW)

    writes: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    original_write = gpu_routes.write_gpu_intent

    def _spy_write(*args: Any, **kwargs: Any) -> Any:
        writes.append((args, kwargs))
        return original_write(*args, **kwargs)

    monkeypatch.setattr(gpu_routes, "write_gpu_intent", _spy_write)

    service = admission or _FakeAdmission()
    app = FastAPI()
    app.include_router(gpu_routes.router, prefix="/scene")
    app.state.usage_admission_service = service
    _override_auth(app, auth)

    async def _usage() -> _FakeAdmission:
        return service

    app.dependency_overrides[get_usage_admission_service] = _usage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, service, writes


@asynccontextmanager
async def _cluster_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth: object,
    tenant_id: str = TENANT_ID,
    admission: _FakeAdmission | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, _ClusterSpy, FakeJobService, _FakeAdmission, list[dict[str, Any]]]]:
    service = admission or _FakeAdmission()
    cluster_spy = _ClusterSpy()
    job_service = FakeJobService()
    revert_calls: list[dict[str, Any]] = []
    session = FakeSession()

    async def _builder(_tenant_id: str) -> _ClusterSpy:
        return cluster_spy

    async def _jobs() -> FakeJobService:
        return job_service

    async def _usage() -> _FakeAdmission:
        return service

    async def _revert(**kwargs: Any) -> IdentityCluster:
        revert_calls.append(kwargs)
        return IdentityCluster(
            id=str(uuid4()),
            tenant_id=str(kwargs["tenant_id"]),
            is_labeled=True,
            identity_count=1,
            label="restored",
        )

    async def _broadcast(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(cluster_revert_module, "revert_merge", _revert)
    monkeypatch.setattr(
        cluster_revert_module,
        "get_event_broadcaster",
        lambda: SimpleNamespace(broadcast=_broadcast),
    )

    async def _yield_session() -> Any:
        yield session

    def _cluster_builder() -> Any:
        return _builder

    app = FastAPI()
    app.include_router(clusters_admission_module.router, prefix="/recognition")
    app.include_router(cluster_revert_module.router, prefix="/recognition")
    app.state.usage_admission_service = service
    _override_auth(app, auth)
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[dependencies.get_clustering_session] = _yield_session
    app.dependency_overrides[dependencies.get_session] = _yield_session
    app.dependency_overrides[dependencies.get_cluster_service_builder] = _cluster_builder
    app.dependency_overrides[dependencies.get_cluster_service_builder_clustering] = _cluster_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service_clustering] = _jobs
    app.dependency_overrides[get_usage_admission_service] = _usage

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, cluster_spy, job_service, service, revert_calls


def _mounted_routes(router: Any, prefix: str) -> set[tuple[str, str]]:
    mounted: set[tuple[str, str]] = set()
    for route in router.routes:
        for method in getattr(route, "methods", None) or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            mounted.add((method, f"{prefix}{route.path}"))
    return mounted


def test_operator_usage_census_matches_mounted_routes() -> None:
    gpu_paths = _mounted_routes(gpu_routes.router, "/scene")
    admission_paths = _mounted_routes(clusters_admission_module.router, "/recognition")
    revert_paths = _mounted_routes(cluster_revert_module.router, "/recognition")
    mounted = {(method, path) for method, path, _auth, _policy in OPERATOR_USAGE_CENSUS}
    assert mounted <= (gpu_paths | admission_paths | revert_paths)
    assert ("POST", "/scene/gpu/intent") in gpu_paths
    assert ("GET", "/scene/gpu/status") in gpu_paths
    assert ("POST", "/recognition/clustering/jobs") in admission_paths
    assert ("POST", "/recognition/clusters/recover-orphans") in admission_paths
    assert ("POST", "/recognition/clusters/{cluster_id}/revert-merge") in revert_paths


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_factory", [_beta_auth, _beta_entitlement_auth, _portal_principal, _demo_auth])
async def test_gpu_intent_denies_restricted_callers_before_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, auth_factory: Any
) -> None:
    async with _gpu_client(monkeypatch, tmp_path, auth=auth_factory()) as (client, admission, writes):
        response = await client.post("/scene/gpu/intent", json={"action": "start"})

    assert response.status_code == 403
    assert response.json()["detail"] == "gpu_control_forbidden"
    assert writes == []
    assert admission.reserves == []
    assert admission.commits == []


@pytest.mark.asyncio
async def test_gpu_intent_allows_existing_operator_branch(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    async with _gpu_client(monkeypatch, tmp_path, auth=_operator_auth()) as (client, admission, writes):
        response = await client.post("/scene/gpu/intent", json={"action": "start", "ttl_seconds": 90})

    assert response.status_code == 202
    assert response.json()["intent"]["action"] == "start"
    assert len(writes) == 1
    assert admission.reserves == []
    assert admission.commits == []


@pytest.mark.asyncio
async def test_gpu_status_polling_is_free_for_beta_and_operator(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    for auth in (_beta_auth(), _portal_principal(), _operator_auth()):
        async with _gpu_client(monkeypatch, tmp_path, auth=auth) as (client, admission, writes):
            first = await client.get("/scene/gpu/status")
            second = await client.get("/scene/gpu/status")

        assert first.status_code == 200
        assert second.status_code == 200
        assert writes == []
        assert admission.reserves == []
        assert admission.commits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("auth_factory", [_beta_auth, _beta_entitlement_auth, _portal_principal])
async def test_clustering_jobs_deny_beta_before_compute_or_job_create(
    monkeypatch: pytest.MonkeyPatch, mode: str, auth_factory: Any
) -> None:
    async with _cluster_client(monkeypatch, auth=auth_factory()) as (
        client,
        cluster_spy,
        job_service,
        admission,
        revert_calls,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": mode, "is_beta": False},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "operator_control_forbidden"
    assert cluster_spy.calls == []
    assert job_service.repository.jobs == {}
    assert admission.reserves == []
    assert admission.commits == []
    assert revert_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_clustering_jobs_preserve_operator_branch(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        cluster_spy,
        job_service,
        admission,
        _revert_calls,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": mode, "is_beta": True},
        )

    assert response.status_code == 202
    assert admission.reserves == []
    assert admission.commits == []
    if mode == "sync":
        assert cluster_spy.calls == [TENANT_ID]
    else:
        assert job_service.repository.jobs


@pytest.mark.asyncio
async def test_clustering_jobs_reject_tenant_mismatch_before_work(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        cluster_spy,
        job_service,
        admission,
        _revert_calls,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": OTHER_TENANT_ID, "mode": "sync"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "tenant mismatch"
    assert cluster_spy.calls == []
    assert job_service.repository.jobs == {}
    assert admission.reserves == []


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_factory", [_beta_auth, _portal_principal])
async def test_recover_orphans_denies_beta_before_recluster(monkeypatch: pytest.MonkeyPatch, auth_factory: Any) -> None:
    async with _cluster_client(monkeypatch, auth=auth_factory()) as (
        client,
        cluster_spy,
        _jobs,
        admission,
        _revert_calls,
    ):
        response = await client.post(
            "/recognition/clusters/recover-orphans",
            json={"tenant_id": TENANT_ID, "is_beta": False},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "operator_control_forbidden"
    assert cluster_spy.calls == []
    assert admission.reserves == []


@pytest.mark.asyncio
async def test_recover_orphans_operator_and_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        cluster_spy,
        _jobs,
        admission,
        _revert_calls,
    ):
        ok = await client.post("/recognition/clusters/recover-orphans", json={"tenant_id": TENANT_ID})
        mismatch = await client.post(
            "/recognition/clusters/recover-orphans",
            json={"tenant_id": OTHER_TENANT_ID},
        )

    assert ok.status_code == 200
    assert mismatch.status_code == 403
    assert mismatch.json()["detail"] == "tenant mismatch"
    assert cluster_spy.calls == [TENANT_ID]
    assert admission.reserves == []
    assert admission.commits == []


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_factory", [_beta_auth, _portal_principal])
async def test_cluster_revert_denies_beta_before_mutation(monkeypatch: pytest.MonkeyPatch, auth_factory: Any) -> None:
    async with _cluster_client(monkeypatch, auth=auth_factory()) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
    ):
        response = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4()), "is_beta": False},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "operator_control_forbidden"
    assert revert_calls == []
    assert admission.reserves == []


@pytest.mark.asyncio
async def test_cluster_revert_operator_and_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth(), tenant_id=OTHER_TENANT_ID) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
    ):
        mismatch = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4())},
        )

    assert mismatch.status_code == 403
    assert mismatch.json()["detail"] == "tenant mismatch"
    assert revert_calls == []
    assert admission.reserves == []

    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
    ):
        ok = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4())},
        )

    assert ok.status_code == 200
    assert revert_calls
    assert admission.reserves == []
    assert admission.commits == []

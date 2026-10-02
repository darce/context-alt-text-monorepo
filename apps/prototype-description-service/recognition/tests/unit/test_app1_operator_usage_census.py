"""G4 operator route census: durable entitlement before mutation; status remains free.

Endpoint/method/auth classification (mounted paths below include router prefixes):

| Method | Path | Auth | Usage policy |
| --- | --- | --- | --- |
| POST | /scene/gpu/intent | require_write_access | durable TenantEntitlement for auth.tenant_claim; demo/portal deny |
| GET | /scene/gpu/status | require_auth | free polling; no reservation or intent mutation |
| POST | /recognition/clustering/jobs | require_write_access | durable entitlement before sync compute or async job create |
| POST | /recognition/clusters/recover-orphans | require_write_access | durable entitlement before recluster |
| POST | /recognition/clusters/{cluster_id}/revert-merge | require_write_access | durable entitlement before revert |
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from recognition.domain.cluster import IdentityCluster
from recognition.domain.portal_contracts import EntitlementStatus, PortalPrincipal, UsageTicket
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.deps import operator_authorization as operator_authorization_module
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth, require_write_access
from recognition.interface_adapters.http.deps.demo_quota import enforce_demo_quota
from recognition.interface_adapters.http.deps.operator_authorization import (
    OPERATOR_FORBIDDEN_DETAIL,
    OPERATOR_UNAVAILABLE_DETAIL,
    get_operator_entitlement_repository,
)
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.deps.session import get_optional_session
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
    ("POST", "/scene/gpu/intent", "require_write_access", "entitlement_deny"),
    ("GET", "/scene/gpu/status", "require_auth", "free"),
    ("POST", "/recognition/clustering/jobs", "require_write_access", "entitlement_deny"),
    ("POST", "/recognition/clusters/recover-orphans", "require_write_access", "entitlement_deny"),
    ("POST", "/recognition/clusters/{cluster_id}/revert-merge", "require_write_access", "entitlement_deny"),
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


class _TrackingSession(FakeSession):
    """FakeSession that records rollback for fail-closed outage proof."""


class _EntitlementRepo:
    def __init__(
        self,
        rows: dict[UUID, Any] | None = None,
        *,
        error: Exception | None = None,
        session: Any | None = None,
    ) -> None:
        self.rows = rows or {}
        self.error = error
        self.session = session
        self.gets: list[UUID] = []

    async def get(self, tenant_id: UUID, *, for_update: bool = False) -> Any:
        del for_update
        self.gets.append(tenant_id)
        if self.error is not None:
            raise self.error
        return self.rows.get(tenant_id)


def _entitlement_row(
    *,
    tenant_id: UUID = PORTAL_TENANT,
    status: str | EntitlementStatus = EntitlementStatus.PAID_ACTIVE,
    current: bool = True,
) -> SimpleNamespace:
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        tenant_id=tenant_id,
        status=status,
        period_start=now - timedelta(days=1),
        period_end=now + timedelta(days=1) if current else now - timedelta(hours=1),
        grace_until=None,
    )


def _paid_repo(*, session: Any | None = None) -> _EntitlementRepo:
    return _EntitlementRepo({PORTAL_TENANT: _entitlement_row()}, session=session)


def _status_repo(status: str | EntitlementStatus, *, session: Any | None = None) -> _EntitlementRepo:
    return _EntitlementRepo({PORTAL_TENANT: _entitlement_row(status=status)}, session=session)


def _operator_auth(*, tenant_id: str = TENANT_ID) -> AuthContext:
    return AuthContext(
        token="operator-key",
        tenant_claim=tenant_id,
        api_key_id="key-operator",
        rate_limit_tier="STANDARD",
        enabled=True,
    )


def _beta_standard_auth() -> AuthContext:
    """Real API-key AuthContext shape: STANDARD tier, no beta markers."""
    return AuthContext(
        token="beta-key",
        tenant_claim=TENANT_ID,
        api_key_id="key-beta-standard",
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
    entitlement_repository: Any | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, _FakeAdmission, list[tuple[tuple[Any, ...], dict[str, Any]]], Any]]:
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
    session = _TrackingSession()
    repo = entitlement_repository if entitlement_repository is not None else _paid_repo(session=session)
    if getattr(repo, "session", None) is None:
        repo.session = session

    app = FastAPI()
    app.include_router(gpu_routes.router, prefix="/scene")
    app.state.usage_admission_service = service
    _override_auth(app, auth)

    async def _usage() -> _FakeAdmission:
        return service

    async def _session() -> Any:
        yield session

    async def _repo() -> Any:
        return repo

    app.dependency_overrides[get_usage_admission_service] = _usage
    app.dependency_overrides[get_optional_session] = _session
    app.dependency_overrides[get_operator_entitlement_repository] = _repo
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, service, writes, repo


@asynccontextmanager
async def _cluster_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    auth: object,
    tenant_id: str = TENANT_ID,
    admission: _FakeAdmission | None = None,
    entitlement_repository: Any | None = None,
    business_session_available: bool = True,
    override_entitlement_repository: bool = True,
) -> AsyncIterator[tuple[httpx.AsyncClient, _ClusterSpy, FakeJobService, _FakeAdmission, list[dict[str, Any]], Any]]:
    service = admission or _FakeAdmission()
    cluster_spy = _ClusterSpy()
    job_service = FakeJobService()
    revert_calls: list[dict[str, Any]] = []
    session = _TrackingSession()
    repo = entitlement_repository if entitlement_repository is not None else _paid_repo(session=session)
    if getattr(repo, "session", None) is None:
        repo.session = session

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

    async def _yield_route_session() -> Any:
        yield session

    async def _yield_optional_session() -> Any:
        yield session if business_session_available else None

    async def _cluster_builder() -> Any:
        return _builder

    async def _repo() -> Any:
        return repo

    async def _tenant_id() -> str:
        return tenant_id

    app = FastAPI()
    app.include_router(clusters_admission_module.router, prefix="/recognition")
    app.include_router(cluster_revert_module.router, prefix="/recognition")
    app.state.usage_admission_service = service
    _override_auth(app, auth)
    app.dependency_overrides[get_tenant_id] = _tenant_id
    app.dependency_overrides[dependencies.get_clustering_session] = _yield_route_session
    app.dependency_overrides[dependencies.get_session] = _yield_route_session
    app.dependency_overrides[get_optional_session] = _yield_optional_session
    if override_entitlement_repository:
        app.dependency_overrides[get_operator_entitlement_repository] = _repo
    app.dependency_overrides[dependencies.get_cluster_service_builder] = _cluster_builder
    app.dependency_overrides[dependencies.get_cluster_service_builder_clustering] = _cluster_builder
    app.dependency_overrides[dependencies.get_persisted_cluster_job_service_clustering] = _jobs
    app.dependency_overrides[get_usage_admission_service] = _usage

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, cluster_spy, job_service, service, revert_calls, repo


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
async def test_gpu_intent_denies_beta_standard_without_markers_before_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    repo = _status_repo(EntitlementStatus.BETA_ACTIVE)
    async with _gpu_client(monkeypatch, tmp_path, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        admission,
        writes,
        used_repo,
    ):
        response = await client.post("/scene/gpu/intent", json={"action": "start"})

    assert response.status_code == 403
    assert response.json()["detail"] == "gpu_control_forbidden"
    assert writes == []
    assert admission.reserves == []
    assert admission.commits == []
    assert used_repo.gets == [PORTAL_TENANT]


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_factory", [_portal_principal, _demo_auth])
async def test_gpu_intent_denies_portal_and_demo_before_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, auth_factory: Any
) -> None:
    auth = auth_factory()
    async with _gpu_client(monkeypatch, tmp_path, auth=auth, entitlement_repository=_paid_repo()) as (
        client,
        admission,
        writes,
        repo,
    ):
        response = await client.post("/scene/gpu/intent", json={"action": "start"})

    assert response.status_code == 403
    assert response.json()["detail"] == "gpu_control_forbidden"
    assert writes == []
    assert admission.reserves == []
    if isinstance(auth, PortalPrincipal):
        assert repo.gets == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_value", "code", "detail"),
    [
        (None, 503, OPERATOR_UNAVAILABLE_DETAIL),
        ("not_a_status", 503, OPERATOR_UNAVAILABLE_DETAIL),
        (EntitlementStatus.EXPIRED, 403, "gpu_control_forbidden"),
        (EntitlementStatus.PAST_DUE, 403, "gpu_control_forbidden"),
    ],
)
async def test_gpu_intent_fail_closed_missing_unknown_expired_pastdue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    status_value: str | EntitlementStatus | None,
    code: int,
    detail: str,
) -> None:
    if status_value is None:
        repo = _EntitlementRepo({})
    else:
        repo = _status_repo(status_value)
    async with _gpu_client(monkeypatch, tmp_path, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        admission,
        writes,
        _repo,
    ):
        response = await client.post("/scene/gpu/intent", json={"action": "start"})

    assert response.status_code == code
    assert response.json()["detail"] == detail
    assert writes == []
    assert admission.reserves == []


@pytest.mark.asyncio
async def test_gpu_intent_outage_fail_closed_rolls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    session = _TrackingSession()
    repo = _EntitlementRepo(error=RuntimeError("entitlement lookup failed"), session=session)
    async with _gpu_client(monkeypatch, tmp_path, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        admission,
        writes,
        _repo,
    ):
        response = await client.post("/scene/gpu/intent", json={"action": "start"})

    assert response.status_code == 503
    assert response.json()["detail"] == OPERATOR_UNAVAILABLE_DETAIL
    assert writes == []
    assert admission.reserves == []
    assert session.rollback_calls >= 1


@pytest.mark.asyncio
async def test_gpu_intent_allows_paid_existing_write_role_without_manufacturing_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    auth = _operator_auth()
    assert auth.is_admin is False
    async with _gpu_client(monkeypatch, tmp_path, auth=auth) as (client, admission, writes, repo):
        response = await client.post("/scene/gpu/intent", json={"action": "start", "ttl_seconds": 90})

    assert response.status_code == 202
    assert response.json()["intent"]["action"] == "start"
    assert len(writes) == 1
    assert admission.reserves == []
    assert admission.commits == []
    assert auth.is_admin is False
    assert repo.gets == [PORTAL_TENANT]


@pytest.mark.asyncio
async def test_gpu_status_polling_is_free_for_beta_and_operator(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    for auth, repo in (
        (_beta_standard_auth(), _status_repo(EntitlementStatus.BETA_ACTIVE)),
        (_portal_principal(), _paid_repo()),
        (_operator_auth(), _paid_repo()),
    ):
        async with _gpu_client(monkeypatch, tmp_path, auth=auth, entitlement_repository=repo) as (
            client,
            admission,
            writes,
            used_repo,
        ):
            first = await client.get("/scene/gpu/status")
            second = await client.get("/scene/gpu/status")

        assert first.status_code == 200
        assert second.status_code == 200
        assert writes == []
        assert admission.reserves == []
        assert admission.commits == []
        assert used_repo.gets == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_clustering_jobs_deny_beta_standard_before_compute_or_job_create(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    repo = _status_repo(EntitlementStatus.BETA_ACTIVE)
    async with _cluster_client(monkeypatch, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        cluster_spy,
        job_service,
        admission,
        revert_calls,
        used_repo,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": mode, "is_beta": False, "entitlement_status": "paid_active"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == OPERATOR_FORBIDDEN_DETAIL
    assert cluster_spy.calls == []
    assert job_service.repository.jobs == {}
    assert admission.reserves == []
    assert admission.commits == []
    assert revert_calls == []
    assert used_repo.gets == [PORTAL_TENANT]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_clustering_jobs_deny_portal_even_when_paid(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    async with _cluster_client(monkeypatch, auth=_portal_principal(), entitlement_repository=_paid_repo()) as (
        client,
        cluster_spy,
        job_service,
        admission,
        revert_calls,
        repo,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": mode},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == OPERATOR_FORBIDDEN_DETAIL
    assert cluster_spy.calls == []
    assert job_service.repository.jobs == {}
    assert admission.reserves == []
    assert revert_calls == []
    assert repo.gets == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
async def test_clustering_jobs_preserve_paid_existing_write_role(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    auth = _operator_auth()
    assert auth.is_admin is False
    async with _cluster_client(monkeypatch, auth=auth) as (
        client,
        cluster_spy,
        job_service,
        admission,
        _revert_calls,
        repo,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": mode, "is_beta": True},
        )

    assert response.status_code == 202
    assert admission.reserves == []
    assert admission.commits == []
    assert auth.is_admin is False
    assert repo.gets == [PORTAL_TENANT]
    if mode == "sync":
        assert cluster_spy.calls == [TENANT_ID]
    else:
        assert job_service.repository.jobs


@pytest.mark.asyncio
async def test_clustering_jobs_use_clustering_pool_when_business_session_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clustering_session = _TrackingSession()
    repo = _paid_repo(session=clustering_session)

    def _clustering_session_factory() -> _TrackingSession:
        return clustering_session

    def _repo_from_session(session: Any) -> Any:
        assert session is clustering_session
        return repo

    monkeypatch.setattr(operator_authorization_module, "clustering_async_session_factory", _clustering_session_factory)
    monkeypatch.setattr(operator_authorization_module, "_repository_from_session", _repo_from_session)

    async with _cluster_client(
        monkeypatch,
        auth=_operator_auth(),
        entitlement_repository=repo,
        business_session_available=False,
        override_entitlement_repository=False,
    ) as (client, cluster_spy, _job_service, _admission, _revert_calls, _repo):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": "sync"},
        )

    assert response.status_code == 202
    assert repo.gets == [PORTAL_TENANT]
    assert clustering_session.commit_calls == 1
    assert clustering_session.close_calls == 1
    assert cluster_spy.calls == [TENANT_ID]


@pytest.mark.asyncio
async def test_clustering_jobs_reject_tenant_mismatch_before_work(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        cluster_spy,
        job_service,
        admission,
        _revert_calls,
        repo,
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
    assert repo.gets == [PORTAL_TENANT]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_value", "code"),
    [
        (None, 503),
        ("mystery", 503),
        (EntitlementStatus.EXPIRED, 403),
        (EntitlementStatus.PAST_DUE, 403),
    ],
)
async def test_clustering_jobs_fail_closed_missing_unknown_expired(
    monkeypatch: pytest.MonkeyPatch, status_value: str | EntitlementStatus | None, code: int
) -> None:
    repo = _EntitlementRepo({}) if status_value is None else _status_repo(status_value)
    async with _cluster_client(monkeypatch, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        cluster_spy,
        job_service,
        admission,
        revert_calls,
        _repo,
    ):
        response = await client.post(
            "/recognition/clustering/jobs",
            json={"tenant_id": TENANT_ID, "mode": "async"},
        )

    assert response.status_code == code
    assert cluster_spy.calls == []
    assert job_service.repository.jobs == {}
    assert admission.reserves == []
    assert revert_calls == []


@pytest.mark.asyncio
async def test_recover_orphans_denies_beta_standard_before_recluster(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _status_repo(EntitlementStatus.BETA_ACTIVE)
    async with _cluster_client(monkeypatch, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        cluster_spy,
        _jobs,
        admission,
        _revert_calls,
        used_repo,
    ):
        response = await client.post(
            "/recognition/clusters/recover-orphans",
            json={"tenant_id": TENANT_ID, "is_beta": False, "plan_code": "paid"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == OPERATOR_FORBIDDEN_DETAIL
    assert cluster_spy.calls == []
    assert admission.reserves == []
    assert used_repo.gets == [PORTAL_TENANT]


@pytest.mark.asyncio
async def test_recover_orphans_operator_and_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        cluster_spy,
        _jobs,
        admission,
        _revert_calls,
        repo,
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
    assert repo.gets == [PORTAL_TENANT, PORTAL_TENANT]


@pytest.mark.asyncio
async def test_cluster_revert_denies_beta_standard_before_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _status_repo(EntitlementStatus.BETA_ACTIVE)
    async with _cluster_client(monkeypatch, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
        used_repo,
    ):
        response = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4()), "is_beta": False, "entitlement_status": "paid_active"},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == OPERATOR_FORBIDDEN_DETAIL
    assert revert_calls == []
    assert admission.reserves == []
    assert used_repo.gets == [PORTAL_TENANT]


@pytest.mark.asyncio
async def test_cluster_revert_outage_fail_closed_no_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _TrackingSession()
    repo = _EntitlementRepo(error=RuntimeError("db unavailable"), session=session)
    async with _cluster_client(monkeypatch, auth=_beta_standard_auth(), entitlement_repository=repo) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
        _repo,
    ):
        response = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4())},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == OPERATOR_UNAVAILABLE_DETAIL
    assert revert_calls == []
    assert admission.reserves == []
    assert session.rollback_calls >= 1


@pytest.mark.asyncio
async def test_cluster_revert_operator_and_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _cluster_client(monkeypatch, auth=_operator_auth(), tenant_id=OTHER_TENANT_ID) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
        repo,
    ):
        mismatch = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4())},
        )

    assert mismatch.status_code == 403
    assert mismatch.json()["detail"] == "tenant mismatch"
    assert revert_calls == []
    assert admission.reserves == []
    assert repo.gets == [PORTAL_TENANT]

    async with _cluster_client(monkeypatch, auth=_operator_auth()) as (
        client,
        _cluster_spy,
        _jobs,
        admission,
        revert_calls,
        repo,
    ):
        ok = await client.post(
            f"/recognition/clusters/{uuid4()}/revert-merge",
            json={"receipt_id": str(uuid4())},
        )

    assert ok.status_code == 200
    assert revert_calls
    assert admission.reserves == []
    assert admission.commits == []
    assert repo.gets == [PORTAL_TENANT]

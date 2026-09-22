"""Authenticated GET /recognition/jobs/{job_id} FREE-POLL contract census.

Proves production API-key auth, tenant fencing, and zero usage admission on
status reads. External compute is not invoked; require_auth and tenant scope
stay on the real dependency path.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from recognition.domain.job import Job, JobStatus, JobType
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.deps import auth as auth_module
from recognition.interface_adapters.http.deps import rate_limit as rate_limit_module
from recognition.interface_adapters.http.routers import analyze as analyze_router
from recognition.tests.api.conftest import FakeSession
from recognition.tests.fakes import FakeJobService

OWNER_KEY = "owner-job-status-key"
OTHER_KEY = "other-job-status-key"


class _AdmissionSpy:
    """Records usage-ledger calls; GET status must never touch them."""

    def __init__(self) -> None:
        self.reserves: list[dict[str, object]] = []
        self.commits: list[UsageTicket] = []
        self.releases: list[UsageTicket] = []

    async def reserve(self, tenant_id, **kwargs):  # noqa: ANN001, ANN003
        self.reserves.append({"tenant_id": tenant_id, **kwargs})
        raise AssertionError("GET /recognition/jobs/{job_id} must not reserve usage")

    async def commit(self, ticket: UsageTicket) -> None:
        self.commits.append(ticket)
        raise AssertionError("GET /recognition/jobs/{job_id} must not commit usage")

    async def release(self, ticket: UsageTicket) -> None:
        self.releases.append(ticket)
        raise AssertionError("GET /recognition/jobs/{job_id} must not release usage")


@dataclass
class _CensusHarness:
    client: TestClient
    admission: _AdmissionSpy
    job_service: FakeJobService
    owner_tenant: str
    other_tenant: str
    admit_usage_calls: list[dict[str, object]] = field(default_factory=list)


def _enable_production_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    monkeypatch.setenv("RECOGNITION_RUNTIME_MODE", "production")


def _seed_job(job_service: FakeJobService, *, tenant_id: str, job_type: JobType, status: JobStatus, **payload) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        type=job_type,
        tenant_id=tenant_id,
        status=status,
        progress_completed=1,
        progress_total=1,
        message="census-job",
        payload=payload or None,
    )
    job_service.repository.jobs[job.id] = job
    return job


def _census_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    lookup: Callable[..., object] | None,
) -> _CensusHarness:
    """Build the analyze router with production auth and a usage-admission spy."""
    _enable_production_auth(monkeypatch)
    rate_limit_module._reset_state_for_tests()

    owner_tenant = str(uuid.uuid4())
    other_tenant = str(uuid.uuid4())
    admission = _AdmissionSpy()
    job_service = FakeJobService()
    admit_usage_calls: list[dict[str, object]] = []

    key_map = {
        OWNER_KEY: (owner_tenant, str(uuid.uuid4()), "STANDARD", False),
        OTHER_KEY: (other_tenant, str(uuid.uuid4()), "STANDARD", False),
    }

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        if lookup is not None:
            return await lookup(api_key, settings, session)
        if api_key not in key_map:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid or missing API key")
        return key_map[api_key]

    monkeypatch.setattr(auth_module, "_lookup_api_key", _fake_lookup)

    @asynccontextmanager
    async def _forbid_admit_usage(*args, **kwargs):  # noqa: ANN002, ANN003
        admit_usage_calls.append({"args": args, "kwargs": kwargs})
        raise AssertionError("GET /recognition/jobs/{job_id} must not enter admit_usage")
        yield None  # pragma: no cover

    monkeypatch.setattr(analyze_router, "admit_usage", _forbid_admit_usage)

    app = FastAPI()
    app.include_router(analyze_router.router, prefix="/recognition")
    app.state.usage_admission_service = admission

    async def _session_dep():
        yield FakeSession()

    async def _job_service_dep():
        return job_service

    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_job_service_dependency] = _job_service_dep

    return _CensusHarness(
        client=TestClient(app),
        admission=admission,
        job_service=job_service,
        owner_tenant=owner_tenant,
        other_tenant=other_tenant,
        admit_usage_calls=admit_usage_calls,
    )


def _owner_headers(tenant_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {OWNER_KEY}", "X-Tenant-ID": tenant_id}


def _other_headers(tenant_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {OTHER_KEY}"}
    if tenant_id is not None:
        headers["X-Tenant-ID"] = tenant_id
    return headers


def test_missing_api_key_denied_under_production_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof: production require_auth rejects a missing key. No ledger writes."""

    async def _lookup_must_not_run(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("missing Authorization must fail before API-key lookup")

    harness = _census_harness(monkeypatch, lookup=_lookup_must_not_run)
    job = _seed_job(
        harness.job_service,
        tenant_id=harness.owner_tenant,
        job_type=JobType.ANALYZE,
        status=JobStatus.RUNNING,
    )

    resp = harness.client.get(f"/recognition/jobs/{job.id}", headers={"X-Tenant-ID": harness.owner_tenant})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Authorization header required"
    assert harness.admission.reserves == []
    assert harness.admission.commits == []
    assert harness.admit_usage_calls == []


def test_invalid_api_key_denied_under_production_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof: production require_auth + DB key lookup rejects an unknown key."""
    _enable_production_auth(monkeypatch)
    rate_limit_module._reset_state_for_tests()
    job_service = FakeJobService()
    admission = _AdmissionSpy()
    job = _seed_job(
        job_service,
        tenant_id=str(uuid.uuid4()),
        job_type=JobType.ANALYZE,
        status=JobStatus.RUNNING,
    )

    app = FastAPI()
    app.include_router(analyze_router.router, prefix="/recognition")
    app.state.usage_admission_service = admission

    async def _session_dep():
        yield FakeSession()

    async def _job_service_dep():
        return job_service

    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_job_service_dependency] = _job_service_dep
    client = TestClient(app)

    resp = client.get(
        f"/recognition/jobs/{job.id}",
        headers={"Authorization": "Bearer not-a-db-key", "X-Tenant-ID": job.tenant_id},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "invalid or missing API key"
    assert admission.reserves == []
    assert admission.commits == []


def test_owner_poll_returns_200_without_usage_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof: authenticated owner poll is 200 FREE-POLL; ledger unchanged."""
    harness = _census_harness(monkeypatch, lookup=None)
    job = _seed_job(
        harness.job_service,
        tenant_id=harness.owner_tenant,
        job_type=JobType.ANALYZE,
        status=JobStatus.RUNNING,
    )

    resp = harness.client.get(f"/recognition/jobs/{job.id}", headers=_owner_headers(harness.owner_tenant))

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == job.id
    assert body["type"] == "analyze"
    assert body["status"] == "running"
    assert harness.admission.reserves == []
    assert harness.admission.commits == []
    assert harness.admission.releases == []
    assert harness.admit_usage_calls == []


def test_other_tenant_cannot_read_job_even_by_spoofing_query_tenant_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proof: another tenant cannot read the job, including query tenant_id spoof.

    Handler/auth-boundary proof (in-memory job service). Not PostgreSQL RLS.
    """
    harness = _census_harness(monkeypatch, lookup=None)
    job = _seed_job(
        harness.job_service,
        tenant_id=harness.owner_tenant,
        job_type=JobType.ANALYZE,
        status=JobStatus.RUNNING,
    )

    spoofed = harness.client.get(
        f"/recognition/jobs/{job.id}",
        params={"tenant_id": harness.owner_tenant},
        headers=_other_headers(),
    )
    matching_other = harness.client.get(
        f"/recognition/jobs/{job.id}",
        params={"tenant_id": harness.owner_tenant},
        headers=_other_headers(harness.other_tenant),
    )

    assert spoofed.status_code == 404, spoofed.text
    assert spoofed.json()["detail"] == "Job not found"
    assert matching_other.status_code == 404, matching_other.text
    assert matching_other.json()["detail"] == "Job not found"
    assert harness.admission.reserves == []
    assert harness.admit_usage_calls == []


def test_unknown_job_is_404_without_usage_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof: authenticated unknown-job poll is 404 and does not reserve."""
    harness = _census_harness(monkeypatch, lookup=None)
    missing_id = str(uuid.uuid4())

    resp = harness.client.get(f"/recognition/jobs/{missing_id}", headers=_owner_headers(harness.owner_tenant))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Job not found"
    assert harness.admission.reserves == []
    assert harness.admission.commits == []
    assert harness.admit_usage_calls == []


def test_pipeline_followup_is_tenant_scoped_and_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """Proof: linked clustering follow-up is still a free tenant-scoped read."""
    harness = _census_harness(monkeypatch, lookup=None)
    scan_job = _seed_job(
        harness.job_service,
        tenant_id=harness.owner_tenant,
        job_type=JobType.ANALYZE,
        status=JobStatus.COMPLETED,
    )
    _seed_job(
        harness.job_service,
        tenant_id=harness.owner_tenant,
        job_type=JobType.CLUSTERING,
        status=JobStatus.RUNNING,
        scan_job_id=scan_job.id,
    )

    owner = harness.client.get(f"/recognition/jobs/{scan_job.id}", headers=_owner_headers(harness.owner_tenant))
    other = harness.client.get(
        f"/recognition/jobs/{scan_job.id}",
        params={"tenant_id": harness.owner_tenant},
        headers=_other_headers(harness.other_tenant),
    )

    assert owner.status_code == 200
    body = owner.json()
    assert body["id"] == scan_job.id
    assert body["type"] == "clustering"
    assert body["status"] == "running"
    assert other.status_code == 404, other.text
    assert other.json()["detail"] == "Job not found"
    assert harness.admission.reserves == []
    assert harness.admit_usage_calls == []

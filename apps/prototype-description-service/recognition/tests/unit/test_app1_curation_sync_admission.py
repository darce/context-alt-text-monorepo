from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException

from recognition.application.services.usage_admission_service import AllowanceExceededError
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import auth as auth_deps
from recognition.interface_adapters.http.deps import get_optional_session
from roster.application.curation_sync_service import CurationSyncResult
from roster.interface_adapters.http import curation_router

TENANT_ID = UUID("c1ca4f2b-6d49-4d1f-8529-5f5a99ad8c17")
OTHER_TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


class _FakeAdmission:
    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.reserves: list[dict[str, object]] = []
        self.commits: list[UsageTicket] = []
        self.releases: list[UsageTicket] = []

    async def reserve(
        self,
        tenant_id,
        *,
        idempotency_key,
        job_id,
        cost_units,
        operation_id=None,
        request_fingerprint=None,
        queue_bytes=0,
    ):
        self.reserves.append(
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "job_id": job_id,
                "cost_units": cost_units,
                "operation_id": operation_id,
                "request_fingerprint": request_fingerprint,
                "queue_bytes": queue_bytes,
            }
        )
        if self.refuse:
            raise AllowanceExceededError()
        return UsageTicket(
            uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=operation_id or idempotency_key,
            request_fingerprint=request_fingerprint or idempotency_key,
        )

    async def commit(self, ticket: UsageTicket) -> None:
        self.commits.append(ticket)

    async def release(self, ticket: UsageTicket) -> None:
        self.releases.append(ticket)


def _payload(*, idempotency_key: str = "idem-1") -> dict[str, object]:
    return {
        "operation_type": "cluster_person_bound",
        "entity_type": "cluster",
        "entity_key": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e",
        "idempotency_key": idempotency_key,
        "expected_base_version": 10,
        "local_revision": 3,
        "payload": {
            "cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e",
            "person_uuid": "cd2cb6f1-0d2e-4d23-95ad-446cc741b6d2",
        },
    }


def _configure_auth(monkeypatch: pytest.MonkeyPatch, authenticated_tenant: UUID = TENANT_ID) -> None:
    monkeypatch.setattr(
        auth_deps,
        "get_security_settings",
        lambda: SimpleNamespace(
            auth_enabled=True,
            api_key_header="x-api-key",
            api_key_hash_algorithm="sha256",
        ),
    )

    async def _lookup_api_key(*_args, **_kwargs):
        return str(authenticated_tenant), None, None, False

    monkeypatch.setattr(auth_deps, "_lookup_api_key", _lookup_api_key)


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    admission: _FakeAdmission | None,
    *,
    authenticated_tenant: UUID = TENANT_ID,
    override_auth: bool = True,
) -> FastAPI:
    _configure_auth(monkeypatch, authenticated_tenant)
    app = FastAPI()
    app.include_router(curation_router.router, prefix="/roster")
    if admission is not None:
        app.state.usage_admission_service = admission

    async def _session_override() -> AsyncIterator[object]:
        yield object()

    async def _no_session():
        return None

    async def _job_service_override() -> object:
        return object()

    async def _tenant_context_override(_session, _tenant_id) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(curation_router, "set_tenant_context", _tenant_context_override)
    app.dependency_overrides.update(
        {
            curation_router.get_session: _session_override,
            get_optional_session: _no_session,
            curation_router.get_curation_sync_job_service: _job_service_override,
        }
    )
    if override_auth:
        async def _authenticated_tenant_override() -> str:
            return str(authenticated_tenant)

        app.dependency_overrides[curation_router.get_authenticated_tenant_id] = _authenticated_tenant_override
    return app


async def _post(app: FastAPI, *, json: dict[str, object], headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.post("/roster/curation/sync", headers=headers, json=json)


def test_curation_sync_requires_authentication_before_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    client = _build_client(monkeypatch, admission, override_auth=False)

    response = asyncio.run(_post(client, json=_payload()))

    assert response.status_code == 401
    assert admission.reserves == []


def test_curation_sync_uses_authenticated_tenant_and_commits_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = _FakeAdmission()
    captured: dict[str, object] = {}

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001
        captured["tenant_id"] = tenant_id
        captured["idempotency_key"] = operation.idempotency_key
        return CurationSyncResult(status="acknowledged", backend_version=23)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)
    client = _build_client(monkeypatch, admission)

    response = asyncio.run(
        _post(
            client,
            headers={"X-Api-Key": "verified-api-key"},
            json=_payload(idempotency_key="idem-authenticated"),
        )
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "acknowledged",
        "backend_version": 23,
        "idempotency_key": "idem-authenticated",
    }
    assert captured == {
        "tenant_id": str(TENANT_ID),
        "idempotency_key": "idem-authenticated",
    }
    assert len(admission.reserves) == 1
    assert admission.reserves[0]["tenant_id"] == TENANT_ID
    assert admission.reserves[0]["cost_units"] == 1
    assert admission.reserves[0]["operation_id"] == admission.reserves[0]["idempotency_key"]
    assert admission.reserves[0]["request_fingerprint"]
    assert len(admission.commits) == 1
    assert admission.releases == []


def test_verified_auth_rejects_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_auth(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_deps.require_auth(
                background_tasks=BackgroundTasks(),
                authorization=None,
                x_tenant_id=str(OTHER_TENANT_ID),
                api_key_header_value="verified-api-key",
                session=None,
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "tenant mismatch"


def test_curation_sync_maps_admission_refusal_to_contract_error(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission(refuse=True)
    client = _build_client(monkeypatch, admission)

    response = asyncio.run(
        _post(
            client,
            headers={"X-Api-Key": "verified-api-key"},
            json=_payload(),
        )
    )

    assert response.status_code == 402
    assert response.json()["detail"] == {"error": "allowance_exhausted"}
    assert len(admission.reserves) == 1
    assert admission.commits == []
    assert admission.releases == []


def test_curation_sync_batch_admits_each_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()
    captured: dict[str, object] = {}

    async def _fake_apply_batch(self, tenant_id: str, operations):  # noqa: ANN001
        captured["tenant_id"] = tenant_id
        captured["operation_count"] = len(operations)
        return [CurationSyncResult(status="acknowledged", backend_version=index) for index, _ in enumerate(operations)]

    monkeypatch.setattr(curation_router.CurationSyncService, "apply_batch", _fake_apply_batch)
    client = _build_client(monkeypatch, admission)

    response = asyncio.run(
        _post(
            client,
            headers={"X-Api-Key": "verified-api-key"},
            json={
                "operations": [
                    _payload(idempotency_key="idem-batch-1"),
                    _payload(idempotency_key="idem-batch-2"),
                ]
            },
        )
    )

    assert response.status_code == 200
    assert captured == {"tenant_id": str(TENANT_ID), "operation_count": 2}
    assert len(admission.reserves) == 2
    assert [reserve["cost_units"] for reserve in admission.reserves] == [1, 1]
    assert len(admission.commits) == 2


def test_curation_sync_allowance_is_charged_once_per_operation_key(monkeypatch: pytest.MonkeyPatch) -> None:
    admission = _FakeAdmission()

    async def _fake_apply_batch(self, tenant_id: str, operations):  # noqa: ANN001
        return [CurationSyncResult(status="acknowledged", backend_version=index) for index, _ in enumerate(operations)]

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001
        return CurationSyncResult(status="acknowledged", backend_version=1)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply_batch", _fake_apply_batch)
    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)
    client = _build_client(monkeypatch, admission)

    for body in (
        {"operations": [_payload(idempotency_key="idem-a"), _payload(idempotency_key="idem-b")]},
        {"operations": [_payload(idempotency_key="idem-b"), _payload(idempotency_key="idem-a")]},
        _payload(idempotency_key="idem-a"),
    ):
        response = asyncio.run(_post(client, headers={"X-Api-Key": "verified-api-key"}, json=body))
        assert response.status_code == 200

    expected_operation_ids = {
        curation_router.build_usage_operation_id(
            TENANT_ID,
            route="roster_curation_sync",
            idempotency_keys=[key],
        )
        for key in ("idem-a", "idem-b")
    }
    assert {reserve["operation_id"] for reserve in admission.reserves} == expected_operation_ids
    assert all(reserve["cost_units"] == 1 for reserve in admission.reserves)
    distinct_charges = {reserve["operation_id"]: reserve["cost_units"] for reserve in admission.reserves}
    assert sum(distinct_charges.values()) == 2


def test_curation_sync_fails_closed_when_admission_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch, None)

    response = asyncio.run(
        _post(
            client,
            headers={"X-Api-Key": "verified-api-key"},
            json=_payload(),
        )
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "usage_admission_unavailable"}

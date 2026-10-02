from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI

from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import auth as auth_deps
from recognition.interface_adapters.http.deps import (
    get_cluster_service_builder,
    get_optional_session,
)
from recognition.interface_adapters.http.deps import services as service_deps
from roster.application.curation_sync_service import CurationSyncResult
from roster.interface_adapters.http import curation_router

TENANT_ID = "c1ca4f2b-6d49-4d1f-8529-5f5a99ad8c17"
OTHER_TENANT_ID = "11111111-1111-1111-1111-111111111111"
AUTH_HEADERS = {"X-Api-Key": "verified-api-key"}


class _SyncTestClient:
    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def post(self, *args, **kwargs) -> httpx.Response:  # noqa: ANN002, ANN003
        async def _post() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=self.app),
                base_url="http://testserver",
            ) as client:
                return await client.post(*args, **kwargs)

        return asyncio.run(_post())


class _FakeAdmission:
    def __init__(self) -> None:
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


def _configure_auth(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(
        auth_deps,
        "get_security_settings",
        lambda: SimpleNamespace(
            auth_enabled=True,
            api_key_header="x-api-key",
            api_key_hash_algorithm="sha256",
        ),
    )

    async def _lookup_api_key(*_args, **_kwargs):  # noqa: ANN002, ANN003
        return TENANT_ID, None, None, False

    monkeypatch.setattr(auth_deps, "_lookup_api_key", _lookup_api_key)


def _build_client(
    monkeypatch,
    *,
    override_job_service: bool = True,
) -> tuple[_SyncTestClient, _FakeAdmission]:  # noqa: ANN001
    _configure_auth(monkeypatch)
    app = FastAPI()
    app.include_router(curation_router.router, prefix="/roster")
    admission = _FakeAdmission()
    app.state.usage_admission_service = admission

    async def _session_override() -> AsyncIterator[object]:
        yield object()

    async def _no_session() -> None:
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
        }
    )
    if override_job_service:
        app.dependency_overrides[curation_router.get_curation_sync_job_service] = _job_service_override
    return _SyncTestClient(app), admission


def _payload(operation_type: str, *, idempotency_key: str = "idem-1") -> dict[str, object]:
    return {
        "operation_type": operation_type,
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


def test_curation_sync_router_passes_authenticated_tenant_and_returns_acknowledged(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001
        captured["tenant_id"] = tenant_id
        captured["operation_type"] = operation.operation_type
        return CurationSyncResult(status="acknowledged", backend_version=23)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)

    client, admission = _build_client(monkeypatch)
    response = client.post(
        "/roster/curation/sync",
        headers=AUTH_HEADERS,
        json=_payload("cluster_person_bound", idempotency_key="idem-ack"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "acknowledged",
        "backend_version": 23,
        "idempotency_key": "idem-ack",
    }
    assert captured["tenant_id"] == TENANT_ID
    assert captured["operation_type"] == "cluster_person_bound"
    assert len(admission.reserves) == 1
    assert admission.reserves[0]["tenant_id"] == UUID(TENANT_ID)


def test_curation_sync_preflight_uses_authenticated_tenant_with_forged_tenant_inputs(monkeypatch) -> None:
    cluster_tenant_lookups: list[str] = []

    class _Session:
        async def execute(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return None

    async def _authenticated_tenant_override():
        return auth_deps.AuthContext(
            token="verified-api-key",
            tenant_claim=TENANT_ID,
            api_key_id="key-a",
            enabled=True,
        )

    async def _session_override():
        return _Session()

    async def _cluster_service_builder_override():
        async def _build(tenant_id: str):
            cluster_tenant_lookups.append(tenant_id)
            return object()

        return _build

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001, ARG001
        assert tenant_id == TENANT_ID
        return CurationSyncResult(status="acknowledged", backend_version=23)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)
    monkeypatch.setattr(service_deps, "set_tenant_context", _tenant_context_noop)
    client, _admission = _build_client(monkeypatch, override_job_service=False)
    client.app.dependency_overrides.update(
        {
            auth_deps.require_auth: _authenticated_tenant_override,
            get_optional_session: _session_override,
            get_cluster_service_builder: _cluster_service_builder_override,
        }
    )

    response = client.post(
        f"/roster/curation/sync?tenant_id={OTHER_TENANT_ID}",
        headers={**AUTH_HEADERS, "X-Tenant-ID": str(OTHER_TENANT_ID)},
        json=_payload("cluster_person_bound"),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "acknowledged",
        "backend_version": 23,
        "idempotency_key": "idem-1",
    }
    assert cluster_tenant_lookups == [TENANT_ID]


async def _tenant_context_noop(_session, _tenant_id) -> None:  # noqa: ANN001
    return None


def test_curation_sync_router_maps_conflict_to_409(monkeypatch) -> None:
    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001, ARG001
        return CurationSyncResult(
            status="conflict",
            backend_version=41,
            conflict_code="version_conflict",
            machine_payload={"cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e"},
        )

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)

    client, _admission = _build_client(monkeypatch)
    response = client.post(
        "/roster/curation/sync",
        headers=AUTH_HEADERS,
        json=_payload("cluster_person_bound", idempotency_key="idem-conflict"),
    )

    assert response.status_code == 409
    assert response.json() == {
        "status": "conflict",
        "conflict_code": "version_conflict",
        "backend_version": 41,
        "machine_payload": {"cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e"},
    }


def test_curation_sync_router_requires_authentication(monkeypatch) -> None:
    client, admission = _build_client(monkeypatch)
    response = client.post(
        "/roster/curation/sync",
        headers={"X-Tenant-ID": TENANT_ID},
        json=_payload("cluster_person_bound"),
    )

    assert response.status_code == 401
    assert admission.reserves == []


def test_curation_sync_router_returns_batch_results(monkeypatch) -> None:
    async def _fake_apply_batch(self, tenant_id: str, operations):  # noqa: ANN001
        assert tenant_id == TENANT_ID
        assert len(operations) == 2
        return [
            CurationSyncResult(status="acknowledged", backend_version=11),
            CurationSyncResult(
                status="conflict",
                backend_version=12,
                conflict_code="version_conflict",
                machine_payload={"cluster_uuid": operations[1].entity_key},
            ),
        ]

    monkeypatch.setattr(curation_router.CurationSyncService, "apply_batch", _fake_apply_batch)

    client, _admission = _build_client(monkeypatch)
    response = client.post(
        "/roster/curation/sync",
        headers=AUTH_HEADERS,
        json={
            "operations": [
                _payload("cluster_person_bound", idempotency_key="idem-1"),
                _payload("cluster_person_unbound", idempotency_key="idem-2"),
            ]
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "status": "acknowledged",
                "backend_version": 11,
                "idempotency_key": "idem-1",
            },
            {
                "status": "conflict",
                "backend_version": 12,
                "idempotency_key": "idem-2",
                "conflict_code": "version_conflict",
                "machine_payload": {"cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e"},
            },
        ]
    }


def test_curation_sync_router_accepts_cluster_label_updated(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001
        captured["tenant_id"] = tenant_id
        captured["operation_type"] = operation.operation_type
        captured["label"] = operation.payload["label"]
        return CurationSyncResult(status="acknowledged", backend_version=33)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)

    client, _admission = _build_client(monkeypatch)
    response = client.post(
        "/roster/curation/sync",
        headers=AUTH_HEADERS,
        json={
            **_payload("cluster_label_updated", idempotency_key="idem-label"),
            "payload": {
                "cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e",
                "label": "Known Person",
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "acknowledged",
        "backend_version": 33,
        "idempotency_key": "idem-label",
    }
    assert captured == {
        "tenant_id": TENANT_ID,
        "operation_type": "cluster_label_updated",
        "label": "Known Person",
    }

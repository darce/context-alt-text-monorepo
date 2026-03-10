from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from roster.application.curation_sync_service import CurationSyncResult
from roster.interface_adapters.http import curation_router

TENANT_ID = "c1ca4f2b-6d49-4d1f-8529-5f5a99ad8c17"


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(curation_router.router, prefix="/roster")

    async def _session_override() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[curation_router.get_session] = _session_override
    return TestClient(app)


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


def test_curation_sync_router_passes_tenant_and_returns_acknowledged(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001
        captured["tenant_id"] = tenant_id
        captured["operation_type"] = operation.operation_type
        return CurationSyncResult(status="acknowledged", backend_version=23)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)

    client = _build_client()
    response = client.post(
        "/roster/curation/sync",
        headers={"X-Tenant-ID": TENANT_ID},
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


def test_curation_sync_router_maps_conflict_to_409(monkeypatch) -> None:
    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001, ARG001
        return CurationSyncResult(
            status="conflict",
            backend_version=41,
            conflict_code="version_conflict",
            machine_payload={"cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e"},
        )

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)

    client = _build_client()
    response = client.post(
        "/roster/curation/sync",
        headers={"X-Tenant-ID": TENANT_ID},
        json=_payload("cluster_person_bound", idempotency_key="idem-conflict"),
    )

    assert response.status_code == 409
    assert response.json() == {
        "status": "conflict",
        "conflict_code": "version_conflict",
        "backend_version": 41,
        "machine_payload": {"cluster_uuid": "8dd2c1d7-b9df-4d0d-9f47-265ff9ea5e7e"},
    }


def test_curation_sync_router_requires_tenant_header() -> None:
    client = _build_client()
    response = client.post(
        "/roster/curation/sync",
        json=_payload("cluster_person_bound"),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "tenant_id is required"


def test_curation_sync_router_accepts_legacy_md5_tenant_header(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_apply(self, tenant_id: str, operation):  # noqa: ANN001
        captured["tenant_id"] = tenant_id
        return CurationSyncResult(status="acknowledged", backend_version=5)

    monkeypatch.setattr(curation_router.CurationSyncService, "apply", _fake_apply)

    legacy_tenant = hashlib.md5(b"http://example.com").hexdigest()
    expected_tenant = str(UUID(legacy_tenant))

    client = _build_client()
    response = client.post(
        "/roster/curation/sync",
        headers={"X-Tenant-ID": legacy_tenant},
        json=_payload("cluster_person_bound", idempotency_key="idem-md5"),
    )

    assert response.status_code == 200
    assert captured["tenant_id"] == expected_tenant


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

    client = _build_client()
    response = client.post(
        "/roster/curation/sync",
        headers={"X-Tenant-ID": TENANT_ID},
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

    client = _build_client()
    response = client.post(
        "/roster/curation/sync",
        headers={"X-Tenant-ID": TENANT_ID},
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

"""API tests for retention endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.services import (
    get_audit_repository,
    get_retention_export_service,
    get_retention_policy_service,
    get_retention_purge_service,
)
from recognition.interface_adapters.http.routers import retention as retention_router
from recognition.tests.api.conftest import FakeSession


class FakeRetentionPolicyService:
    """In-memory policy service for HTTP tests."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.calls: list[tuple[str, str, str]] = []
        self.policy: dict[str, Any] = {
            "retention_mode": "retain_all",
            "last_export_at": None,
            "last_purge_at": None,
            "retention_updated_at": None,
        }

    async def get_policy(self, tenant_id: str) -> dict[str, Any]:
        self.calls.append(("get", tenant_id, ""))
        return dict(self.policy)

    async def update_policy(self, tenant_id: str, retention_mode: str, actor: str) -> dict[str, Any]:
        self.calls.append(("patch", tenant_id, actor))
        self.policy["retention_mode"] = retention_mode
        self.policy["retention_updated_at"] = datetime.now(tz=UTC)
        return dict(self.policy)


class FakeRetentionExportService:
    """In-memory export service for HTTP tests."""

    def __init__(self, tenant_id: str, *, count: int = 1) -> None:
        self.tenant_id = tenant_id
        self.count = count
        self.calls: list[tuple[str, str]] = []

    async def count_exportable_identities(self, tenant_id: str) -> int:
        assert tenant_id == self.tenant_id
        return self.count

    async def export_tenant_data(self, tenant_id: str, actor: str) -> dict[str, Any]:
        self.calls.append((tenant_id, actor))
        return {
            "tenant_id": tenant_id,
            "exported_at": datetime.now(tz=UTC),
            "schema_version": 1,
            "counts": {"clusters": 2, "members": 3},
            "data": {"clusters": [{"id": str(uuid.uuid4())}]},
        }


class FakeRetentionPurgeService:
    """In-memory purge service for HTTP tests."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.calls: list[tuple[str, str, str]] = []

    async def purge_tenant_data(self, tenant_id: str, actor: str, scope: str = "disposed") -> dict[str, Any]:
        self.calls.append((tenant_id, actor, scope))
        return {
            "tenant_id": tenant_id,
            "scope": scope,
            "deleted_counts": {"media_identities": 4, "identity_clusters": 2},
            "last_purge_at": datetime.now(tz=UTC),
        }


class FakeAuditRepository:
    """In-memory audit repository for HTTP tests."""

    def __init__(self) -> None:
        now = datetime.now(tz=UTC)
        self.items = [
            {
                "id": str(uuid.uuid4()),
                "event_type": "policy_updated",
                "actor": "api_key:test",
                "scope": "tenant",
                "payload": {"retention_mode": "dispose_after_ack"},
                "result_status": "success",
                "created_at": now,
            },
            {
                "id": str(uuid.uuid4()),
                "event_type": "export_completed",
                "actor": "api_key:test",
                "scope": "tenant",
                "payload": {"clusters": 2},
                "result_status": "success",
                "created_at": now,
            },
        ]

    async def list_events(self, tenant_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        assert tenant_id
        return self.items[offset : offset + limit]

    async def count_events(self, tenant_id: str) -> int:
        assert tenant_id
        return len(self.items)


def _build_client(
    monkeypatch,
    *,
    tenant_id: str | None = None,
    export_count: int = 1,
) -> tuple[TestClient, FakeRetentionPolicyService, FakeRetentionExportService, FakeRetentionPurgeService]:
    tenant_id = tenant_id or str(uuid.uuid4())
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    app = FastAPI()

    @app.get("/tenant-probe")
    async def tenant_probe(
        resolved_tenant_id: str = Depends(dependencies.get_authenticated_tenant_id),
    ) -> dict[str, str]:
        return {"tenant_id": resolved_tenant_id}

    app.include_router(recognition_router, prefix="/recognition")
    fake_session = FakeSession()
    policy_service = FakeRetentionPolicyService(tenant_id)
    export_service = FakeRetentionExportService(tenant_id, count=export_count)
    purge_service = FakeRetentionPurgeService(tenant_id)
    audit_repo = FakeAuditRepository()

    async def _session_dep():
        yield fake_session

    async def _policy_dep():
        return policy_service

    async def _export_dep():
        return export_service

    async def _purge_dep():
        return purge_service

    async def _audit_dep():
        return audit_repo

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_retention_policy_service] = _policy_dep
    app.dependency_overrides[dependencies.get_retention_export_service] = _export_dep
    app.dependency_overrides[dependencies.get_retention_purge_service] = _purge_dep
    app.dependency_overrides[dependencies.get_audit_repository] = _audit_dep
    return TestClient(app), policy_service, export_service, purge_service


def test_retention_policy_requires_authorization(monkeypatch) -> None:
    client, _, _, _ = _build_client(monkeypatch)

    response = client.get("/recognition/retention/policy")

    assert response.status_code == 401


def test_retention_policy_uses_authenticated_tenant_claim(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, policy_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/policy",
        params={"tenant_id": str(uuid.uuid4())},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    assert policy_service.calls == [("get", tenant_id, "")]


def test_authenticated_tenant_dependency_is_self_contained(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get("/tenant-probe", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 200
    assert response.json() == {"tenant_id": tenant_id}


def test_retention_policy_admin_requires_header_not_query_param(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "admin-key"
        return None, None, "enterprise", True

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/policy",
        params={"tenant_id": tenant_id},
        headers={"Authorization": "Bearer admin-key"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "X-Tenant-ID header required"


def test_patch_retention_policy_updates_mode(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, policy_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id-1234567890", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.patch(
        "/recognition/retention/policy",
        json={"retention_mode": "dispose_after_ack"},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["retention_mode"] == "dispose_after_ack"
    assert policy_service.calls[-1] == ("patch", tenant_id, "api_key:api-key-id-1")


def test_patch_retention_policy_invalid_mode_returns_400(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, policy_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.patch(
        "/recognition/retention/policy",
        json={"retention_mode": "invalid_mode"},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid retention_mode"
    assert policy_service.calls == []


def test_export_returns_inline_payload(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, export_service, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post("/recognition/retention/export", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["counts"] == {"clusters": 2, "members": 3}
    assert export_service.calls == [(tenant_id, "api_key:api-key-id")]


def test_coerce_export_response_preserves_real_service_shape() -> None:
    tenant_id = str(uuid.uuid4())

    response = retention_router._coerce_export_response(
        {
            "tenant_id": tenant_id,
            "exported_at": datetime.now(tz=UTC).isoformat(),
            "schema_version": 1,
            "clusters": [{"id": "cluster-1"}],
            "media_identities": [{"id": "identity-1"}],
            "identity_suggestions": [],
            "cluster_merge_suggestions": [],
            "scan_jobs": [{"id": "job-1"}],
        },
        tenant_id,
    )

    assert response.data["clusters"] == [{"id": "cluster-1"}]
    assert response.data["media_identities"] == [{"id": "identity-1"}]
    assert response.counts == {
        "clusters": 1,
        "media_identities": 1,
        "identity_suggestions": 0,
        "cluster_merge_suggestions": 0,
        "scan_jobs": 1,
    }


def test_export_enforces_size_guard(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id, export_count=3)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    monkeypatch.setattr(
        retention_router,
        "get_recognition_settings",
        lambda: SimpleNamespace(retention_export_max_identities=2),
    )
    response = client.post("/recognition/retention/export", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 413


def test_purge_requires_confirmation(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, purge_service = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/purge",
        json={"scope": "disposed", "confirm": False},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 422
    assert purge_service.calls == []


def test_purge_returns_deleted_counts(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, purge_service = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/purge",
        json={"scope": "all", "confirm": True},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    assert response.json()["deleted_counts"] == {"media_identities": 4, "identity_clusters": 2}
    assert purge_service.calls == [(tenant_id, "api_key:api-key-id", "all")]


def test_coerce_purge_response_accepts_purged_at_timestamp() -> None:
    tenant_id = str(uuid.uuid4())
    timestamp = datetime.now(tz=UTC).isoformat()

    response = retention_router._coerce_purge_response(
        {
            "tenant_id": tenant_id,
            "scope": "disposed",
            "deleted_counts": {"media_identities": 4},
            "purged_at": timestamp,
        },
        tenant_id,
        "disposed",
    )

    assert response.last_purge_at == datetime.fromisoformat(timestamp)


def test_purge_invalid_scope_returns_400(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, purge_service = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/purge",
        json={"scope": "nope", "confirm": True},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid scope"
    assert purge_service.calls == []


def test_audit_endpoint_returns_paginated_events(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/audit",
        params={"limit": 1, "offset": 1},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["event_type"] == "export_completed"


@pytest.mark.asyncio
async def test_retention_dependency_factories_return_real_implementations() -> None:
    session = FakeSession()

    policy_service = await get_retention_policy_service(session)
    export_service = await get_retention_export_service(session)
    purge_service = await get_retention_purge_service(session)
    audit_repository = await get_audit_repository(session)

    assert policy_service.__class__.__name__ == "RetentionPolicyService"
    assert export_service.__class__.__name__ == "TenantExportService"
    assert purge_service.__class__.__name__ == "TenantPurgeService"
    assert audit_repository.__class__.__name__ == "AuditRepository"

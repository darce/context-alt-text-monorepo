"""API tests for retention endpoints."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from recognition.application.services.export_service import EXPORT_SCHEMA_VERSION
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps.services import (
    get_audit_repository,
    get_retention_export_service,
    get_retention_import_service,
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

    async def apply_preset(self, tenant_id: str, preset_name: str, actor: str) -> dict[str, Any]:
        self.calls.append(("preset", tenant_id, actor))
        from recognition.application.services.retention_policy_service import RETENTION_PRESETS

        if preset_name not in RETENTION_PRESETS:
            raise ValueError(f"invalid preset: {preset_name!r}")
        config = RETENTION_PRESETS[preset_name]
        self.policy["retention_mode"] = config["retention_mode"]
        self.policy["retention_updated_at"] = datetime.now(tz=UTC)
        return {**self.policy, "preset": preset_name}


class FakeRetentionExportService:
    """In-memory export service for HTTP tests."""

    def __init__(self, tenant_id: str, *, count: int = 1) -> None:
        self.tenant_id = tenant_id
        self.count = count
        self.calls: list[tuple[str, str]] = []
        self._fake_job_id = "fake-export-job-id"

    async def count_exportable_identities(self, tenant_id: str) -> int:
        assert tenant_id == self.tenant_id
        return self.count

    async def export_tenant_data(self, tenant_id: str, actor: str) -> dict[str, Any]:
        self.calls.append((tenant_id, actor))
        return {
            "tenant_id": tenant_id,
            "exported_at": datetime.now(tz=UTC),
            "schema_version": EXPORT_SCHEMA_VERSION,
            "counts": {"clusters": 2, "members": 3},
            "data": {"clusters": [{"id": str(uuid.uuid4())}]},
        }

    async def start_async_export(self, tenant_id: str, actor: str) -> dict[str, Any]:
        self.calls.append((tenant_id, actor))
        return {"job_id": self._fake_job_id, "status": "pending"}

    async def get_export_status(self, job_id: str, tenant_id: str) -> dict[str, Any]:
        if job_id != self._fake_job_id:
            return {"error": "not_found"}
        return {
            "job_id": job_id,
            "status": "completed",
            "file_size": 1024,
            "error_message": None,
            "data_json": {
                "tenant_id": tenant_id,
                "exported_at": datetime.now(tz=UTC).isoformat(),
                "schema_version": EXPORT_SCHEMA_VERSION,
                "clusters": [{"id": str(uuid.uuid4())}],
            },
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


class FakeRetentionImportService:
    """In-memory import service for HTTP tests."""

    def __init__(self, tenant_id: str, *, raise_error: str | None = None) -> None:
        self.tenant_id = tenant_id
        self.raise_error = raise_error
        self.calls: list[tuple[str, str]] = []

    async def validate_and_import(self, data: dict[str, Any], tenant_id: str, actor: str) -> dict[str, Any]:
        if self.raise_error is not None:
            raise ValueError(self.raise_error)
        self.calls.append((tenant_id, actor))
        return {
            "tenant_id": tenant_id,
            "schema_version": data.get("schema_version", EXPORT_SCHEMA_VERSION),
            "imported_at": datetime.now(tz=UTC).isoformat(),
            "counts": {"clusters": 1},
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

    async def list_events(
        self, tenant_id: str, limit: int, offset: int, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        assert tenant_id
        filtered = [e for e in self.items if event_type is None or e["event_type"] == event_type]
        return filtered[offset : offset + limit]

    async def count_events(self, tenant_id: str, event_type: str | None = None) -> int:
        assert tenant_id
        if event_type is not None:
            return sum(1 for e in self.items if e["event_type"] == event_type)
        return len(self.items)


def _build_client(
    monkeypatch,
    *,
    tenant_id: str | None = None,
    export_count: int = 1,
    import_raises: str | None = None,
    session: FakeSession | None = None,
) -> tuple[
    TestClient,
    FakeRetentionPolicyService,
    FakeRetentionExportService,
    FakeRetentionPurgeService,
    FakeRetentionImportService,
]:
    tenant_id = tenant_id or str(uuid.uuid4())
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    app = FastAPI()

    @app.get("/tenant-probe")
    async def tenant_probe(
        resolved_tenant_id: str = Depends(dependencies.get_authenticated_tenant_id),
    ) -> dict[str, str]:
        return {"tenant_id": resolved_tenant_id}

    app.include_router(recognition_router, prefix="/recognition")
    fake_session = session or FakeSession()
    policy_service = FakeRetentionPolicyService(tenant_id)
    export_service = FakeRetentionExportService(tenant_id, count=export_count)
    purge_service = FakeRetentionPurgeService(tenant_id)
    import_service = FakeRetentionImportService(tenant_id, raise_error=import_raises)
    audit_repo = FakeAuditRepository()

    async def _session_dep():
        yield fake_session

    async def _policy_dep():
        return policy_service

    async def _export_dep():
        return export_service

    async def _purge_dep():
        return purge_service

    async def _import_dep():
        return import_service

    async def _audit_dep():
        return audit_repo

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_retention_policy_service] = _policy_dep
    app.dependency_overrides[dependencies.get_retention_export_service] = _export_dep
    app.dependency_overrides[dependencies.get_retention_purge_service] = _purge_dep
    app.dependency_overrides[dependencies.get_retention_import_service] = _import_dep
    app.dependency_overrides[dependencies.get_audit_repository] = _audit_dep
    return TestClient(app), policy_service, export_service, purge_service, import_service


def test_retention_policy_requires_authorization(monkeypatch) -> None:
    client, _, _, _, _ = _build_client(monkeypatch)

    response = client.get("/recognition/retention/policy")

    assert response.status_code == 401


def test_retention_policy_uses_authenticated_tenant_claim(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, policy_service, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get("/tenant-probe", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 200
    assert response.json() == {"tenant_id": tenant_id}


def test_retention_policy_auth_store_failure_stops_at_auth_boundary(monkeypatch) -> None:
    """Auth-store faults should fail before downstream retention services run."""
    tenant_id = str(uuid.uuid4())
    fake_session = FakeSession()
    fake_session.queue_execute_exception(Exception('relation "api_keys" does not exist'))
    fake_session.queue_execute_result(scalar=1)
    client, policy_service, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id, session=fake_session)

    response = client.get("/recognition/retention/policy", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 500
    assert response.json()["detail"] == "api key store unavailable"
    assert policy_service.calls == []
    assert fake_session.begin_nested_calls == 1
    assert fake_session.nested_rollback_calls == 1
    assert fake_session._savepoint_recovered is True
    assert len(fake_session._execute_results) == 1  # queued result unconsumed; downstream never ran


def test_retention_policy_admin_requires_header_not_query_param(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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
    client, policy_service, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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
    client, policy_service, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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


def test_export_starts_async_job(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, export_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)

    async def _noop(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr(retention_router, "run_export_to_file", _noop)
    response = client.post("/recognition/retention/export", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "fake-export-job-id"
    assert body["status"] == "pending"
    assert export_service.calls == [(tenant_id, "api_key:api-key-id")]


def test_export_large_tenant_proceeds_to_async_job(monkeypatch) -> None:
    """Large tenants must no longer be rejected with 413; they proceed via async job."""
    tenant_id = str(uuid.uuid4())
    # export_count=3 would have exceeded the old limit of 2; now it must succeed
    client, _, export_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id, export_count=3)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)

    async def _noop(*args: Any, **kwargs: Any) -> None:
        pass

    monkeypatch.setattr(retention_router, "run_export_to_file", _noop)
    response = client.post("/recognition/retention/export", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "fake-export-job-id"
    assert body["status"] == "pending"


def test_export_job_status_returns_current_status(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/export/fake-export-job-id/status",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "fake-export-job-id"
    assert body["status"] == "completed"
    assert body["file_size"] == 1024
    assert body["error_message"] is None


def test_export_job_status_returns_404_for_unknown_job(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/export/00000000-0000-0000-0000-000000000000/status",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 404


def test_export_job_data_returns_payload_when_completed(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/export/fake-export-job-id/data",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["schema_version"] == EXPORT_SCHEMA_VERSION


def test_export_job_data_returns_409_when_not_completed(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, export_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)

    # Override get_export_status to return a non-completed job

    async def _pending_status(job_id: str, tenant_id: str) -> dict[str, Any]:
        return {"job_id": job_id, "status": "running", "file_size": None, "error_message": None, "data_json": None}

    export_service.get_export_status = _pending_status

    response = client.get(
        "/recognition/retention/export/fake-export-job-id/data",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 409


def test_purge_requires_confirmation(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, purge_service, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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
    client, _, _, purge_service, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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
    client, _, _, purge_service, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

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


def test_audit_event_type_filter_returns_only_matching_events(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        assert api_key == "good-key"
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get(
        "/recognition/retention/audit",
        params={"event_type": "export_completed"},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["event_type"] == "export_completed"


def test_import_missing_data_field_returns_422(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/import",
        json={},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 422


def test_import_valid_payload_returns_summary(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, import_service = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    payload = {
        "data": {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "tenant_id": tenant_id,
            "clusters": [{"id": str(uuid.uuid4())}],
        }
    }
    response = client.post(
        "/recognition/retention/import",
        json=payload,
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["schema_version"] == EXPORT_SCHEMA_VERSION
    assert "imported_at" in body
    assert "counts" in body
    assert import_service.calls == [(tenant_id, "api_key:api-key-id")]


def test_import_service_error_returns_422(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(
        monkeypatch,
        tenant_id=tenant_id,
        import_raises="unsupported schema_version 999; maximum supported version is 2",
    )

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/import",
        json={"data": {"schema_version": 999}},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 422
    assert "schema_version" in response.json()["detail"]


@pytest.mark.asyncio
async def test_retention_dependency_factories_return_real_implementations() -> None:
    session = FakeSession()

    policy_service = await get_retention_policy_service(session)
    export_service = await get_retention_export_service(session)
    purge_service = await get_retention_purge_service(session)
    audit_repository = await get_audit_repository(session)
    import_service = await get_retention_import_service(session)

    assert policy_service.__class__.__name__ == "RetentionPolicyService"
    assert export_service.__class__.__name__ == "TenantExportService"
    assert purge_service.__class__.__name__ == "TenantPurgeService"
    assert audit_repository.__class__.__name__ == "AuditRepository"
    assert import_service.__class__.__name__ == "TenantImportService"


def test_apply_preset_gdpr_sets_dispose_after_ack(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, policy_service, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/policy/preset",
        json={"preset": "gdpr"},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["retention_mode"] == "dispose_after_ack"
    assert data["preset"] == "gdpr"
    assert ("preset", tenant_id, "api_key:api-key-id") in policy_service.calls


def test_apply_preset_invalid_name_returns_400(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/policy/preset",
        json={"preset": "unknown-preset"},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 400
    assert "preset" in response.json()["detail"].lower()


def test_apply_preset_empty_string_returns_422(monkeypatch) -> None:
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.post(
        "/recognition/retention/policy/preset",
        json={"preset": ""},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 422

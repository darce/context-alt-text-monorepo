"""API tests for retention endpoints."""

from __future__ import annotations

import asyncio
import textwrap
import uuid
from datetime import UTC, datetime
from typing import Any, cast

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


def _export_snapshot(tenant_id: str, **overrides: Any) -> dict[str, Any]:
    """Build a snapshot with the exact top-level shape TenantExportService emits.

    rg-005 / FEBT2-LE-NEW-02: the fake must not be looser than the real
    exporter. A fake that omits collections lets a response contract be
    written against the fake instead of against production, which is how the
    admin client came to believe in wire shapes the exporter never produced
    (FEBT1-LG-01). Every key here mirrors
    ``TenantExportService.export_tenant_data``.
    """
    snapshot: dict[str, Any] = {
        "tenant_id": tenant_id,
        "retention_mode": "retain_all",
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "schema_version": EXPORT_SCHEMA_VERSION,
        "clusters": [{"id": str(uuid.uuid4())}],
        "media_identities": [],
        "identity_suggestions": [],
        "name_suggestions": [],
        "cluster_merge_suggestions": [],
        "scan_jobs": [],
    }
    snapshot.update(overrides)
    return snapshot


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
        self.data_json_override: dict[str, Any] | None = None

    async def count_exportable_identities(self, tenant_id: str) -> int:
        assert tenant_id == self.tenant_id
        return self.count

    async def export_tenant_data(self, tenant_id: str, actor: str) -> dict[str, Any]:
        """Mirror ``TenantExportService.export_tenant_data`` exactly.

        FEBT2-W2-V-02 / rg-005: this fake used to nest the collections under a
        ``data`` key and add a ``counts`` key the real exporter never emits.
        That is the phantom envelope FEBT1-LG-01 blamed the admin client for
        inventing -- the fake taught it. A fake that is looser than, or simply
        different from, the production collaborator lets a contract be written
        against the double instead of against the system.
        """
        self.calls.append((tenant_id, actor))
        return _export_snapshot(tenant_id)

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
            "data_json": self.data_json_override or _export_snapshot(tenant_id),
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


def test_retention_policy_returns_503_when_db_session_unavailable(monkeypatch) -> None:
    """Breaker-open (optional session is None) surfaces as 503 at the HTTP boundary, not 501.

    Pins the client-visible 501->503 contract change end-to-end: the REAL
    get_retention_policy_service factory runs (fake override dropped) with no DB session,
    guarding against the router's except-Exception->501 catch-all reabsorbing the 503.
    """
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)
    app = cast(FastAPI, client.app)

    # Run the real factory (not the fake) with no DB session available.
    app.dependency_overrides.pop(dependencies.get_retention_policy_service, None)

    async def _no_session():
        yield None

    app.dependency_overrides[dependencies.get_optional_session] = _no_session

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)
    response = client.get("/recognition/retention/policy", headers={"Authorization": "Bearer good-key"})

    assert response.status_code == 503


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
        import_raises="unsupported schema_version 999; maximum supported version is 3",
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


def _auth(monkeypatch, tenant_id: str) -> None:
    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id", "enterprise", False

    from recognition.interface_adapters.http.deps import auth

    monkeypatch.setattr(auth, "_lookup_api_key", _fake_lookup)


_EXPORT_CONTRACT_KEYS = (
    "tenant_id",
    "retention_mode",
    "exported_at",
    "schema_version",
    "clusters",
    "media_identities",
    "identity_suggestions",
    "name_suggestions",
    "cluster_merge_suggestions",
    "scan_jobs",
)


def _real_exporter_return_keys() -> set[str]:
    """Top-level keys of the dict literal ``TenantExportService.export_tenant_data`` returns.

    Read from the real source rather than restated, so the constant below cannot
    drift away from production without this test noticing (ARCH-13: the
    structure enforces the correspondence, not a reviewer's memory).
    """
    import ast as _ast
    import inspect as _inspect

    from recognition.application.services.export_service import TenantExportService

    tree = _ast.parse(textwrap.dedent(_inspect.getsource(TenantExportService.export_tenant_data)))
    returns = [n for n in _ast.walk(tree) if isinstance(n, _ast.Return) and isinstance(n.value, _ast.Dict)]
    if len(returns) != 1:
        raise AssertionError(
            f"expected exactly one dict-literal return in export_tenant_data, found {len(returns)}; "
            "the fake-fidelity guard can no longer read the real contract"
        )
    keys = {k.value for k in returns[0].value.keys if isinstance(k, _ast.Constant) and isinstance(k.value, str)}
    if not keys:
        raise AssertionError("export_tenant_data's return dict yielded no literal keys; refusing a vacuous pass")
    return keys


def test_export_contract_keys_match_the_real_exporter() -> None:
    """rg-005: the constant the tests pin the wire shape to is the exporter's own shape."""
    assert set(_EXPORT_CONTRACT_KEYS) == _real_exporter_return_keys()


@pytest.mark.asyncio
async def test_fake_export_service_mirrors_the_real_exporter_shape() -> None:
    """FEBT2-W2-V-02 / rg-005: a test double must not be a different contract.

    The fake used to nest collections under ``data`` and add a ``counts`` key
    the exporter never emits. Tests written against that double would certify a
    wire shape production does not produce -- which is exactly how the admin
    client came to believe in a phantom envelope (FEBT1-LG-01).
    """
    tenant_id = str(uuid.uuid4())
    payload = await FakeRetentionExportService(tenant_id).export_tenant_data(tenant_id, "api_key:test")

    assert set(payload) == _real_exporter_return_keys()
    assert "data" not in payload
    assert "counts" not in payload


def test_export_job_data_envelope_matches_the_export_contract(monkeypatch) -> None:
    """FEBT2-LE-NEW-02: the download envelope is pinned server-side.

    The route previously had no ``response_model``, so nothing on the server
    said what the download looks like and the admin client invented envelopes
    the exporter never emits (FEBT1-LG-01). The collections sit at the top
    level; there is no ``data`` wrapper.
    """
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)
    _auth(monkeypatch, tenant_id)

    response = client.get(
        "/recognition/retention/export/fake-export-job-id/data",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    body = response.json()
    for key in _EXPORT_CONTRACT_KEYS:
        assert key in body, f"export contract key {key!r} missing from the download envelope"
    assert "data" not in body
    assert isinstance(body["schema_version"], int)
    assert all(isinstance(body[key], list) for key in _EXPORT_CONTRACT_KEYS[4:])


@pytest.mark.parametrize("missing_key", _EXPORT_CONTRACT_KEYS)
def test_export_job_data_rejects_a_snapshot_that_violates_the_contract(monkeypatch, missing_key: str) -> None:
    """rg-015: an off-contract stored snapshot is an explicit fault, not a second supported shape."""
    tenant_id = str(uuid.uuid4())
    client, _, export_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)
    _auth(monkeypatch, tenant_id)

    snapshot = _export_snapshot(tenant_id)
    del snapshot[missing_key]
    export_service.data_json_override = snapshot

    response = client.get(
        "/recognition/retention/export/fake-export-job-id/data",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "stored export snapshot does not match the export contract"


def test_export_job_data_does_not_silently_drop_unknown_keys(monkeypatch) -> None:
    """A response_model that filters extras would silently truncate a download (RLSE-05)."""
    tenant_id = str(uuid.uuid4())
    client, _, export_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)
    _auth(monkeypatch, tenant_id)

    export_service.data_json_override = _export_snapshot(tenant_id, future_collection=[{"id": "x"}])

    response = client.get(
        "/recognition/retention/export/fake-export-job-id/data",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 200
    assert response.json()["future_collection"] == [{"id": "x"}]


def test_export_job_data_unclassified_failure_returns_500_not_501(monkeypatch) -> None:
    """FEBT2-LE-NEW-03: a server fault is 500. 501 tells the client the feature does not exist."""
    tenant_id = str(uuid.uuid4())
    client, _, export_service, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)
    _auth(monkeypatch, tenant_id)

    async def _boom(job_id: str, tenant_id: str) -> dict[str, Any]:
        raise RuntimeError("transient database failure")

    export_service.get_export_status = _boom

    response = client.get(
        "/recognition/retention/export/fake-export-job-id/data",
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 500
    assert response.status_code != 501
    # SEC-01: the driver text is logged server-side and must not cross the boundary.
    assert "transient database failure" not in response.text
    assert response.json()["detail"] == retention_router.INTERNAL_ERROR_DETAIL


def test_import_unclassified_failure_returns_500_not_501(monkeypatch) -> None:
    """FEBT2-LE-NEW-03: the import route's catch-all must not claim 'not implemented'."""
    tenant_id = str(uuid.uuid4())
    client, _, _, _, import_service = _build_client(monkeypatch, tenant_id=tenant_id)
    _auth(monkeypatch, tenant_id)

    async def _boom(data, tenant_id: str, actor: str) -> dict[str, Any]:  # noqa: ANN001
        raise RuntimeError("transient database failure")

    import_service.validate_and_import = _boom

    response = client.post(
        "/recognition/retention/import",
        json={"data": {"schema_version": EXPORT_SCHEMA_VERSION, "clusters": []}},
        headers={"Authorization": "Bearer good-key"},
    )

    assert response.status_code == 500
    assert response.status_code != 501
    # SEC-01: the driver text is logged server-side and must not cross the boundary.
    assert "transient database failure" not in response.text
    assert response.json()["detail"] == retention_router.INTERNAL_ERROR_DETAIL


# The single-module "no 501 in retention.py" guard and its
# ``source.count("HTTP_500_INTERNAL_SERVER_ERROR") >= 9`` companion that used to
# live here are gone. The first read one file and so certified nothing about
# ``analyze.py``, which kept a 501 catch-all through the wave that claimed to fix
# that class. The second was a lower bound on a substring count: it still passed
# if a tenth 500 was added while one of the nine that mattered was deleted, so it
# could never fail for the reason it was written. Both are replaced by the
# AST-based, directory-wide, fail-closed properties in
# ``test_router_error_boundary_contract.py`` (ARCH-13).


def test_export_job_data_publishes_its_response_model_in_openapi(monkeypatch) -> None:
    """ARCH-13: the contract must be structural, not just a runtime check in the handler.

    Validating inside the handler makes the server honest; declaring
    ``response_model`` is what publishes the shape to every client generator.
    Dropping the decorator argument would leave the route documented as an
    untyped object again -- the exact gap that let the admin client invent
    envelopes (FEBT1-LG-01) -- while all behavioural tests stayed green.
    """
    tenant_id = str(uuid.uuid4())
    client, _, _, _, _ = _build_client(monkeypatch, tenant_id=tenant_id)
    app = cast(FastAPI, client.app)

    schema = app.openapi()
    content = schema["paths"]["/recognition/retention/export/{job_id}/data"]["get"]["responses"]["200"]["content"]
    assert content["application/json"]["schema"]["$ref"].endswith("/ExportSnapshotResponse")

    properties = schema["components"]["schemas"]["ExportSnapshotResponse"]["properties"]
    for key in _EXPORT_CONTRACT_KEYS:
        assert key in properties, f"export contract key {key!r} is not published in the OpenAPI schema"

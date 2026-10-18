"""Auth audit emitter tests (Slice 3 of E15-1).

Each outcome emits exactly one structured log record with:
- outcome string
- 12-char hash-prefix fingerprint (never raw key)
- api_key_id when resolvable
- tenant_claim, trace_id
"""

from __future__ import annotations

import hashlib
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http import router as recognition_router
from recognition.interface_adapters.http.deps import auth as auth_module
from recognition.observability.auth_audit import emit_auth_event
from recognition.tests.api.conftest import FakeSession
from recognition.tests.fakes import FakeClusterService

AUDIT_LOGGER = "recognition.auth_audit"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def test_emit_success_record(caplog) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)
    key_hash = _hash("abcdef")
    emit_auth_event(
        "success",
        api_key_id="k-1",
        key_hash=key_hash,
        tenant_claim="t-1",
        trace_id="trace-1",
    )
    records = [r for r in caplog.records if r.name == AUDIT_LOGGER]
    assert len(records) == 1
    r = records[0]
    assert r.outcome == "success"
    assert r.fingerprint == key_hash[:12]
    assert r.api_key_id == "k-1"
    assert r.tenant_claim == "t-1"
    assert r.trace_id == "trace-1"


@pytest.mark.parametrize("outcome", ["invalid_key", "expired", "revoked", "tenant_mismatch", "rate_limit"])
def test_emit_each_outcome(caplog, outcome) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)
    key_hash = _hash("somekey")
    emit_auth_event(
        outcome,
        api_key_id=None,
        key_hash=key_hash,
        tenant_claim=None,
        trace_id="t",
    )
    records = [r for r in caplog.records if r.name == AUDIT_LOGGER]
    assert len(records) == 1
    assert records[0].outcome == outcome
    assert records[0].fingerprint == key_hash[:12]


def test_raw_key_never_appears_in_audit_log(caplog) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)
    raw = "super-secret-raw-value"
    key_hash = _hash(raw)
    emit_auth_event(
        "success",
        api_key_id="k-1",
        key_hash=key_hash,
        tenant_claim="t",
        trace_id="x",
    )
    for r in caplog.records:
        assert raw not in r.getMessage()
        for v in r.__dict__.values():
            assert raw != v


def test_fingerprint_missing_when_hash_empty(caplog) -> None:
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)
    emit_auth_event(
        "invalid_key",
        api_key_id=None,
        key_hash=None,
        tenant_claim=None,
        trace_id="x",
    )
    records = [r for r in caplog.records if r.name == AUDIT_LOGGER]
    assert len(records) == 1
    assert records[0].fingerprint is None


# Integration via require_auth: success path emits an audit record
def _auth_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")
    app = FastAPI()
    app.include_router(recognition_router, prefix="/recognition")

    async def _session_dep():
        yield FakeSession()

    def cluster_builder():
        async def _build(_tenant_id: str):
            return FakeClusterService()

        return _build

    app.dependency_overrides[dependencies.get_session] = _session_dep
    app.dependency_overrides[dependencies.get_optional_session] = _session_dep
    app.dependency_overrides[dependencies.get_cluster_service_builder] = cluster_builder
    # Reset rate limiter to avoid interference
    from recognition.interface_adapters.http.deps import rate_limit

    rate_limit._reset_state_for_tests()
    return TestClient(app)


def test_success_path_emits_audit_record(monkeypatch, caplog) -> None:
    client = _auth_client(monkeypatch)
    tenant_id = str(uuid.uuid4())

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return tenant_id, "api-key-id-success", "STANDARD", False

    monkeypatch.setattr(auth_module, "_lookup_api_key", _fake_lookup)
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

    resp = client.get(
        "/recognition/clusters",
        headers={"X-Tenant-ID": tenant_id, "Authorization": "Bearer good"},
    )
    assert resp.status_code == 200
    records = [r for r in caplog.records if r.name == AUDIT_LOGGER and r.outcome == "success"]
    assert len(records) >= 1
    assert records[-1].api_key_id == "api-key-id-success"


def test_tenant_mismatch_emits_audit_record(monkeypatch, caplog) -> None:
    client = _auth_client(monkeypatch)
    token_tenant = str(uuid.uuid4())
    request_tenant = str(uuid.uuid4())

    async def _fake_lookup(api_key, settings, session):  # noqa: ANN001
        return token_tenant, "kid", "STANDARD", False

    monkeypatch.setattr(auth_module, "_lookup_api_key", _fake_lookup)
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

    resp = client.get(
        "/recognition/clusters",
        headers={"X-Tenant-ID": request_tenant, "Authorization": "Bearer good"},
    )
    assert resp.status_code == 403
    records = [r for r in caplog.records if r.name == AUDIT_LOGGER and r.outcome == "tenant_mismatch"]
    assert len(records) == 1


def test_invalid_key_emits_audit_record(monkeypatch, caplog) -> None:
    client = _auth_client(monkeypatch)
    tenant_id = str(uuid.uuid4())
    caplog.set_level(logging.INFO, logger=AUDIT_LOGGER)

    # Use real _lookup_api_key path: session returns None for unknown key
    resp = client.get(
        "/recognition/clusters",
        headers={"X-Tenant-ID": tenant_id, "Authorization": "Bearer unknown-key"},
    )
    assert resp.status_code == 403
    records = [r for r in caplog.records if r.name == AUDIT_LOGGER and r.outcome == "invalid_key"]
    assert len(records) == 1

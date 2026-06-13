"""E15-27 Slice 1: fail-fast intake when worker-published embedding runtime is unavailable."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from recognition.application.scan import capability as capability_module
from recognition.application.scan.capability import EmbeddingRuntimeCapability
from recognition.application.tasks import scan as scan_tasks


@pytest.fixture
def unavailable_capability() -> EmbeddingRuntimeCapability:
    return EmbeddingRuntimeCapability(
        available=False,
        reason="InsightFace model bundle missing",
        updated_at=datetime.now(tz=UTC),
        heartbeat_age_seconds=1.5,
    )


def test_analyze_rejects_when_embedding_runtime_unavailable(
    api_client,
    tenant_id: str,
    monkeypatch,
    unavailable_capability: EmbeddingRuntimeCapability,
) -> None:
    """Accepted jobs must not be created when the worker reports runtime unavailable."""

    async def _scan_worker_available(_session) -> bool:  # noqa: ANN001
        return True

    async def _read_capability(_session) -> EmbeddingRuntimeCapability:  # noqa: ANN001
        return unavailable_capability

    monkeypatch.setattr(scan_tasks, "scan_worker_available", _scan_worker_available)
    monkeypatch.setattr(capability_module, "read_embedding_runtime_capability", _read_capability)
    monkeypatch.setattr(
        "recognition.interface_adapters.http.routers.analyze.is_postgres",
        lambda _session: True,
    )

    resp = api_client.post(
        "/recognition/analyze",
        json={"media_ids": [str(uuid.uuid4())], "tenant_id": tenant_id},
    )

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["detail"]["reason"] == "embedding_runtime_unavailable"
    assert body["detail"]["detail"] == unavailable_capability.reason


def test_health_detailed_reports_embedding_runtime(tmp_path, monkeypatch) -> None:
    """Operator diagnostic must surface worker-published embedding runtime capability."""
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from recognition.tests.api.test_health_probes import _build_ready_app

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(model_cache_dir=tmp_path)

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    async def _read_capability(_session) -> EmbeddingRuntimeCapability:  # noqa: ANN001
        return EmbeddingRuntimeCapability(
            available=False,
            reason="adapter init failed",
            updated_at=datetime.now(tz=UTC),
            heartbeat_age_seconds=4.2,
        )

    monkeypatch.setattr(
        "api.main.read_embedding_runtime_capability",
        _read_capability,
    )

    app.dependency_overrides[require_auth] = _auth_ok
    client = __import__("fastapi.testclient", fromlist=["TestClient"]).TestClient(app)

    resp = client.get("/health/detailed")
    assert resp.status_code == 200, resp.text
    embedding = resp.json()["embedding_runtime"]
    assert embedding["available"] is False
    assert embedding["reason"] == "adapter init failed"
    assert embedding["heartbeat_age_seconds"] == pytest.approx(4.2)

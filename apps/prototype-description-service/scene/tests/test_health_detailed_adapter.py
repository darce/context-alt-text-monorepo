"""GPUFLOW-2 A1: /health/detailed description_adapter readiness (CARD-09)."""

from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft7Validator

from scene.config.profiles import DescriptionProfile, get_profile_spec

GPU_ENDPOINT = "http://gpu.oraclevcn.com:8000"
GPU_HOST = "gpu.oraclevcn.com"
SCHEMA_PATH = (
    Path(__file__).resolve().parents[4] / "packages/shared-contracts/schemas/scene-health-detailed.schema.json"
)
ADAPTER_KEYS = {
    "profile",
    "kind",
    "endpoint_configured",
    "endpoint_allowlisted",
    "endpoint_private",
    "checked_at",
    "fresh",
    "usable",
    "reason",
}


def _schema_document() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _adapter_validator() -> Draft7Validator:
    document = _schema_document()
    return Draft7Validator(document["definitions"]["descriptionAdapterReadiness"])


def _build_client(tmp_path: Path) -> TestClient:
    from api.main import register_health_probes
    from recognition.interface_adapters.http import deps as dependencies
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from recognition.interface_adapters.http.deps.circuit_breaker import (
        SessionDependencyCircuitBreaker,
        initialize_session_dependency_circuit_breaker,
    )

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir(exist_ok=True)
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = FastAPI()
    breaker = SessionDependencyCircuitBreaker(failure_threshold=3, window_seconds=30, half_open_after_seconds=10)
    initialize_session_dependency_circuit_breaker(app, breaker=breaker)
    register_health_probes(app, model_cache_dir=tmp_path)

    async def _session_yielder():
        from db.settings import get_database_settings

        dim = int(get_database_settings().pgvector_dimension)
        rows = [
            ("media_identities", "embedding", dim),
            ("identity_cluster_representatives", "embedding", dim),
            ("mv_identity_cluster_centroids", "centroid", dim),
        ]
        result = MagicMock()
        result.all = MagicMock(return_value=rows)
        result.fetchall = MagicMock(return_value=rows)
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)
        yield session

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder
    app.dependency_overrides[require_auth] = _auth_ok
    return TestClient(app)


def _get_adapter(client: TestClient) -> dict[str, Any]:
    resp = client.get("/health/detailed")
    assert resp.status_code == 200, resp.text
    adapter = resp.json()["description_adapter"]
    assert set(adapter) == ADAPTER_KEYS
    _adapter_validator().validate(adapter)
    return adapter


@pytest.fixture(autouse=True)
def _reset_privacy_cache() -> None:
    from api import main as main_module

    main_module._endpoint_privacy_cache = main_module.EndpointPrivacyCache()
    yield
    main_module._endpoint_privacy_cache = main_module.EndpointPrivacyCache()


def test_schema_example_validates() -> None:
    document = _schema_document()
    Draft7Validator.check_schema(document)
    Draft7Validator(document).validate(document["examples"][0])
    adapter = document["examples"][0]["description_adapter"]
    assert set(adapter) == ADAPTER_KEYS
    gpu_spec = get_profile_spec(DescriptionProfile(adapter["profile"]))
    assert gpu_spec.model_id == "Qwen3-VL-30B-A3B-Instruct"
    assert gpu_spec.model_version == "Q4_K_M"


def test_unset_endpoint_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert adapter["endpoint_configured"] is False
    assert adapter["endpoint_allowlisted"] is False
    assert adapter["endpoint_private"] is None
    assert adapter["checked_at"] is None
    assert adapter["fresh"] is False
    assert adapter["usable"] is False
    assert adapter["reason"] == "endpoint_unconfigured"


def test_non_private_endpoint_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_module

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    monkeypatch.setattr(main_module, "_resolved_addresses_are_private", lambda host: False)
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert adapter["endpoint_configured"] is True
    assert adapter["endpoint_allowlisted"] is True
    assert adapter["endpoint_private"] is False
    assert adapter["fresh"] is True
    assert adapter["usable"] is False
    assert adapter["reason"] == "endpoint_not_private"
    assert isinstance(adapter["checked_at"], float)


def test_allowlisted_fresh_endpoint_is_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_module

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    monkeypatch.setattr(main_module, "_resolved_addresses_are_private", lambda host: True)
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert spec.model_id == "Qwen3-VL-30B-A3B-Instruct"
    assert spec.model_version == "Q4_K_M"
    assert adapter["kind"] == "gpu"
    assert adapter["endpoint_configured"] is True
    assert adapter["endpoint_allowlisted"] is True
    assert adapter["endpoint_private"] is True
    assert adapter["fresh"] is True
    assert adapter["usable"] is True
    assert adapter["reason"] is None
    assert isinstance(adapter["checked_at"], float)


def test_allowlisted_stale_cache_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_module

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)

    def _forbid(host: str) -> bool:
        raise AssertionError(f"stale cache must not re-resolve {host}")

    monkeypatch.setattr(main_module, "_resolved_addresses_are_private", _forbid)
    now = time.time()
    main_module._endpoint_privacy_cache.seed(
        host=GPU_HOST,
        value=True,
        checked_at=now - (main_module.EndpointPrivacyCache.TTL_SECONDS + 1),
        last_attempt_at=now,
    )
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["endpoint_configured"] is True
    assert adapter["endpoint_allowlisted"] is True
    assert adapter["endpoint_private"] is True
    assert adapter["fresh"] is False
    assert adapter["usable"] is False
    assert adapter["reason"] == "endpoint_resolution_pending"


def test_cpu_profile_has_no_gpu_endpoint_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert spec.model_id == "microsoft/Florence-2-base-ft"
    assert spec.model_version == "florence-2-base-ft"
    assert adapter["endpoint_configured"] is False
    assert adapter["usable"] is True
    assert adapter["reason"] is None
    assert adapter["fresh"] is False
    assert adapter["endpoint_private"] is None


def test_stalled_resolver_stays_bounded_and_unusable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_module

    calls: list[str] = []

    def _stalled(host: str) -> bool:
        calls.append(host)
        time.sleep(5)
        return True

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    monkeypatch.setattr(main_module, "_resolved_addresses_are_private", _stalled)
    client = _build_client(tmp_path)

    started = time.perf_counter()
    adapter = _get_adapter(client)
    elapsed = time.perf_counter() - started
    assert elapsed < 1, f"/health/detailed stalled-resolver bound exceeded: {elapsed:.3f}s"
    assert adapter["usable"] is False
    assert adapter["reason"] == "endpoint_resolution_pending"
    assert adapter["endpoint_private"] is None
    assert adapter["fresh"] is False
    assert calls == [GPU_HOST]

    started_repeat = time.perf_counter()
    repeated = _get_adapter(client)
    repeat_elapsed = time.perf_counter() - started_repeat
    assert repeat_elapsed < 1, f"repeated stalled resolve exceeded bound: {repeat_elapsed:.3f}s"
    assert repeated["usable"] is False
    assert repeated["reason"] == "endpoint_resolution_pending"
    assert calls == [GPU_HOST]


def test_privacy_cache_single_flight_on_concurrent_stalled_resolutions(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import EndpointPrivacyCache

    calls: list[str] = []

    def _stalled(host: str) -> bool:
        calls.append(host)
        time.sleep(5)
        return True

    monkeypatch.setattr("api.main._resolved_addresses_are_private", _stalled)
    cache = EndpointPrivacyCache()

    async def _run() -> None:
        started = time.perf_counter()
        first, second = await asyncio.gather(cache.refresh(GPU_HOST), cache.refresh(GPU_HOST))
        elapsed = time.perf_counter() - started
        assert elapsed < 1, f"concurrent stalled resolve exceeded bound: {elapsed:.3f}s"
        assert first == (None, None)
        assert second == (None, None)
        assert calls == [GPU_HOST]

        started_repeat = time.perf_counter()
        third = await cache.refresh(GPU_HOST)
        repeat_elapsed = time.perf_counter() - started_repeat
        assert repeat_elapsed < 1
        assert third == (None, None)
        assert calls == [GPU_HOST]

    asyncio.run(_run())


def test_gaierror_leaves_last_value_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import EndpointPrivacyCache

    def _raise_gaierror(host: str) -> bool:
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

    monkeypatch.setattr("api.main._resolved_addresses_are_private", _raise_gaierror)
    cache = EndpointPrivacyCache()
    checked_at = time.time() - 5
    cache.seed(host=GPU_HOST, value=True, checked_at=checked_at, last_attempt_at=None)

    async def _run() -> None:
        value, cached_at = await cache.refresh(GPU_HOST)
        assert value is True
        assert cached_at == checked_at

    asyncio.run(_run())

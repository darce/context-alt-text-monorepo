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

from scene.config.profiles import PROFILE_SPECS, DescriptionProfile, get_profile_spec

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
    "model_id",
    "model_version",
}
_UNAVAILABLE_PROFILES = tuple(profile for profile, spec in PROFILE_SPECS.items() if not spec.available)
_PRIVATE_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]
_PUBLIC_ADDRINFO = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]


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


def _patch_getaddrinfo(monkeypatch: pytest.MonkeyPatch, impl: Any) -> None:
    monkeypatch.setattr("api.main.socket.getaddrinfo", impl)


def test_invalid_description_adapter_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import create_app

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "not-a-description-profile")
    with pytest.raises(ValueError, match=r"ACX_DESCRIPTION_ADAPTER.*seeded.*florence_small"):
        create_app()


@pytest.fixture(autouse=True)
def _reset_privacy_cache() -> None:
    from api import main as main_module

    main_module._endpoint_privacy_cache = main_module.EndpointPrivacyCache()
    yield
    main_module._endpoint_privacy_cache = main_module.EndpointPrivacyCache()


def test_schema_example_validates() -> None:
    from api.main import wire_model_id

    document = _schema_document()
    Draft7Validator.check_schema(document)
    Draft7Validator(document).validate(document["examples"][0])
    adapter = document["examples"][0]["description_adapter"]
    assert set(adapter) == ADAPTER_KEYS
    gpu_spec = get_profile_spec(DescriptionProfile(adapter["profile"]))
    assert adapter["model_id"] == wire_model_id(gpu_spec)
    assert adapter["model_version"] == gpu_spec.model_version


def test_unset_endpoint_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import AdapterReadinessReason, wire_model_id

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
    assert adapter["reason"] == AdapterReadinessReason.ENDPOINT_UNCONFIGURED.value
    assert adapter["model_id"] == wire_model_id(spec)
    assert adapter["model_version"] == spec.model_version


def test_non_private_endpoint_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import AdapterReadinessReason, wire_model_id

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    _patch_getaddrinfo(monkeypatch, lambda *args, **kwargs: _PUBLIC_ADDRINFO)
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert adapter["endpoint_configured"] is True
    assert adapter["endpoint_allowlisted"] is True
    assert adapter["endpoint_private"] is False
    assert adapter["fresh"] is True
    assert adapter["usable"] is False
    assert adapter["reason"] == AdapterReadinessReason.ENDPOINT_NOT_PRIVATE.value
    assert isinstance(adapter["checked_at"], float)
    assert adapter["model_id"] == wire_model_id(spec)
    assert adapter["model_version"] == spec.model_version


def test_allowlisted_fresh_endpoint_is_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import wire_model_id
    from scene.infrastructure.vlm.gpu_remote_adapter import GpuRemoteDescriptionAdapter

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    _patch_getaddrinfo(monkeypatch, lambda *args, **kwargs: _PRIVATE_ADDRINFO)
    spec = get_profile_spec(DescriptionProfile.GPU_QWEN30B)
    gpu_adapter = GpuRemoteDescriptionAdapter(
        endpoint_url="http://127.0.0.1:9",
        model_id=spec.model_id or "unavailable",
        model_version=spec.model_version,
        model_revision=spec.model_revision,
        hub_repo=spec.hub_repo,
    )
    assert wire_model_id(spec) == gpu_adapter.model_id
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert adapter["endpoint_configured"] is True
    assert adapter["endpoint_allowlisted"] is True
    assert adapter["endpoint_private"] is True
    assert adapter["fresh"] is True
    assert adapter["usable"] is True
    assert adapter["reason"] is None
    assert isinstance(adapter["checked_at"], float)
    assert adapter["model_id"] == gpu_adapter.model_id
    assert adapter["model_version"] == spec.model_version


def test_allowlisted_stale_cache_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api import main as main_module
    from api.main import AdapterReadinessReason

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)

    def _forbid(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError(f"stale cache must not re-resolve {args!r}")

    _patch_getaddrinfo(monkeypatch, _forbid)
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
    assert adapter["reason"] == AdapterReadinessReason.ENDPOINT_RESOLUTION_PENDING.value


def test_cpu_profile_has_no_gpu_endpoint_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import wire_model_id

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    monkeypatch.setattr("api.main.scene_http_deps._missing_vlm_dependencies", lambda: ())
    spec = get_profile_spec(DescriptionProfile.FLORENCE_SMALL)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert adapter["model_id"] == wire_model_id(spec)
    assert adapter["model_id"] == spec.model_id
    assert adapter["model_version"] == spec.model_version
    assert adapter["endpoint_configured"] is False
    assert adapter["usable"] is True
    assert adapter["reason"] is None
    assert adapter["fresh"] is False
    assert adapter["endpoint_private"] is None


@pytest.mark.parametrize("profile", _UNAVAILABLE_PROFILES, ids=lambda profile: profile.value)
def test_unavailable_profile_is_not_usable(
    profile: DescriptionProfile, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.main import AdapterReadinessReason, wire_model_id

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", profile.value)
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    spec = get_profile_spec(profile)
    adapter = _get_adapter(_build_client(tmp_path))
    assert spec.available is False
    assert adapter["profile"] == spec.profile.value
    assert adapter["kind"] == spec.adapter_kind.value
    assert adapter["usable"] is False
    assert adapter["reason"] == AdapterReadinessReason.PROFILE_UNAVAILABLE.value
    assert adapter["model_id"] == wire_model_id(spec)
    assert adapter["model_version"] == (None if adapter["model_id"] is None else spec.model_version)


@pytest.mark.parametrize(
    "endpoint_url",
    ["gpu.oraclevcn.com", "ftp://10.0.0.5", "http://[", "http://gpu.oraclevcn.com:bad"],
)
def test_invalid_gpu_endpoint_url_skips_dns(
    endpoint_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from api.main import AdapterReadinessReason

    def _forbid(*args: object, **kwargs: object) -> list[object]:
        raise AssertionError("resolver must not be called for an invalid GPU endpoint URL")

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", endpoint_url)
    _patch_getaddrinfo(monkeypatch, _forbid)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["endpoint_configured"] is True
    assert adapter["usable"] is False
    assert adapter["reason"] == AdapterReadinessReason.ENDPOINT_INVALID_URL.value
    assert adapter["fresh"] is False


def test_gaierror_is_resolution_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import AdapterReadinessReason

    def _raise_gaierror(*args: object, **kwargs: object) -> list[object]:
        raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    _patch_getaddrinfo(monkeypatch, _raise_gaierror)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["endpoint_configured"] is True
    assert adapter["endpoint_allowlisted"] is True
    assert adapter["endpoint_private"] is None
    assert adapter["fresh"] is False
    assert adapter["usable"] is False
    assert adapter["reason"] == AdapterReadinessReason.ENDPOINT_RESOLUTION_PENDING.value


def test_health_detailed_does_not_read_secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_provider() -> None:
        raise RuntimeError("health path must not construct DescriptionSettings or read secrets")

    monkeypatch.setattr("shared.secrets.get_secret_provider", _raise_provider)
    monkeypatch.setattr("scene.config.settings.get_secret_provider", _raise_provider)
    monkeypatch.setattr("api.main.scene_http_deps._missing_vlm_dependencies", lambda: ())
    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["usable"] is True
    assert adapter["reason"] is None


def test_stalled_resolver_stays_bounded_and_unusable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import AdapterReadinessReason

    calls: list[str] = []

    def _stalled(host: str, *args: object, **kwargs: object) -> list[object]:
        calls.append(host)
        time.sleep(5)
        return _PRIVATE_ADDRINFO

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "gpu_qwen30b")
    monkeypatch.setenv("ACX_GPU_ENDPOINT_URL", GPU_ENDPOINT)
    _patch_getaddrinfo(monkeypatch, _stalled)
    client = _build_client(tmp_path)

    started = time.perf_counter()
    adapter = _get_adapter(client)
    elapsed = time.perf_counter() - started
    assert elapsed < 1, f"/health/detailed stalled-resolver bound exceeded: {elapsed:.3f}s"
    assert adapter["usable"] is False
    assert adapter["reason"] == AdapterReadinessReason.ENDPOINT_RESOLUTION_PENDING.value
    assert adapter["endpoint_private"] is None
    assert adapter["fresh"] is False
    assert calls == [GPU_HOST]

    started_repeat = time.perf_counter()
    repeated = _get_adapter(client)
    repeat_elapsed = time.perf_counter() - started_repeat
    assert repeat_elapsed < 1, f"repeated stalled resolve exceeded bound: {repeat_elapsed:.3f}s"
    assert repeated["usable"] is False
    assert repeated["reason"] == AdapterReadinessReason.ENDPOINT_RESOLUTION_PENDING.value
    assert calls == [GPU_HOST]


def test_privacy_cache_single_flight_on_concurrent_stalled_resolutions(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import EndpointPrivacyCache

    calls: list[str] = []

    def _stalled(host: str, *args: object, **kwargs: object) -> list[object]:
        calls.append(host)
        time.sleep(5)
        return _PRIVATE_ADDRINFO

    _patch_getaddrinfo(monkeypatch, _stalled)
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


def test_seeded_profile_model_identity_matches_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import wire_model_id
    from scene.application.seeded_adapter import SeededDescriptionAdapter

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "seeded")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("ACX_DESCRIPTION_MODEL_VERSION", "health-seeded-v2")
    seeded_adapter = SeededDescriptionAdapter(model_version="health-seeded-v2")
    spec = get_profile_spec(DescriptionProfile.SEEDED)
    adapter = _get_adapter(_build_client(tmp_path))
    assert spec.model_id is None
    assert wire_model_id(spec) == seeded_adapter.model_id
    assert adapter["model_id"] == seeded_adapter.model_id
    assert adapter["model_version"] == seeded_adapter.model_version
    assert adapter["usable"] is True
    assert adapter["reason"] is None


def test_local_vlm_missing_dependencies_is_not_usable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from api.main import AdapterReadinessReason

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", "florence_small")
    monkeypatch.delenv("ACX_GPU_ENDPOINT_URL", raising=False)
    monkeypatch.setattr("api.main.scene_http_deps._missing_vlm_dependencies", lambda: ("torch",))
    adapter = _get_adapter(_build_client(tmp_path))
    assert adapter["usable"] is False
    assert adapter["reason"] == AdapterReadinessReason.VLM_DEPENDENCIES_MISSING.value

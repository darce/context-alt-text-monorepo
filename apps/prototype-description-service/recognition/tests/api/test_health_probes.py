"""Health probe contracts for the recognition service.

Tests cover:
- GET /health probes the observability database pool with a bounded timeout.
- GET /health returns 503 and preserves identity when the pool is unavailable.
- GET /health keeps only the database dependency projection.
- Invalid database timeout configuration fails app creation.
- HealthStatus is a StrEnum in shared.health with OK/DEGRADED/UNHEALTHY.
- GET /ready runs DB + breaker + model-cache probes and aggregates status.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from time import perf_counter

import pytest
from fastapi.testclient import TestClient


def test_health_status_enum_exposes_canonical_members() -> None:
    """HealthStatus is the canonical enum for liveness/readiness status strings.

    Downstream code (root /health, /ready, /health/detailed, log fields) must
    import these members instead of using magic strings (sr-007).
    """
    from shared.health import HealthStatus

    assert issubclass(HealthStatus, StrEnum)
    assert HealthStatus.OK.value == "ok"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.UNHEALTHY.value == "unhealthy"


def test_root_health_is_healthy_when_observability_pool_is_available() -> None:
    """A reachable pool makes /health return 200 with one database check.

    Deploy smoke, ``verify``, ``status``, and uptime checks use this endpoint,
    so its success signal must include the same pool probe used by readiness.
    """
    from shared.health import HealthStatus

    app = _build_ready_app(db_ok=True)
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.OK.value
    assert body["database"]["status"] == HealthStatus.OK.value
    assert "timestamp" in body


def test_root_health_reports_unhealthy_when_observability_session_is_unavailable() -> None:
    """A missing observability session is a 503 database health failure."""
    from shared.health import HealthStatus

    app = _build_ready_app(db_ok=False)
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.UNHEALTHY.value
    assert body["database"]["status"] == HealthStatus.UNHEALTHY.value
    assert body["database"]["detail"] == "connection_unavailable"


def test_root_health_timeout_is_bounded(monkeypatch) -> None:
    """A slow database probe returns 503 within the configured bound."""
    from api import main as main_module
    from shared.health import HealthStatus

    monkeypatch.setenv("ACX_HEALTH_DB_TIMEOUT_SECONDS", "0.05")

    async def _slow_database_probe(_session):
        await asyncio.sleep(1)

    monkeypatch.setattr(main_module, "check_database", _slow_database_probe)
    app = _build_ready_app(db_ok=True)
    client = TestClient(app)

    started = perf_counter()
    resp = client.get("/health")
    elapsed = perf_counter() - started

    assert elapsed < 1, f"/health exceeded its bound: {elapsed:.3f}s"
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.UNHEALTHY.value
    assert body["database"]["status"] == HealthStatus.UNHEALTHY.value
    assert body["database"]["reason"] == "timeout"


def test_root_health_preserves_identity_when_database_unhealthy(monkeypatch) -> None:
    """A database outage response still identifies the deployed image."""
    monkeypatch.setenv("APP_GIT_COMMIT_SHA", "af9d6504deadbeefcafebabe1234567890abcdef")

    app = _build_ready_app(db_ok=False)
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["commit_sha"] == "af9d6504deadbeefcafebabe1234567890abcdef"
    assert isinstance(body["image_variant"], str) and body["image_variant"]


def test_root_health_excludes_non_database_dependency_projections() -> None:
    """The root probe exposes only identity plus its database check."""
    app = _build_ready_app(db_ok=True)
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    forbidden_keys = {
        "breaker_state",
        "pool_stats",
        "checks",
        "model_cache",
        "description_adapter",
    }
    assert not (forbidden_keys & body.keys()), f"/health leaked dependency fields {forbidden_keys & body.keys()}"


@pytest.mark.parametrize("raw_timeout", ["abc", "0"])
def test_create_app_rejects_invalid_health_db_timeout(monkeypatch, raw_timeout: str) -> None:
    """Malformed and non-positive health timeouts fail before serving."""
    from api.main import create_app

    monkeypatch.setenv("ACX_HEALTH_DB_TIMEOUT_SECONDS", raw_timeout)

    with pytest.raises(ValueError, match="ACX_HEALTH_DB_TIMEOUT_SECONDS"):
        create_app()


# ---------------------------------------------------------------------------
# /ready probes (Slice 2-ready): DB + breaker + model-cache
# ---------------------------------------------------------------------------


def _build_ready_app(
    *,
    db_ok: bool = True,
    breaker_open: bool = False,
    model_cache_dir=None,
):
    """Build an isolated FastAPI app with /ready and injected probe deps.

    Each probe is overridden per test so the slice exercises the aggregator
    and endpoint shape without spinning up a real DB, breaker, or InsightFace
    bundle on disk.
    """
    from unittest.mock import AsyncMock, MagicMock

    from fastapi import FastAPI

    from api.main import register_health_probes
    from recognition.interface_adapters.http import deps as dependencies
    from recognition.interface_adapters.http.deps.circuit_breaker import (
        BreakerState,
        SessionDependencyCircuitBreaker,
        initialize_session_dependency_circuit_breaker,
    )

    app = FastAPI()
    breaker = SessionDependencyCircuitBreaker(failure_threshold=3, window_seconds=30, half_open_after_seconds=10)
    if breaker_open:
        breaker.state = BreakerState.OPEN
    initialize_session_dependency_circuit_breaker(app, breaker=breaker)

    register_health_probes(app, model_cache_dir=model_cache_dir)

    async def _session_yielder():
        if db_ok:
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
        else:
            yield None

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder
    return app


@pytest.fixture(autouse=True)
def _clear_disk_headroom_settings_cache():
    """Keep cached headroom settings isolated from env-mutating probe tests."""
    from shared.disk_headroom import get_disk_headroom_settings

    get_disk_headroom_settings.cache_clear()
    yield
    get_disk_headroom_settings.cache_clear()


def _stub_disk_headroom_probe(monkeypatch, *, free_bytes: int, total_bytes: int, status, reason: str):
    from shared.disk_headroom import DiskHeadroom

    def _probe(path: str) -> DiskHeadroom:
        return DiskHeadroom(
            probe_path=path,
            free_bytes=free_bytes,
            total_bytes=total_bytes,
            status=status,
            reason=reason,
        )

    # The alias is added by the readiness implementation; allowing this
    # pre-implementation keeps the test's RED result about the missing check.
    monkeypatch.setattr("recognition.application.health.probe_disk_headroom", _probe, raising=False)


def test_ready_disk_headroom_below_threshold_is_degraded_without_503(monkeypatch, tmp_path) -> None:
    """Disk pressure degrades readiness but never removes the pod from service."""
    from shared.disk_headroom import get_disk_headroom_settings
    from shared.health import HealthStatus

    monkeypatch.setenv("ACX_PG_HEADROOM_PROBE_PATH", str(tmp_path))
    monkeypatch.setenv("ACX_PG_HEADROOM_MIN_BYTES", "100")
    get_disk_headroom_settings.cache_clear()
    _stub_disk_headroom_probe(
        monkeypatch,
        free_bytes=99,
        total_bytes=1000,
        status=HealthStatus.UNHEALTHY,
        reason="free bytes below minimum headroom (100)",
    )

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")
    app = _build_ready_app(model_cache_dir=tmp_path)

    resp = TestClient(app).get("/ready")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.DEGRADED.value
    disk = next(check for check in body["checks"] if check["name"] == "disk_headroom")
    assert disk["status"] == HealthStatus.DEGRADED.value
    assert "free bytes below minimum headroom" in disk["detail"]
    assert "free_bytes=99" in disk["detail"]
    assert "min_bytes=100" in disk["detail"]
    assert f"probe_path={tmp_path}" in disk["detail"]


def test_ready_disk_headroom_probe_error_is_degraded_without_503(monkeypatch, tmp_path) -> None:
    """A headroom probe error is diagnostic degradation, not liveness failure."""
    from shared.disk_headroom import get_disk_headroom_settings
    from shared.health import HealthStatus

    monkeypatch.setenv("ACX_PG_HEADROOM_PROBE_PATH", str(tmp_path / "missing"))
    get_disk_headroom_settings.cache_clear()
    _stub_disk_headroom_probe(
        monkeypatch,
        free_bytes=0,
        total_bytes=0,
        status=HealthStatus.UNHEALTHY,
        reason="unable to probe disk headroom: permission denied",
    )

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")
    app = _build_ready_app(model_cache_dir=tmp_path)

    resp = TestClient(app).get("/ready")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.DEGRADED.value
    disk = next(check for check in body["checks"] if check["name"] == "disk_headroom")
    assert disk["status"] == HealthStatus.DEGRADED.value
    assert "permission denied" in disk["detail"]
    assert "free_bytes=0" in disk["detail"]
    assert f"probe_path={tmp_path / 'missing'}" in disk["detail"]


def test_ready_disk_headroom_disabled_is_explicitly_ok(monkeypatch, tmp_path) -> None:
    """Unset probe path disables the optional guard without silent success."""
    from shared.disk_headroom import get_disk_headroom_settings
    from shared.health import HealthStatus

    monkeypatch.delenv("ACX_PG_HEADROOM_PROBE_PATH", raising=False)
    get_disk_headroom_settings.cache_clear()

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")
    app = _build_ready_app(model_cache_dir=tmp_path)

    resp = TestClient(app).get("/ready")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.OK.value
    disk = next(check for check in body["checks"] if check["name"] == "disk_headroom")
    assert disk["status"] == HealthStatus.OK.value
    assert disk["detail"] == "disabled: ACX_PG_HEADROOM_PROBE_PATH unset"


def test_health_detailed_includes_disk_headroom_payload(monkeypatch, tmp_path) -> None:
    """The operator payload exposes every headroom measurement and reason."""
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from shared.disk_headroom import get_disk_headroom_settings
    from shared.health import HealthStatus

    monkeypatch.setenv("ACX_PG_HEADROOM_PROBE_PATH", str(tmp_path))
    monkeypatch.setenv("ACX_PG_HEADROOM_MIN_BYTES", "100")
    get_disk_headroom_settings.cache_clear()
    _stub_disk_headroom_probe(
        monkeypatch,
        free_bytes=99,
        total_bytes=1000,
        status=HealthStatus.UNHEALTHY,
        reason="free bytes below minimum headroom (100)",
    )

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")
    app = _build_ready_app(model_cache_dir=tmp_path)

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    body = TestClient(app).get("/health/detailed").json()

    assert body["status"] == HealthStatus.DEGRADED.value
    assert body["disk_headroom"] == {
        "probe_path": str(tmp_path),
        "free_bytes": 99,
        "total_bytes": 1000,
        "min_bytes": 100,
        "status": HealthStatus.DEGRADED.value,
        "reason": "free bytes below minimum headroom (100)",
    }


def test_ready_healthy_when_all_deps_up(tmp_path) -> None:
    """/ready returns 200 with status=ok and per-dep check entries when DB,
    breaker, and model-cache bundle are all healthy.
    """
    from shared.health import HealthStatus

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(model_cache_dir=tmp_path)
    client = TestClient(app)

    resp = client.get("/ready")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.OK.value
    names = {check["name"] for check in body["checks"]}
    # FIR23-01: embedding_model readiness is fail-closed with the other deps.
    assert names == {"database", "breaker", "model_cache", "embedding_model", "disk_headroom"}
    for check in body["checks"]:
        assert check["status"] == HealthStatus.OK.value, check


def test_ready_unhealthy_when_breaker_open(tmp_path) -> None:
    """E15-2-BR-02: an OPEN breaker means DB checkout is blocked, so /ready
    must fail-closed with 503 / UNHEALTHY. Readiness succeeds only when DB
    checks pass, the breaker is closed, and the model bundle is present.
    """
    from shared.health import HealthStatus

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(breaker_open=True, model_cache_dir=tmp_path)
    client = TestClient(app)

    resp = client.get("/ready")

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.UNHEALTHY.value
    breaker_check = next(c for c in body["checks"] if c["name"] == "breaker")
    assert breaker_check["status"] == HealthStatus.UNHEALTHY.value


def test_ready_unhealthy_when_db_down(tmp_path) -> None:
    """When the observability session dep yields None (pool exhausted /
    connection_unavailable), /ready must report UNHEALTHY and return 503 so
    the load balancer pulls the pod from rotation.
    """
    from shared.health import HealthStatus

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(db_ok=False, model_cache_dir=tmp_path)
    client = TestClient(app)

    resp = client.get("/ready")

    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.UNHEALTHY.value
    db_check = next(c for c in body["checks"] if c["name"] == "database")
    assert db_check["status"] == HealthStatus.UNHEALTHY.value


# ---------------------------------------------------------------------------
# Slice 2.5b: subsystem health routers consolidated away
# ---------------------------------------------------------------------------


def test_subsystem_health_routers_are_removed() -> None:
    """PA-01 / Slice 2.5b: `/recognition/health`, `/recognition/health/pool`,
    `/roster/health`, and `/scene/health` are consolidated behind root
    `/health`, `/ready`, and `/health/detailed`. The old subsystem probes and
    their orphan schema (`api.schemas.health`) must be gone so operators have
    exactly one probe surface (no dashboards silently reading stale routes).
    """
    import importlib

    from api.main import create_app

    app = create_app()
    client = TestClient(app)

    for path in (
        "/recognition/health",
        "/recognition/health/pool",
        "/roster/health",
        "/scene/health",
    ):
        resp = client.get(path)
        assert resp.status_code == 404, f"{path} still served: {resp.status_code}"

    import pytest

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("api.schemas.health")


# ---------------------------------------------------------------------------
# /health/detailed (Slice 2.5a): auth-gated operator diagnostic
# ---------------------------------------------------------------------------


def test_health_detailed_requires_auth(monkeypatch, tmp_path) -> None:
    """PA-05 / Slice 2.5: /health/detailed is the operator-diagnostic surface
    (pool stats, breaker state, model-cache inventory). It must be auth-gated
    via the same `require_auth` dependency used by /metrics and /health/pool.
    """
    monkeypatch.setenv("RECOGNITION_AUTH_ENABLED", "1")

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(model_cache_dir=tmp_path)
    client = TestClient(app)

    resp = client.get("/health/detailed")
    assert resp.status_code == 401, resp.text


def test_health_detailed_returns_diagnostic_payload(tmp_path) -> None:
    """With auth satisfied, /health/detailed returns the full operator payload:
    pool stats from both engines, breaker state string, model-cache inventory.
    """
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from shared.health import HealthStatus

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")
    (bundle / "w600k_r50.onnx").write_bytes(b"stub")

    app = _build_ready_app(model_cache_dir=tmp_path)

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    client = TestClient(app)

    resp = client.get("/health/detailed")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["status"] in {s.value for s in HealthStatus}
    assert "timestamp" in body

    pool_stats = body["pool_stats"]
    assert set(pool_stats) == {"business", "observability", "clustering"}

    assert body["breaker_state"] in {"closed", "open", "half_open"}

    mc = body["model_cache"]
    assert mc["model_name"] == "buffalo_l"
    assert mc["bundle_files"] == 2
    assert mc["status"] == HealthStatus.OK.value

    embedding_runtime = body["embedding_runtime"]
    assert embedding_runtime["available"] is False
    assert embedding_runtime["reason"] == "capability read failed"


@pytest.mark.parametrize("profile", ["seeded", "florence_small"])
def test_health_detailed_reports_description_adapter(profile: str, tmp_path, monkeypatch) -> None:
    """Auth-gated diagnostic must expose the active description profile.

    model_cache.profile is the face_pipeline profile. The demo describe gate
    needs the caption producer — DescriptionSettings.profile — as a top-level
    string. Parametrize two real profiles so a hardcoded field fails.
    """
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from scene.config.settings import DescriptionSettings

    monkeypatch.setenv("ACX_DESCRIPTION_ADAPTER", profile)

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(model_cache_dir=tmp_path)

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    client = TestClient(app)

    resp = client.get("/health/detailed")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["description_adapter"] == profile
    assert body["description_adapter"] == DescriptionSettings().profile.value

    live = client.get("/health")
    assert live.status_code == 200, live.text
    assert "description_adapter" not in live.json()


def test_health_detailed_status_tracks_breaker_failure(tmp_path) -> None:
    """Regression guard for 7ed215db: /health/detailed status must aggregate
    DB + breaker + model-cache, not model-cache alone.
    """
    from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
    from shared.health import HealthStatus

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    (bundle / "det_10g.onnx").write_bytes(b"stub")

    app = _build_ready_app(breaker_open=True, model_cache_dir=tmp_path)

    async def _auth_ok() -> AuthContext:
        return AuthContext(token=None, tenant_claim=None, enabled=False)

    app.dependency_overrides[require_auth] = _auth_ok
    client = TestClient(app)

    resp = client.get("/health/detailed")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == HealthStatus.UNHEALTHY.value


# ---------------------------------------------------------------------------
# E15-3a-BR-03: /version surface + commit_sha on /health
# ---------------------------------------------------------------------------


def test_version_endpoint_returns_identity_payload(monkeypatch) -> None:
    """E15-3a-BR-03: operators must be able to observe the deployed commit SHA
    from the client, not infer it from a behavior matrix against undocumented
    auth paths. `/version` returns the canonical identity payload so the
    WordPress plugin (and prod-smoke canary) can compare against a minimum-
    supported-commit constant.
    """
    monkeypatch.setenv("APP_GIT_COMMIT_SHA", "af9d6504deadbeefcafebabe1234567890abcdef")
    monkeypatch.setenv("APP_BUILD_TIME", "2026-04-06T12:34:56Z")

    from api.main import create_app

    app = create_app()
    client = TestClient(app)

    resp = client.get("/version")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["commit_sha"] == "af9d6504deadbeefcafebabe1234567890abcdef"
    assert body["build_time"] == "2026-04-06T12:34:56Z"
    assert body["version"] == "0.1.0"


def test_version_endpoint_falls_back_to_unknown_when_env_missing(monkeypatch) -> None:
    """When APP_GIT_COMMIT_SHA is unset in production images, /version must
    still respond 200 with a sentinel value so the probe itself never 500s.
    A missing SHA is itself a signal (image built without build-arg).
    """
    monkeypatch.delenv("APP_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("APP_BUILD_TIME", raising=False)

    from api.main import create_app

    app = create_app()
    client = TestClient(app)

    resp = client.get("/version")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["version"] == "0.1.0"
    # Allow either "unknown" or a git-detected short SHA (local dev);
    # the contract is that the field is always present and a string.
    assert isinstance(body["commit_sha"], str) and body["commit_sha"]
    assert isinstance(body["build_time"], str)


def test_root_health_includes_commit_sha(monkeypatch) -> None:
    """E15-3a-BR-03: unhealthy health responses preserve commit identity."""
    monkeypatch.setenv("APP_GIT_COMMIT_SHA", "af9d6504deadbeefcafebabe1234567890abcdef")

    app = _build_ready_app(db_ok=False)
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert body["commit_sha"] == "af9d6504deadbeefcafebabe1234567890abcdef"
    assert body["database"]["status"] == "unhealthy"
    forbidden_keys = {
        "breaker_state",
        "pool_stats",
        "checks",
        "model_cache",
        "description_adapter",
    }
    assert not (forbidden_keys & body.keys())


def test_image_variant_artifact_constant_is_canonical() -> None:
    """rg-015 / TEST-15: production constant must be /app/.image-variant.

    Monkeypatching the path in other tests must not let a wrong constant pass:
    this asserts the real module-level path used in the image. Also pins
    agreement with the canonical scripts.verify_vlm_cache export (sr-007).
    """
    from pathlib import Path

    from api.main import _IMAGE_VARIANT_ARTIFACT
    from scripts.verify_vlm_cache import IMAGE_VARIANT_ARTIFACT

    assert _IMAGE_VARIANT_ARTIFACT == Path("/app/.image-variant")
    assert _IMAGE_VARIANT_ARTIFACT == IMAGE_VARIANT_ARTIFACT


def test_image_variant_labels_lockstep_with_bake_surfaces() -> None:
    """sr-007: Dockerfile bakes + entrypoint case arm use ImageVariant members.

    Five historical copies of the recognition|vlm labels drift silently when
    only one is renamed. Assert every bake surface equals an ImageVariant
    member; mutating a label off the enum must fail this gate.
    """
    import re
    from pathlib import Path

    from scripts.verify_vlm_cache import ImageVariant

    service_root = Path(__file__).resolve().parents[3]
    dockerfile = (service_root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (service_root / "scripts" / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    valid = {member.value for member in ImageVariant}

    # printf 'recognition\n' > /app/.image-variant  (and vlm)
    baked = set(
        re.findall(
            r"""printf\s+['"]([^'"\\]+)\\n['"]\s*>\s*/app/\.image-variant""",
            dockerfile,
        )
    )
    assert baked, "Dockerfile must printf bake labels into /app/.image-variant"
    assert baked <= valid, (
        f"Dockerfile bake labels {baked} must be ImageVariant members {valid}"
    )
    assert valid <= baked, (
        f"every ImageVariant member must be baked somewhere; missing {valid - baked}"
    )

    # entrypoint case recognition|vlm)
    case_m = re.search(
        r"case\s+\"\$\{BAKED_IMAGE_VARIANT\}\"\s+in\s*\n([^\n]+)\)",
        entrypoint,
    )
    assert case_m, "entrypoint must case on BAKED_IMAGE_VARIANT"
    case_labels = {part.strip() for part in case_m.group(1).split("|") if part.strip()}
    assert case_labels == valid, (
        f"entrypoint case labels {case_labels} must equal ImageVariant {valid}"
    )


def test_health_and_version_report_baked_image_variant(tmp_path, monkeypatch) -> None:
    """D8: /health and /version report image_variant from /app/.image-variant.

    ENV alone is not build-immutable (compose env_file overrides image ENV).
    The bake wins even when ACX_IMAGE_VARIANT is unset or matches; /health
    remains attributable when the database session is unavailable.
    """
    artifact = tmp_path / ".image-variant"
    artifact.write_text("vlm\n", encoding="utf-8")
    monkeypatch.setattr("api.main._IMAGE_VARIANT_ARTIFACT", artifact)
    monkeypatch.delenv("ACX_IMAGE_VARIANT", raising=False)

    from api.main import create_app

    app = create_app()
    from recognition.interface_adapters.http import deps as dependencies

    async def _no_observability_session():
        yield None

    app.dependency_overrides[dependencies.get_observability_session] = _no_observability_session
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 503, health.text
    assert health.json()["image_variant"] == "vlm"

    version = client.get("/version")
    assert version.status_code == 200, version.text
    assert version.json()["image_variant"] == "vlm"


def test_image_variant_env_mismatch_with_bake_fails_closed(tmp_path, monkeypatch) -> None:
    """D8: non-empty ACX_IMAGE_VARIANT that disagrees with the bake fails closed."""
    artifact = tmp_path / ".image-variant"
    artifact.write_text("vlm\n", encoding="utf-8")
    monkeypatch.setattr("api.main._IMAGE_VARIANT_ARTIFACT", artifact)
    monkeypatch.setenv("ACX_IMAGE_VARIANT", "recognition")

    import pytest

    from api.main import create_app

    with pytest.raises(RuntimeError, match="disagrees with baked"):
        create_app()


def test_image_variant_unreadable_bake_fails_closed(monkeypatch) -> None:
    """OSError reading the bake must fail closed — never report recognition."""
    import pytest

    class _Unreadable:
        def is_file(self) -> bool:
            return True

        def read_text(self, *args, **kwargs) -> str:
            raise OSError("permission denied")

        def __str__(self) -> str:
            return "/app/.image-variant"

        def __fspath__(self) -> str:
            return "/app/.image-variant"

    monkeypatch.setattr("api.main._IMAGE_VARIANT_ARTIFACT", _Unreadable())
    monkeypatch.delenv("ACX_IMAGE_VARIANT", raising=False)

    from api.main import _resolve_image_variant

    with pytest.raises(RuntimeError, match="cannot read baked image variant"):
        _resolve_image_variant()


def test_image_variant_absent_bake_falls_back_to_env_then_recognition(
    tmp_path, monkeypatch
) -> None:
    """Absent artifact (local dev / unit tests): env claim, else recognition.

    Does not fabricate a VLM identity when no bake and no env claim — that is
    the only permitted fail-open path (production images always bake).
    """
    from scripts.verify_vlm_cache import ImageVariant

    missing = tmp_path / "no-such-image-variant"
    monkeypatch.setattr("api.main._IMAGE_VARIANT_ARTIFACT", missing)

    from api.main import _resolve_image_variant

    monkeypatch.setenv("ACX_IMAGE_VARIANT", ImageVariant.VLM.value)
    assert _resolve_image_variant() == ImageVariant.VLM.value

    monkeypatch.delenv("ACX_IMAGE_VARIANT", raising=False)
    assert _resolve_image_variant() == ImageVariant.RECOGNITION.value


def test_image_variant_invalid_bake_fails_closed(tmp_path, monkeypatch) -> None:
    """Corrupt bake values must fail closed (match entrypoint case arm)."""
    import pytest

    artifact = tmp_path / ".image-variant"
    artifact.write_text("torch-edition\n", encoding="utf-8")
    monkeypatch.setattr("api.main._IMAGE_VARIANT_ARTIFACT", artifact)
    monkeypatch.delenv("ACX_IMAGE_VARIANT", raising=False)

    from api.main import _resolve_image_variant

    with pytest.raises(RuntimeError, match="invalid baked image variant"):
        _resolve_image_variant()


def test_logging_file_handler_falls_back_when_dir_unwritable(tmp_path, monkeypatch) -> None:
    """Explicit stream-only fallback when log dir cannot be created (not bare pass)."""
    import logging

    from api import logging_config as lc

    blocked = tmp_path / "nope" / "logs"
    # Parent is a file → mkdir parents fails with OSError (not PermissionError-only).
    blocker = tmp_path / "nope"
    blocker.write_text("not-a-dir", encoding="utf-8")
    monkeypatch.setenv("ACX_LOG_DIR", str(blocked))
    # Temporarily pretend we are not under pytest so file handler is attempted.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(lc, "_is_test_environment", lambda: False)

    root = logging.getLogger()
    before_handlers = list(root.handlers)
    try:
        lc.configure_logging("INFO")
        # Console handler always present; file handler must be absent.
        file_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.handlers.WatchedFileHandler)
        ]
        assert file_handlers == [], (
            "unwritable log dir must not attach WatchedFileHandler"
        )
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    finally:
        root.handlers.clear()
        for h in before_handlers:
            root.addHandler(h)


def test_ready_model_cache_flips_unhealthy_when_bundle_missing(tmp_path) -> None:
    """PA-10: the model-cache check must stat the filesystem on every call
    (no caching). Unlinking the bundle between calls flips the next /ready
    response to UNHEALTHY without any process restart.
    """
    from shared.health import HealthStatus

    bundle = tmp_path / "buffalo_l"
    bundle.mkdir()
    det = bundle / "det_10g.onnx"
    det.write_bytes(b"stub")

    app = _build_ready_app(model_cache_dir=tmp_path)
    client = TestClient(app)

    first = client.get("/ready")
    assert first.status_code == 200
    assert first.json()["status"] == HealthStatus.OK.value

    # Remove the bundle mid-process — no caching should hide this.
    det.unlink()
    bundle.rmdir()

    second = client.get("/ready")
    assert second.status_code == 503, second.text
    body = second.json()
    assert body["status"] == HealthStatus.UNHEALTHY.value
    mc_check = next(c for c in body["checks"] if c["name"] == "model_cache")
    assert mc_check["status"] == HealthStatus.UNHEALTHY.value


# ---------------------------------------------------------------------------
# Lane w10d gates: compose blob parity + VLM operator-runbook contracts.
# Kept here because this file is the lane-owned test surface for compose/
# README findings that deploy-parity tests do not cover (RECOGNITION_BLOB_ROOT
# on api/worker; runnable README recipes).
# ---------------------------------------------------------------------------


def _service_root():
    from pathlib import Path

    return Path(__file__).resolve().parents[3]


def _repo_root():
    return _service_root().parents[1]


def _compose_api_worker_blob_contract(compose_text: str) -> bool:
    """api + worker must set RECOGNITION_BLOB_ROOT and mount acx_blobs.

    Mirrors the env.yml production topology so a reference prod.yml cannot
    silently fall back to /tmp/acx-recognition-blobs (R0811-H-04).
    """
    import re

    try:
        import yaml  # type: ignore
    except ImportError:  # pragma: no cover - PyYAML is a service dep
        # Fallback: structural string checks (both services + named volume).
        if compose_text.count("RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs") < 2:
            return False
        if compose_text.count("acx_blobs:/var/lib/acx-blobs") < 2:
            return False
        if not re.search(r"^\s*acx_blobs\s*:", compose_text, re.MULTILINE):
            return False
        return True

    data = yaml.safe_load(compose_text)
    services = (data or {}).get("services") or {}
    for name in ("api", "worker"):
        svc = services.get(name) or {}
        env = svc.get("environment") or []
        # environment may be list of "K=V" or a mapping
        env_blob = False
        if isinstance(env, dict):
            env_blob = env.get("RECOGNITION_BLOB_ROOT") == "/var/lib/acx-blobs"
        else:
            env_blob = any(
                isinstance(item, str) and item.strip() == "RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs"
                for item in env
            )
        if not env_blob:
            return False
        vols = svc.get("volumes") or []
        if "acx_blobs:/var/lib/acx-blobs" not in vols:
            return False
    volumes = (data or {}).get("volumes") or {}
    if "acx_blobs" not in volumes:
        return False
    return True


def test_compose_env_and_prod_api_worker_blob_root_parity() -> None:
    """R0811-H-04: env.yml + prod.yml share RECOGNITION_BLOB_ROOT + acx_blobs.

    Deploy does not select prod.yml, but parity-gating it prevents a second
    production topology with /tmp blob fallback under USER acx.
    """
    root = _service_root()
    for name in ("docker-compose.env.yml", "docker-compose.prod.yml"):
        text = (root / name).read_text(encoding="utf-8")
        assert _compose_api_worker_blob_contract(text), (
            f"{name}: api and worker must set RECOGNITION_BLOB_ROOT=/var/lib/acx-blobs "
            f"and mount acx_blobs:/var/lib/acx-blobs (named volume declared)"
        )


def test_oci_readme_vlm_cache_gate_recipe_uses_entrypoint_override() -> None:
    """rg-006 / R0811-V-05 / A-07: isolated gate recipe must not run full CMD.

    Full image CMD hits alembic first; bare docker run without DSN never
    reaches verify_vlm_cache. Recipe must use --entrypoint python … -m
    scripts.verify_vlm_cache.
    """
    readme = (_repo_root() / "infra" / "oci" / "README.md").read_text(encoding="utf-8")
    assert "--entrypoint python" in readme, (
        "infra/oci/README.md must show --entrypoint python for the isolated "
        "VLM cache-gate demonstration"
    )
    assert "-m scripts.verify_vlm_cache" in readme
    # Forbid the historical bare-run form as the *only* recipe: if the
    # isolation entrypoint disappears, this fails even if a full-stack
    # docker run remains.
    # Boot order must list alembic before the VLM gate so operators do not
    # misread migration failures as cache-gate failures.
    alembic_pos = readme.find("alembic -c db/alembic.ini upgrade head")
    gate_pos = readme.find("python -m scripts.verify_vlm_cache")
    assert alembic_pos != -1 and gate_pos != -1 and alembic_pos < gate_pos, (
        "README boot order must list alembic before verify_vlm_cache"
    )


def test_oci_readme_health_identity_uses_docker_exec() -> None:
    """R0811-V-05: host curl :8000 only works under prod admin overlay.

    Prefer docker exec … localhost:8000/health so staging/dev (expose-only)
    can still identify image_variant.
    """
    import re

    readme = (_repo_root() / "infra" / "oci" / "README.md").read_text(encoding="utf-8")
    assert "image_variant" in readme, "README health identity recipe must mention image_variant"
    # Require a docker exec that targets /health (not postgres pg_isready).
    health_exec = re.search(
        r"docker exec[^\n]*/health",
        readme,
    )
    assert health_exec is not None, (
        "README must document docker exec … /health for image_variant identity "
        "(host curl 127.0.0.1:8000 only works under prod admin overlay)"
    )


def test_oci_readme_documents_readonly_cache_and_build_immutable_variant() -> None:
    """A-09 / HARM-A-09: README must match shipped :ro mount + bake identity.

    Compose mounts ${ACX_MODELS_PATH}:/data/cache:ro; variant is baked into
    /app/.image-variant (not free-form ACX_IMAGE_VARIANT selection).
    """
    readme = (_repo_root() / "infra" / "oci" / "README.md").read_text(encoding="utf-8")
    # Primary compose contract annotation (unique; not the docker -v form).
    assert "compose: `${ACX_MODELS_PATH}:/data/cache:ro`" in readme, (
        "README must document compose: `${ACX_MODELS_PATH}:/data/cache:ro`"
    )
    # Ad-hoc docker run recipes also mount :ro (isolated gate + full-stack).
    assert "-v /data/cache:/data/cache:ro" in readme, (
        "README isolated docker run recipe must use -v /data/cache:/data/cache:ro"
    )
    assert "-v ${ACX_MODELS_PATH}:/data/cache:ro" in readme, (
        "README full-stack docker run recipe must use -v ${ACX_MODELS_PATH}:/data/cache:ro"
    )
    assert "build-immutable" in readme.lower() or "Build-immutable" in readme
    assert "/app/.image-variant" in readme
    assert "Do not set `ACX_IMAGE_VARIANT`" in readme or "Do not set ACX_IMAGE_VARIANT" in readme

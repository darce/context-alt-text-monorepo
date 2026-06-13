"""Slice 2a + 2-ready: root /health is liveness-only; /ready runs dep probes.

Tests cover:
- GET /health returns 200 with {"status": HealthStatus.OK, "timestamp": ...}.
- GET /health performs no I/O (never enters a DB session factory).
- HealthStatus is a StrEnum in shared.health with OK/DEGRADED/UNHEALTHY.
- GET /ready runs DB + breaker + model-cache probes and aggregates status.
"""

from __future__ import annotations

from enum import StrEnum

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


def test_root_health_is_liveness_only() -> None:
    """GET / health returns {status: ok, timestamp: ...} with 200 and performs
    zero I/O. PR-01: the Caddy active probe at 10s must never touch the DB,
    breaker state, or disk. Liveness answers only 'can this process respond'.
    """
    from api.main import create_app
    from shared.health import HealthStatus

    app = create_app()
    client = TestClient(app)

    resp = client.get("/health")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == HealthStatus.OK.value
    assert "timestamp" in body
    # Liveness must not include dependency projections: no DB, breaker, or cache.
    forbidden_keys = {"database", "breaker_state", "pool_stats", "checks", "model_cache"}
    assert not (forbidden_keys & body.keys()), (
        f"/health leaked dependency fields {forbidden_keys & body.keys()}; liveness must stay minimal (PR-01)."
    )


def test_root_health_does_not_open_db_session(monkeypatch) -> None:
    """The liveness handler must not call any session factory. Monkeypatch the
    observability and business factories to raise; a passing response proves
    the handler never entered them.
    """
    from api.main import create_app
    from recognition.interface_adapters.http import dependencies

    def _boom():  # pragma: no cover - should never execute
        raise AssertionError("/health must not open a DB session (liveness only)")

    app = create_app()
    app.dependency_overrides[dependencies.get_optional_session] = _boom
    app.dependency_overrides[dependencies.get_observability_session] = _boom
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200


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
    from recognition.interface_adapters.http import dependencies
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
            session = MagicMock()
            session.execute = AsyncMock(return_value=None)
            yield session
        else:
            yield None

    app.dependency_overrides[dependencies.get_observability_session] = _session_yielder
    return app


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
    assert names == {"database", "breaker", "model_cache"}
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
    """E15-3a-BR-03: the liveness probe grows a commit_sha field so operators
    diagnosing a stale deploy can read the SHA from the same endpoint Caddy
    already hits. Liveness discipline (no DB/breaker/disk) is preserved —
    commit_sha is a static identity string resolved once at import time.
    """
    monkeypatch.setenv("APP_GIT_COMMIT_SHA", "af9d6504deadbeefcafebabe1234567890abcdef")

    from api.main import create_app

    app = create_app()
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["commit_sha"] == "af9d6504deadbeefcafebabe1234567890abcdef"
    # Dep-projection keys still forbidden (PR-01 liveness contract).
    forbidden_keys = {"database", "breaker_state", "pool_stats", "checks", "model_cache"}
    assert not (forbidden_keys & body.keys())


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

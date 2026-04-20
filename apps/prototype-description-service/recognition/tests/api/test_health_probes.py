"""Slice 2a: root /health is liveness-only per PR-01.

Tests cover:
- GET /health returns 200 with {"status": HealthStatus.OK, "timestamp": ...}.
- GET /health performs no I/O (never enters a DB session factory).
- HealthStatus is a StrEnum in shared.health with OK/DEGRADED/UNHEALTHY.
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

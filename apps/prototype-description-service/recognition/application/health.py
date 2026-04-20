"""Health probe helpers for the recognition service.

Dep checks live here (not in the HTTP router) so /ready and /health/detailed
(Slice 2.5) can share a single source of truth. The helpers are plain async
functions — the HTTP layer owns wiring them to FastAPI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.interface_adapters.http.deps.circuit_breaker import (
    BreakerState,
    SessionDependencyCircuitBreaker,
)
from shared.health import HealthReport, HealthStatus


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One dependency probe's outcome as it appears in /ready response."""

    name: str
    status: HealthStatus
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


def check_health() -> HealthReport:
    """Return a static health signal for the recognition service."""
    return HealthReport.ok("recognition")


async def check_database(session: AsyncSession | None) -> CheckResult:
    """Reuse the session dependency's built-in SELECT 1 probe.

    `get_observability_session` already runs SELECT 1 before yielding a live
    session and yields None when the probe fails. A second SELECT 1 here would
    double DB load on every /ready hit (BR-03) without adding signal.
    """
    if session is None:
        return CheckResult("database", HealthStatus.UNHEALTHY, "connection_unavailable")
    return CheckResult("database", HealthStatus.OK, "reachable")


def check_breaker(breaker: SessionDependencyCircuitBreaker) -> CheckResult:
    """An OPEN breaker means DB checkout is blocked — /ready fails (BR-02).

    Readiness succeeds only when DB checks pass, the breaker is closed, and
    the model bundle is present. An OPEN breaker violates that contract, so
    the aggregate status flips UNHEALTHY and the handler returns 503 so the
    load balancer pulls the pod until the breaker resets.
    """
    if breaker.state is BreakerState.OPEN:
        return CheckResult("breaker", HealthStatus.UNHEALTHY, "open")
    return CheckResult("breaker", HealthStatus.OK, breaker.state.value)


def check_model_cache(cache_dir: Path, model_name: str = "buffalo_l") -> CheckResult:
    """Stat the InsightFace bundle on every call (PA-10: no caching).

    The bundle must be a directory containing at least one .onnx file;
    a missing directory or empty bundle flips /ready to UNHEALTHY.
    """
    bundle = cache_dir / model_name
    if not bundle.is_dir():
        return CheckResult("model_cache", HealthStatus.UNHEALTHY, f"missing: {bundle}")
    onnx_files = list(bundle.glob("*.onnx"))
    if not onnx_files:
        return CheckResult("model_cache", HealthStatus.UNHEALTHY, f"no_onnx_files: {bundle}")
    return CheckResult("model_cache", HealthStatus.OK, f"{len(onnx_files)} bundle file(s)")


def aggregate_status(checks: list[CheckResult]) -> HealthStatus:
    """Worst-case aggregation: any UNHEALTHY wins, else any DEGRADED, else OK."""
    if any(c.status is HealthStatus.UNHEALTHY for c in checks):
        return HealthStatus.UNHEALTHY
    if any(c.status is HealthStatus.DEGRADED for c in checks):
        return HealthStatus.DEGRADED
    return HealthStatus.OK

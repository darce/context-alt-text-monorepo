"""Health probe helpers for the recognition service.

Dep checks live here (not in the HTTP router) so /ready and /health/detailed
(Slice 2.5) can share a single source of truth. The helpers are plain async
functions — the HTTP layer owns wiring them to FastAPI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
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
    """Probe DB reachability via a cheap SELECT 1 on the observability pool."""
    if session is None:
        return CheckResult("database", HealthStatus.UNHEALTHY, "connection_unavailable")
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        return CheckResult("database", HealthStatus.UNHEALTHY, f"query_failed: {exc}")
    return CheckResult("database", HealthStatus.OK, "reachable")


def check_breaker(breaker: SessionDependencyCircuitBreaker) -> CheckResult:
    """A tripped breaker is a degradation, not an outage — the process is up
    and can still answer liveness; readiness degrades so operators see it.
    """
    if breaker.state is BreakerState.OPEN:
        return CheckResult("breaker", HealthStatus.DEGRADED, "open")
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

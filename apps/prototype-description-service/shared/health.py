from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class HealthStatus(StrEnum):
    """Canonical liveness/readiness status values.

    Single import surface for all health-probe responses (root /health,
    /ready, /health/detailed) and log fields (sr-007). String values are the
    wire contract consumed by Caddy probes and downstream dashboards.
    """

    OK = "ok"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Domain object describing the health of an individual service."""

    service: str
    status: HealthStatus
    timestamp: datetime

    @classmethod
    def ok(cls, service: str) -> HealthReport:
        return cls(service=service, status=HealthStatus.OK, timestamp=datetime.now(timezone.utc))  # noqa: UP017

    def to_dict(self) -> dict[str, Any]:
        """Convert the report into a serializable dictionary."""
        return asdict(self)

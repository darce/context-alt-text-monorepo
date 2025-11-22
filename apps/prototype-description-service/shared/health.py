from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Domain object describing the health of an individual service."""

    service: str
    status: str
    timestamp: datetime

    @classmethod
    def ok(cls, service: str) -> HealthReport:
        return cls(service=service, status="ok", timestamp=datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert the report into a serializable dictionary."""
        return asdict(self)

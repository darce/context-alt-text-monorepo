from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Domain object describing the health of an individual service."""

    service: str
    status: str
    timestamp: datetime

    @classmethod
    def ok(cls, service: str) -> "HealthReport":
        return cls(service=service, status="ok", timestamp=datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert the report into a serializable dictionary."""
        return asdict(self)

"""Decision types and decision log dataclass for observability.

This module defines the core types used for logging cluster assignment decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    pass


class DecisionType(Enum):
    """Outcome of an assignment gate evaluation.

    These labels appear in logs and charts to clearly communicate
    what action was taken for each identity.

    Attributes:
        ACCEPT: Identity was assigned to the cluster.
        SUGGEST: Identity was sent to human review (borderline confidence).
        REJECT: Identity was not assigned (stays in unclustered pool).
    """

    ACCEPT = "accept"
    SUGGEST = "suggest"
    REJECT = "reject"


@dataclass(frozen=True)
class DecisionLog:
    """Record of a single cluster assignment decision.

    Captures all relevant context for debugging and analysis.
    Immutable (frozen) to ensure log integrity.

    Attributes:
        timestamp: When the decision was made (UTC).
        identity_id: UUID of the media identity being evaluated.
        cluster_id: Target cluster UUID (None if rejected).
        decision: The outcome (ACCEPT, SUGGEST, or REJECT).
        similarity: Similarity score that triggered the decision.
        algorithm: Name of the discovery algorithm (HDBSCAN, ChineseWhispers, etc.).
        checks_passed: Names of validation checks that passed.
        checks_failed: Names of validation checks that failed.
        rejection_reason: Human-readable reason for SUGGEST or REJECT.

    Example:
        >>> log = DecisionLog(
        ...     timestamp=datetime.utcnow(),
        ...     identity_id=UUID("abc123..."),
        ...     cluster_id=UUID("def456..."),
        ...     decision=DecisionType.ACCEPT,
        ...     similarity=0.87,
        ...     algorithm="HDBSCAN",
        ...     checks_passed=["complete_link", "maturity"],
        ...     checks_failed=[],
        ... )
    """

    timestamp: datetime
    identity_id: UUID
    cluster_id: UUID | None
    decision: DecisionType
    similarity: float
    algorithm: str
    checks_passed: list[str] = field(default_factory=list)
    checks_failed: list[str] = field(default_factory=list)
    rejection_reason: str | None = None

    def to_log_dict(self) -> dict:
        """Convert to dictionary for structured logging.

        Returns:
            Dictionary suitable for JSON logging output.

        Example:
            >>> log.to_log_dict()
            {'timestamp': '2025-12-01T14:32:15Z', 'identity_id': 'abc123...', ...}
        """
        raise NotImplementedError("TODO: Implement to_log_dict serialization")

    def to_log_line(self) -> str:
        """Format as a single log line.

        Returns:
            Formatted string like "[HDBSCAN] ACCEPT: identity X → cluster Y (sim=0.87)"

        Example:
            >>> log.to_log_line()
            '[HDBSCAN] ACCEPT: abc123 → def456 (sim=0.87)'
        """
        raise NotImplementedError("TODO: Implement to_log_line formatting")

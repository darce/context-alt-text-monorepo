"""
Shared protocols for the orchestration layer to avoid circular dependencies and duplication.
"""

from __future__ import annotations

from typing import Protocol

from recognition.application.assignment import AssignmentCandidate
from recognition.domain.suggestion import AssignmentSuggestion, SuggestionRefreshReason


class SuggestionServiceProtocol(Protocol):
    """Protocol for creating and managing assignment suggestions."""

    async def create(self, candidate: AssignmentCandidate, confidence: float | None = None) -> None:
        """Create a suggestion record for later human review."""
        ...

    async def refresh_for_identity(
        self,
        *,
        identity_id: str,
        reason: SuggestionRefreshReason,
    ) -> list[AssignmentSuggestion]:
        """Refresh suggestions for a specific identity."""
        ...

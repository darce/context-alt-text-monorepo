"""Domain Protocol contract for the suggestion extension service."""

from __future__ import annotations

from typing import Protocol

from recognition.domain.suggestion import BulkAcceptResult, NameSuggestion


class SuggestionExtensionServiceProtocol(Protocol):
    """Domain contract for name suggestions, bulk accept, and expiry flows."""

    async def list_name_suggestions(
        self,
        tenant_id: str,
        *,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NameSuggestion]: ...

    async def accept_name_suggestion(self, tenant_id: str, suggestion_id: str) -> NameSuggestion: ...

    async def reject_name_suggestion(self, tenant_id: str, suggestion_id: str) -> NameSuggestion: ...

    async def bulk_accept(
        self,
        tenant_id: str,
        *,
        suggestion_type: str,
        min_confidence: float,
    ) -> BulkAcceptResult: ...

"""Phase 0 scaffold for suggestion-system extensions."""

from __future__ import annotations

from typing import Any


class SuggestionExtensionService:
    """Placeholder service for name suggestions, expiry, and bulk accept flows."""

    async def list_name_suggestions(
        self,
        tenant_id: str,
        *,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("Name suggestion listing is not implemented yet.")

    async def accept_name_suggestion(self, tenant_id: str, suggestion_id: str) -> dict[str, Any]:
        raise NotImplementedError("Name suggestion acceptance is not implemented yet.")

    async def reject_name_suggestion(self, tenant_id: str, suggestion_id: str) -> dict[str, Any]:
        raise NotImplementedError("Name suggestion rejection is not implemented yet.")

    async def bulk_accept(
        self,
        tenant_id: str,
        *,
        suggestion_type: str,
        min_confidence: float,
    ) -> dict[str, Any]:
        raise NotImplementedError("Bulk suggestion acceptance is not implemented yet.")

    async def expire_stale(self, tenant_id: str) -> int:
        raise NotImplementedError("Suggestion expiry is not implemented yet.")

"""Retention audit service implementation."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.infrastructure.repositories.audit_repository import AuditRepository


class AuditService:
    """Transactional audit event helper used by retention services."""

    def __init__(self, repository_factory: Callable[[AsyncSession], AuditRepository] = AuditRepository) -> None:
        self._repository_factory = repository_factory

    async def record_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        event_type: str,
        actor: str,
        scope: str,
        payload: dict[str, object],
        result_status: str = "success",
    ) -> dict[str, object]:
        repository = self._repository_factory(session)
        event = await repository.create_event(
            tenant_id=tenant_id,
            event_type=event_type,
            actor=actor,
            scope=scope,
            payload=payload,
            result_status=result_status,
        )
        return {
            "id": str(event.id),
            "tenant_id": str(event.tenant_id),
            "event_type": event.event_type,
            "actor": event.actor,
            "scope": event.scope,
            "payload": dict(event.payload or {}),
            "result_status": event.result_status,
            "created_at": event.created_at,
        }

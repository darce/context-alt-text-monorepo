"""Audit repository implementation."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditEvent
from recognition.infrastructure.repositories._helpers import coerce_uuid


class AuditRepository:
    """Tenant-scoped audit event queries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_event(
        self,
        tenant_id: str,
        event_type: str,
        actor: str,
        scope: str,
        payload: dict[str, object],
        result_status: str = "success",
    ) -> AuditEvent:
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        event = AuditEvent(
            tenant_id=tenant_uuid,
            event_type=event_type,
            actor=actor,
            scope=scope,
            payload=payload,
            result_status=result_status,
        )
        self.session.add(event)
        await self.session.flush()
        await self.session.refresh(event)
        return event

    async def list_events(
        self, tenant_id: str, limit: int, offset: int, event_type: str | None = None
    ) -> list[AuditEvent]:
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        stmt = select(AuditEvent).where(AuditEvent.tenant_id == tenant_uuid)
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        stmt = stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_events(self, tenant_id: str, event_type: str | None = None) -> int:
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant_uuid)
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

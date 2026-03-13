"""Retention policy service implementation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant
from recognition.domain.services.audit_service import AuditService
from recognition.infrastructure.repositories._helpers import coerce_uuid

ALLOWED_RETENTION_MODES = ("retain_all", "dispose_after_ack", "purge_on_demand")


class RetentionPolicyService:
    """Reads and mutates tenant retention policy."""

    def __init__(self, session: AsyncSession, audit_service: AuditService | None = None) -> None:
        self._session = session
        self._audit_service = audit_service or AuditService()

    async def get_policy(self, tenant_id: str) -> dict[str, object]:
        tenant = await self._get_tenant(tenant_id)
        return self._serialize_policy(tenant)

    async def update_policy(self, tenant_id: str, retention_mode: str, actor: str) -> dict[str, object]:
        if retention_mode not in ALLOWED_RETENTION_MODES:
            raise ValueError("invalid retention_mode")

        tenant = await self._get_tenant(tenant_id)
        previous_mode = tenant.retention_mode
        tenant.retention_mode = retention_mode
        tenant.retention_updated_at = datetime.now(tz=UTC)
        await self._session.flush()

        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="policy_updated",
            actor=actor,
            scope="tenant",
            payload={
                "retention_mode": retention_mode,
                "previous": previous_mode,
            },
            result_status="success",
        )
        await self._session.commit()
        await self._session.refresh(tenant)

        return self._serialize_policy(tenant)

    async def _get_tenant(self, tenant_id: str) -> Tenant:
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        tenant = await self._session.get(Tenant, tenant_uuid)
        if tenant is None:
            raise LookupError("tenant not found")

        return tenant

    @staticmethod
    def _serialize_policy(tenant: Tenant) -> dict[str, object]:
        return {
            "tenant_id": str(tenant.id),
            "retention_mode": tenant.retention_mode,
            "last_export_at": tenant.last_export_at,
            "last_purge_at": tenant.last_purge_at,
            "retention_updated_at": tenant.retention_updated_at,
        }

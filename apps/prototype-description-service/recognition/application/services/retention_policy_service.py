"""Retention policy service implementation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityCluster, IdentityClusterRepresentative, MediaIdentity, NameSuggestion, Tenant
from recognition.application.services.audit_service import AuditService
from recognition.infrastructure.repositories._helpers import coerce_uuid

ALLOWED_RETENTION_MODES = ("retain_all", "dispose_after_ack", "purge_on_demand")

RETENTION_PRESETS: dict[str, dict[str, str]] = {
    "gdpr": {
        "retention_mode": "dispose_after_ack",
        "description": "Automatically dispose machine-derived data after WordPress acknowledgement.",
    },
}


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

    async def apply_disposal_after_ack(
        self,
        tenant_id: str,
        snapshot_generation_id: str | None,
        actor: str,
    ) -> dict[str, object]:
        tenant = await self._get_tenant(tenant_id)
        if tenant.retention_mode != "dispose_after_ack":
            return {"retention_mode": tenant.retention_mode, "disposed_counts": self._empty_disposed_counts()}
        if snapshot_generation_id is None:
            raise ValueError("snapshot_generation_id is required when retention_mode is dispose_after_ack")
        try:
            snapshot_uuid = uuid.UUID(snapshot_generation_id)
        except ValueError as exc:
            raise ValueError("snapshot_generation_id must be a valid UUID") from exc

        disposed_at = datetime.now(tz=UTC)
        identity_rows = (
            (
                await self._session.execute(
                    select(MediaIdentity)
                    .where(MediaIdentity.tenant_id == tenant.id)
                    .where(MediaIdentity.last_exported_snapshot_id == snapshot_uuid)
                    .where(MediaIdentity.disposed_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        cluster_rows = (
            (
                await self._session.execute(
                    select(IdentityCluster)
                    .where(IdentityCluster.tenant_id == tenant.id)
                    .where(IdentityCluster.last_exported_snapshot_id == snapshot_uuid)
                    .where(IdentityCluster.disposed_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        representative_rows = (
            (
                await self._session.execute(
                    select(IdentityClusterRepresentative)
                    .where(IdentityClusterRepresentative.tenant_id == tenant.id)
                    .where(IdentityClusterRepresentative.last_exported_snapshot_id == snapshot_uuid)
                    .where(IdentityClusterRepresentative.disposed_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        name_suggestion_rows = (
            (
                await self._session.execute(
                    select(NameSuggestion)
                    .where(NameSuggestion.tenant_id == tenant.id)
                    .where(NameSuggestion.last_exported_snapshot_id == snapshot_uuid)
                    .where(NameSuggestion.disposed_at.is_(None))
                )
            )
            .scalars()
            .all()
        )

        for identity in identity_rows:
            identity.disposed_at = disposed_at
        for cluster in cluster_rows:
            cluster.disposed_at = disposed_at
        for representative in representative_rows:
            representative.disposed_at = disposed_at
        for suggestion in name_suggestion_rows:
            suggestion.disposed_at = disposed_at

        disposed_counts = {
            "media_identities": len(identity_rows),
            "identity_clusters": len(cluster_rows),
            "identity_cluster_representatives": len(representative_rows),
            "name_suggestions": len(name_suggestion_rows),
        }

        await self._session.flush()
        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="disposal_completed",
            actor=actor,
            scope="tenant",
            payload={
                "snapshot_generation_id": snapshot_generation_id,
                "disposed_at": disposed_at.isoformat(),
                "disposed_counts": disposed_counts,
            },
        )
        return {
            "retention_mode": tenant.retention_mode,
            "snapshot_generation_id": snapshot_generation_id,
            "disposed_at": disposed_at.isoformat(),
            "disposed_counts": disposed_counts,
        }

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

    async def apply_preset(self, tenant_id: str, preset_name: str, actor: str) -> dict[str, object]:
        if preset_name not in RETENTION_PRESETS:
            raise ValueError(f"invalid preset: {preset_name!r}")
        preset = RETENTION_PRESETS[preset_name]
        retention_mode = preset["retention_mode"]

        tenant = await self._get_tenant(tenant_id)
        previous_mode = tenant.retention_mode
        tenant.retention_mode = retention_mode
        tenant.retention_updated_at = datetime.now(tz=UTC)
        await self._session.flush()

        await self._audit_service.record_event(
            self._session,
            tenant_id=str(tenant.id),
            event_type="preset_applied",
            actor=actor,
            scope="tenant",
            payload={"preset": preset_name, "retention_mode": retention_mode, "previous": previous_mode},
            result_status="success",
        )
        await self._session.commit()
        await self._session.refresh(tenant)
        return {**self._serialize_policy(tenant), "preset": preset_name}

    @staticmethod
    def _empty_disposed_counts() -> dict[str, int]:
        return {
            "media_identities": 0,
            "identity_clusters": 0,
            "identity_cluster_representatives": 0,
            "name_suggestions": 0,
        }

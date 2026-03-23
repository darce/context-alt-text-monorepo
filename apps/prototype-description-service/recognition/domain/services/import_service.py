"""Tenant import service: validates and records export/import round-trips."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.domain.services.audit_service import AuditService
from recognition.domain.services.export_service import EXPORT_SCHEMA_VERSION
from recognition.infrastructure.repositories._helpers import coerce_uuid


class TenantImportService:
    """Validates an export payload and records an import audit event.

    Full data restoration (re-inserting all rows from the export) is a
    future concern. This MVP validates the schema version, checks the
    tenant context, and records a ``import_completed`` audit event so the
    import is visible in the retention audit log.
    """

    def __init__(self, session: AsyncSession, audit_service: AuditService | None = None) -> None:
        self._session = session
        self._audit_service = audit_service or AuditService()

    async def validate_and_import(
        self,
        data: dict[str, Any],
        tenant_id: str,
        actor: str,
    ) -> dict[str, Any]:
        """Validate the export payload and record an import event.

        Args:
            data: The decoded export JSON as a plain dict.
            tenant_id: The current tenant (from auth context).
            actor: Stable actor string from the authenticated request.

        Returns:
            Summary dict with tenant_id, schema_version, and item counts.

        Raises:
            ValueError: When schema_version is missing, non-integer, or
                newer than the maximum supported version.
        """
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        schema_version = data.get("schema_version")
        if not isinstance(schema_version, int):
            raise ValueError(f"invalid schema_version: {schema_version!r}; expected an integer")
        if schema_version > EXPORT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {schema_version}; maximum supported version is {EXPORT_SCHEMA_VERSION}"
            )

        counts = _extract_counts(data)

        imported_at = datetime.now(tz=UTC)

        await self._audit_service.record_event(
            self._session,
            tenant_id=tenant_id,
            event_type="import_completed",
            actor=actor,
            scope="tenant",
            payload={
                "schema_version": schema_version,
                "source_tenant_id": data.get("tenant_id"),
                "exported_at": data.get("exported_at"),
                "imported_at": imported_at.isoformat(),
                "counts": counts,
            },
        )

        await self._session.commit()

        return {
            "tenant_id": tenant_id,
            "schema_version": schema_version,
            "imported_at": imported_at.isoformat(),
            "counts": counts,
        }


def _extract_counts(data: dict[str, Any]) -> dict[str, int]:
    """Best-effort extraction of item counts from an export payload."""
    count_keys = (
        "clusters",
        "media_identities",
        "identity_suggestions",
        "name_suggestions",
        "cluster_merge_suggestions",
        "scan_jobs",
    )
    counts: dict[str, int] = {}
    for key in count_keys:
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            counts[key] = len(value)
        elif isinstance(value, int):
            counts[key] = value
    return counts

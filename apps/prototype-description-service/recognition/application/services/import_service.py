"""Tenant import service: validates and records export/import round-trips."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.audit_service import AuditService
from recognition.application.services.export_service import EXPORT_SCHEMA_VERSION
from recognition.infrastructure.repositories._helpers import coerce_uuid

#: Top-level collection keys carried by a tenant-export snapshot.
#:
#: rg-005 (schema/contract parity): mirrors the keys emitted by
#: ``TenantExportService.export_tenant_data`` and the client-side
#: ``EXPORT_COLLECTION_KEYS`` in
#: ``js/admin/api/recognition/retentionApi.ts``.
IMPORT_COLLECTION_KEYS: Final[tuple[str, ...]] = (
    "clusters",
    "media_identities",
    "identity_suggestions",
    "name_suggestions",
    "cluster_merge_suggestions",
    "scan_jobs",
)


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

        This is the trust boundary for the import path: a client-side guard
        closes the common case but cannot be relied upon, so the submitted
        snapshot is validated structurally here and rejected explicitly
        (``ValueError`` -> HTTP 422) rather than accepted with best-effort
        counts. An ``import_completed`` audit event that records success with
        understated or zeroed counts is a lie in the audit log; a rejection
        is honest.

        Args:
            data: The decoded export JSON as a plain dict.
            tenant_id: The current tenant (from auth context).
            actor: Stable actor string from the authenticated request.

        Returns:
            Summary dict with tenant_id, schema_version, and item counts.

        Raises:
            ValueError: When the payload is not a JSON object, when
                schema_version is missing, non-integer, or newer than the
                maximum supported version, when the payload carries no known
                collection, or when a present collection is not a list.
        """
        tenant_uuid = coerce_uuid(tenant_id, on_failure="none")
        if tenant_uuid is None:
            raise ValueError("invalid tenant_id")

        if not isinstance(data, dict):
            raise ValueError(f"invalid export payload: expected a JSON object, got {type(data).__name__}")

        schema_version = data.get("schema_version")
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise ValueError(f"invalid schema_version: {schema_version!r}; expected an integer")
        if schema_version > EXPORT_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {schema_version}; maximum supported version is {EXPORT_SCHEMA_VERSION}"
            )

        counts = _validate_collections(data)

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


def _validate_collections(data: dict[str, Any]) -> dict[str, int]:
    """Validate the snapshot's collections and return their real item counts.

    Every count returned is the length of an actually-present list, so the
    recorded ``import_completed`` audit event cannot understate what was
    submitted. A payload with no known collection is the envelope-instead-of-
    snapshot mistake (``{"schema_version": n, "data": {...}}``) and is
    rejected rather than imported as zero of everything.
    """
    present_keys = [key for key in IMPORT_COLLECTION_KEYS if key in data]
    if not present_keys:
        raise ValueError(
            "invalid export payload: no exported collections found; expected at least one of "
            f"{', '.join(IMPORT_COLLECTION_KEYS)} at the top level"
        )

    counts: dict[str, int] = {}
    for key in present_keys:
        value = data[key]
        if not isinstance(value, list):
            raise ValueError(f"invalid export payload: {key!r} must be a list, got {type(value).__name__}")
        counts[key] = len(value)

    return counts

"""Trust-boundary tests for TenantImportService.validate_and_import.

FEBT1-LG-02: the import trust boundary is the service, not the client. A
malformed snapshot must be rejected explicitly instead of being accepted with
best-effort counts and an audit event that understates or zeroes what was
imported (RLSE-05: silent failure is the worst failure).

FEBT2-LE-NEW-01: the service restores nothing, so the audit event it writes is
named ``import_validated``. ``import_completed`` claimed a restore that never
happened -- the same RLSE-05 failure mode read from the operator's side.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.services.audit_service import AuditService
from recognition.application.services.export_service import EXPORT_SCHEMA_VERSION
from recognition.application.services.import_service import (
    IMPORT_AUDIT_EVENT_TYPE,
    IMPORT_COLLECTION_KEYS,
    TenantImportService,
)


class _FakeSession:
    """Minimal stand-in: the service only commits through the session."""

    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _RecordingAuditService:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record_event(self, session: Any, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _build_service() -> tuple[TenantImportService, _FakeSession, _RecordingAuditService]:
    session = _FakeSession()
    audit = _RecordingAuditService()
    service = TenantImportService(
        cast(AsyncSession, session),
        cast(AuditService, audit),
    )
    return service, session, audit


def _snapshot(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "tenant_id": str(uuid4()),
        "exported_at": "2026-01-01T00:00:00+00:00",
        "clusters": [{"id": "cluster-1"}, {"id": "cluster-2"}],
        "media_identities": [{"id": "identity-1"}],
        "identity_suggestions": [],
        "name_suggestions": [],
        "cluster_merge_suggestions": [],
        "scan_jobs": [],
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_valid_snapshot_records_real_counts() -> None:
    service, session, audit = _build_service()
    tenant_id = str(uuid4())

    result = await service.validate_and_import(_snapshot(), tenant_id, "actor@test")

    assert result["counts"] == {
        "clusters": 2,
        "media_identities": 1,
        "identity_suggestions": 0,
        "name_suggestions": 0,
        "cluster_merge_suggestions": 0,
        "scan_jobs": 0,
    }
    assert result["schema_version"] == EXPORT_SCHEMA_VERSION
    assert session.commit_count == 1
    assert len(audit.events) == 1
    assert audit.events[0]["event_type"] == "import_validated"
    assert audit.events[0]["payload"]["counts"] == result["counts"]


@pytest.mark.asyncio
async def test_partial_snapshot_counts_only_present_collections() -> None:
    service, _session, audit = _build_service()

    result = await service.validate_and_import(
        {"schema_version": EXPORT_SCHEMA_VERSION, "clusters": [{"id": "c"}]},
        str(uuid4()),
        "actor@test",
    )

    assert result["counts"] == {"clusters": 1}
    assert audit.events[0]["payload"]["counts"] == {"clusters": 1}


@pytest.mark.parametrize(
    ("payload", "message_fragment"),
    [
        pytest.param(["not", "an", "object"], "expected a JSON object", id="list-payload"),
        pytest.param("not an object", "expected a JSON object", id="str-payload"),
        pytest.param({"clusters": []}, "invalid schema_version", id="missing-schema-version"),
        pytest.param({"schema_version": "3", "clusters": []}, "invalid schema_version", id="str-schema-version"),
        pytest.param({"schema_version": True, "clusters": []}, "invalid schema_version", id="bool-schema-version"),
        pytest.param(
            {"schema_version": EXPORT_SCHEMA_VERSION + 1, "clusters": []},
            "unsupported schema_version",
            id="future-schema-version",
        ),
        pytest.param(
            {"schema_version": EXPORT_SCHEMA_VERSION, "tenant_id": "t"},
            "no exported collections found",
            id="no-collections",
        ),
        pytest.param(
            {"schema_version": EXPORT_SCHEMA_VERSION, "data": {"clusters": [{"id": "c"}]}},
            "no exported collections found",
            id="envelope-instead-of-snapshot",
        ),
        pytest.param(
            {"schema_version": EXPORT_SCHEMA_VERSION, "clusters": {"id": "c"}},
            "'clusters' must be a list",
            id="collection-is-object",
        ),
        pytest.param(
            {"schema_version": EXPORT_SCHEMA_VERSION, "clusters": 5},
            "'clusters' must be a list",
            id="collection-is-int-count",
        ),
        pytest.param(
            {"schema_version": EXPORT_SCHEMA_VERSION, "clusters": [], "scan_jobs": None},
            "'scan_jobs' must be a list",
            id="collection-is-null",
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_payload_is_rejected_and_records_no_audit_event(
    payload: Any,
    message_fragment: str,
) -> None:
    service, session, audit = _build_service()

    with pytest.raises(ValueError) as excinfo:
        await service.validate_and_import(payload, str(uuid4()), "actor@test")

    assert message_fragment in str(excinfo.value)
    # RLSE-05: no success is recorded for a rejected import.
    assert audit.events == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_invalid_tenant_id_is_rejected_before_any_audit_event() -> None:
    service, session, audit = _build_service()

    with pytest.raises(ValueError, match="invalid tenant_id"):
        await service.validate_and_import(_snapshot(), "not-a-uuid", "actor@test")

    assert audit.events == []
    assert session.commit_count == 0


def test_collection_keys_match_the_export_contract() -> None:
    # rg-005: the import counter must not drift from the exporter's collections.
    assert IMPORT_COLLECTION_KEYS == (
        "clusters",
        "media_identities",
        "identity_suggestions",
        "name_suggestions",
        "cluster_merge_suggestions",
        "scan_jobs",
    )


def test_audit_event_type_does_not_claim_a_restore() -> None:
    """RLSE-05 discrimination guard: the event name must not overstate the work.

    TenantImportService writes no rows. Naming its audit event ``*_completed``
    tells an operator reading the retention audit log that their data was
    restored. This asserts the literal so a rename back to a completion verb
    turns this test red instead of quietly re-introducing the false claim.
    """
    assert IMPORT_AUDIT_EVENT_TYPE == "import_validated"
    assert "completed" not in IMPORT_AUDIT_EVENT_TYPE

"""Persistence tests for audit event storage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from db.models import AuditEvent, Tenant
from recognition.application.services.audit_service import AuditService
from recognition.infrastructure.repositories.audit_repository import AuditRepository


@pytest.mark.asyncio
async def test_audit_repository_creates_and_lists_events_newest_first(db_session, tenant: Tenant) -> None:
    repository = AuditRepository(db_session)

    older = await repository.create_event(
        tenant_id=str(tenant.id),
        event_type="policy_updated",
        actor="api_key:old",
        scope="tenant",
        payload={"retention_mode": "retain_all"},
    )
    older.created_at = datetime.now(tz=UTC) - timedelta(hours=1)
    newer = await repository.create_event(
        tenant_id=str(tenant.id),
        event_type="export_completed",
        actor="api_key:new",
        scope="tenant",
        payload={"cluster_count": 4},
    )
    newer.created_at = datetime.now(tz=UTC)
    await db_session.commit()

    events = await repository.list_events(str(tenant.id), limit=10, offset=0)

    assert [event.event_type for event in events] == ["export_completed", "policy_updated"]
    assert await repository.count_events(str(tenant.id)) == 2


@pytest.mark.asyncio
async def test_audit_repository_filters_by_tenant(db_session, tenant: Tenant) -> None:
    other_tenant = Tenant(id=uuid4(), site_url="http://other.example.test")
    db_session.add(other_tenant)
    await db_session.flush()

    repository = AuditRepository(db_session)
    await repository.create_event(
        tenant_id=str(tenant.id),
        event_type="policy_updated",
        actor="api_key:test",
        scope="tenant",
        payload={"retention_mode": "retain_all"},
    )
    await repository.create_event(
        tenant_id=str(other_tenant.id),
        event_type="policy_updated",
        actor="api_key:other",
        scope="tenant",
        payload={"retention_mode": "purge_on_demand"},
    )
    await db_session.commit()

    events = await repository.list_events(str(tenant.id), limit=10, offset=0)

    assert len(events) == 1
    assert events[0].actor == "api_key:test"


@pytest.mark.asyncio
async def test_audit_service_records_transactional_event_payload(db_session, tenant: Tenant) -> None:
    service = AuditService()

    event = await service.record_event(
        db_session,
        tenant_id=str(tenant.id),
        event_type="policy_updated",
        actor="api_key:test",
        scope="tenant",
        payload={"retention_mode": "dispose_after_ack"},
    )
    await db_session.commit()

    persisted = await db_session.get(AuditEvent, UUID(str(event["id"])))
    assert persisted is not None
    assert persisted.payload["retention_mode"] == "dispose_after_ack"
    assert event["event_type"] == "policy_updated"

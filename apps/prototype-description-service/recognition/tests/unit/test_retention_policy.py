"""Persistence tests for RetentionPolicyService."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from db.models import AuditEvent, Tenant
from recognition.config.settings import RecognitionSettings
from recognition.domain.services.retention_policy_service import RetentionPolicyService


@pytest.mark.asyncio
async def test_get_policy_returns_existing_tenant_fields(db_session, tenant: Tenant) -> None:
    tenant.retention_mode = "purge_on_demand"
    tenant.last_export_at = datetime.now(tz=UTC)
    tenant.last_purge_at = datetime.now(tz=UTC)
    tenant.retention_updated_at = datetime.now(tz=UTC)
    await db_session.commit()

    service = RetentionPolicyService(db_session)

    policy = await service.get_policy(str(tenant.id))

    assert policy["tenant_id"] == str(tenant.id)
    assert policy["retention_mode"] == "purge_on_demand"
    assert policy["last_export_at"] is not None
    assert policy["last_purge_at"] is not None
    assert policy["retention_updated_at"] is not None


@pytest.mark.asyncio
async def test_update_policy_persists_and_records_audit_event(db_session, tenant: Tenant) -> None:
    service = RetentionPolicyService(db_session)

    policy = await service.update_policy(str(tenant.id), "dispose_after_ack", "api_key:test")

    assert policy["retention_mode"] == "dispose_after_ack"
    assert policy["retention_updated_at"] is not None

    refreshed = await db_session.get(Tenant, tenant.id)
    assert refreshed is not None
    assert refreshed.retention_mode == "dispose_after_ack"

    events = (await db_session.execute(select(AuditEvent).where(AuditEvent.tenant_id == tenant.id))).scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "policy_updated"
    assert events[0].actor == "api_key:test"
    assert events[0].payload["retention_mode"] == "dispose_after_ack"
    assert events[0].payload["previous"] == "retain_all"


@pytest.mark.asyncio
async def test_update_policy_rejects_invalid_mode(db_session, tenant: Tenant) -> None:
    service = RetentionPolicyService(db_session)

    with pytest.raises(ValueError, match="invalid retention_mode"):
        await service.update_policy(str(tenant.id), "invalid-mode", "api_key:test")


def test_recognition_settings_defaults_retention_mode() -> None:
    settings = RecognitionSettings()

    assert settings.default_retention_mode == "retain_all"


def test_recognition_settings_rejects_invalid_retention_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_DEFAULT_RETENTION_MODE", "not-a-mode")

    with pytest.raises(ValidationError, match="default_retention_mode"):
        RecognitionSettings()


@pytest.mark.asyncio
async def test_get_policy_raises_for_missing_tenant(db_session) -> None:
    service = RetentionPolicyService(db_session)

    with pytest.raises(LookupError, match="tenant not found"):
        await service.get_policy(str(uuid4()))

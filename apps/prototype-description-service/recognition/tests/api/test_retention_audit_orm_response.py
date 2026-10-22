"""Retention audit responses must accept the records returned by the real repository."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from db.models.observability import AuditEvent
from recognition.interface_adapters.http import deps as dependencies
from recognition.interface_adapters.http.deps.rate_limit import enforce_rate_limit
from recognition.interface_adapters.http.routers.retention import router
from recognition.interface_adapters.http.schemas.responses import AuditEventResponse

TENANT_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
EVENT_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CREATED_AT = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


class AuditRepositoryFixture:
    def __init__(self, event: AuditEvent) -> None:
        self.event = event

    async def list_events(
        self, tenant_id: str, limit: int, offset: int, event_type: str | None = None
    ) -> list[AuditEvent]:
        assert tenant_id == str(TENANT_ID)
        assert (limit, offset, event_type) == (5, 0, None)
        return [self.event]

    async def count_events(self, tenant_id: str, event_type: str | None = None) -> int:
        assert tenant_id == str(TENANT_ID)
        assert event_type is None
        return 1


def test_audit_endpoint_serializes_actual_orm_record() -> None:
    event = AuditEvent(
        id=EVENT_ID,
        tenant_id=TENANT_ID,
        event_type="policy_updated",
        actor="api_key:fixture",
        scope="tenant",
        payload={"retention_mode": "dispose_after_ack"},
        result_status="success",
        created_at=CREATED_AT,
    )
    repository = AuditRepositoryFixture(event)
    app = FastAPI()
    app.include_router(router, prefix="/recognition")

    async def tenant_dependency() -> str:
        return str(TENANT_ID)

    async def audit_dependency() -> AuditRepositoryFixture:
        return repository

    async def request_guard_dependency() -> None:
        return None

    app.dependency_overrides[dependencies.get_authenticated_tenant_id] = tenant_dependency
    app.dependency_overrides[dependencies.get_audit_repository] = audit_dependency
    # The existing retention API suite covers authentication and throttling.
    app.dependency_overrides[dependencies.require_auth] = request_guard_dependency
    app.dependency_overrides[enforce_rate_limit] = request_guard_dependency
    with TestClient(app) as client:
        response = client.get("/recognition/retention/audit", params={"limit": 5})

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "limit": 5,
        "offset": 0,
        "items": [
            {
                "id": str(EVENT_ID),
                "event_type": "policy_updated",
                "actor": "api_key:fixture",
                "scope": "tenant",
                "payload": {"retention_mode": "dispose_after_ack"},
                "result_status": "success",
                "created_at": "2026-10-19T12:00:00Z",
            }
        ],
    }


@pytest.mark.parametrize("event_id", [str(EVENT_ID), EVENT_ID.hex.upper()])
def test_audit_response_keeps_dictionary_id_normalization(event_id: str) -> None:
    response = AuditEventResponse.model_validate(
        {"id": event_id, "event_type": "policy_updated", "actor": "fixture", "created_at": CREATED_AT}
    )

    assert response.model_dump(mode="json")["id"] == str(EVENT_ID)


@pytest.mark.parametrize("event_id", ["", "invalid id!", 123, True, None])
def test_audit_response_still_rejects_invalid_id_inputs(event_id: object) -> None:
    with pytest.raises(ValidationError):
        AuditEventResponse.model_validate(
            {"id": event_id, "event_type": "policy_updated", "actor": "fixture", "created_at": CREATED_AT}
        )

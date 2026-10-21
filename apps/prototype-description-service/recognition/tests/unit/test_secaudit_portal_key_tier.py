"""Portal callers cannot choose the server-owned API-key rate tier."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from recognition.tests.unit.test_app1_portal_router import TENANT_ID, _app, _key


@pytest.mark.parametrize("tier", ["ENTERPRISE", "STANDARD", None])
def test_create_rejects_client_rate_limit_tier(tier: str | None) -> None:
    service = AsyncMock()
    with TestClient(_app(key_service=service)) as client:
        response = client.post(
            "/portal/keys",
            json={"rate_limit_tier": tier},
            headers={"Idempotency-Key": "create-tier"},
        )

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "rate_limit_tier"] and error["type"] == "extra_forbidden"
        for error in response.json()["detail"]
    )
    service.create_key.assert_not_called()


def test_create_uses_service_default_rate_limit_tier() -> None:
    service = AsyncMock()
    service.create_key.return_value = _key(TENANT_ID)
    with TestClient(_app(key_service=service)) as client:
        response = client.post(
            "/portal/keys",
            json={"lifetime_seconds": 3600},
            headers={"Idempotency-Key": "create-default-tier"},
        )

    assert response.status_code == 200
    service.create_key.assert_awaited_once_with(
        TENANT_ID, idempotency_key="create-default-tier", lifetime_seconds=3600
    )


def test_rotate_rejects_client_rate_limit_tier() -> None:
    service = AsyncMock()
    with TestClient(_app(key_service=service)) as client:
        response = client.post(
            f"/portal/keys/{uuid4()}/rotate",
            json={"reason": "routine", "rate_limit_tier": "ENTERPRISE"},
            headers={"Idempotency-Key": "rotate-tier"},
        )

    assert response.status_code == 422
    assert any(
        error["loc"] == ["body", "rate_limit_tier"] and error["type"] == "extra_forbidden"
        for error in response.json()["detail"]
    )
    service.rotate_key.assert_not_called()

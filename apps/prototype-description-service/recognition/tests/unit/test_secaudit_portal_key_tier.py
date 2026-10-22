"""Portal callers cannot choose the server-owned API-key rate tier."""

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from recognition.tests.unit.test_app1_portal_router import TENANT_ID, _app, _key


@pytest.mark.parametrize("tier", ["ENTERPRISE", "enterprise", " Pro ", "PRO", "custom", " "])
def test_create_rejects_client_rate_limit_tier_above_default(tier: str) -> None:
    service = AsyncMock()
    with TestClient(_app(key_service=service)) as client:
        response = client.post(
            "/portal/keys",
            json={"lifetime_seconds": 3600, "rate_limit_tier": tier},
            headers={"Idempotency-Key": "create-tier"},
        )

    assert response.status_code == 422
    assert any(error["loc"] == ["body", "rate_limit_tier"] for error in response.json()["detail"])
    service.create_key.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"lifetime_seconds": 3600},
        {"lifetime_seconds": 3600, "rate_limit_tier": None},
        {"lifetime_seconds": 3600, "rate_limit_tier": " standard "},
        {"lifetime_seconds": 3600, "rate_limit_tier": "STANDARD"},
    ],
)
def test_create_never_passes_client_rate_limit_tier(body: dict[str, Any]) -> None:
    service = AsyncMock()
    service.create_key.return_value = _key(TENANT_ID)
    with TestClient(_app(key_service=service)) as client:
        response = client.post(
            "/portal/keys",
            json=body,
            headers={"Idempotency-Key": "create-default-tier"},
        )

    assert response.status_code == 200
    service.create_key.assert_awaited_once_with(TENANT_ID, idempotency_key="create-default-tier", lifetime_seconds=3600)


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

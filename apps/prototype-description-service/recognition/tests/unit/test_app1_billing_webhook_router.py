"""APP-1 signed Polar billing webhook boundary tests."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.portal_contracts import BillingSubscriptionStatus, WebhookInboxStatus
from recognition.interface_adapters.http.routers import billing_webhooks

SECRET = b"router-test-secret"
TENANT_ID = uuid4()


@dataclass
class _InboxRow:
    provider_event_id: str
    event_type: str
    payload: dict[str, object]
    status: str = WebhookInboxStatus.RECEIVED.value


@dataclass
class _Projection:
    status: BillingSubscriptionStatus
    event_position: datetime
    provider_event_id: str
    provider_subscription_id: str | None = None


class _ProviderStub:
    def __init__(self, *, replay_window_valid: bool = True) -> None:
        self.verify_calls: list[bytes] = []
        self.parse_calls: list[bytes] = []
        self._verified: set[bytes] = set()
        self.replay_window_valid = replay_window_valid

    async def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        self.verify_calls.append(raw_body)
        expected = base64.b64encode(hmac.new(SECRET, raw_body, hashlib.sha256).digest()).decode()
        verified = self.replay_window_valid and hmac.compare_digest(signature, expected)
        if verified:
            self._verified.add(raw_body)
        return verified

    async def parse_event(self, raw_body: bytes) -> Mapping[str, object]:
        self.parse_calls.append(raw_body)
        if raw_body not in self._verified:
            raise ValueError("unverified")
        return json.loads(raw_body)


class _RepositoryStub:
    def __init__(self) -> None:
        self.rows: dict[str, _InboxRow] = {}
        self.projections: dict[UUID, _Projection] = {}
        self.transitions: list[str] = []
        self.skipped: list[str] = []
        self.projection_result: bool | None = None

    async def record_webhook(
        self,
        *,
        provider: str,
        provider_event_id: str,
        event_type: str,
        signature_verified: bool,
        payload: Mapping[str, object],
    ) -> bool:
        assert provider == billing_webhooks.POLAR_PROVIDER
        assert signature_verified is True
        if provider_event_id in self.rows:
            return False
        self.rows[provider_event_id] = _InboxRow(provider_event_id, event_type, dict(payload))
        return True

    async def get_webhook(self, *, provider: str, provider_event_id: str) -> _InboxRow | None:
        assert provider == billing_webhooks.POLAR_PROVIDER
        return self.rows.get(provider_event_id)

    async def upsert_projection(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        provider_customer_id: str,
        provider_subscription_id: str | None,
        status: BillingSubscriptionStatus,
        current_period_end: datetime | None,
        past_due_since: datetime | None,
        provider_event_id: str,
        event_position: datetime | str,
    ) -> bool:
        assert provider == billing_webhooks.POLAR_PROVIDER
        assert provider_customer_id
        assert current_period_end is not None
        assert past_due_since is None
        if self.projection_result is not None:
            return self.projection_result
        position = (
            datetime.fromisoformat(event_position.replace("Z", "+00:00"))
            if isinstance(event_position, str)
            else event_position
        )
        existing = self.projections.get(tenant_id)
        if existing is not None and position <= existing.event_position:
            return False
        self.projections[tenant_id] = _Projection(status, position, provider_event_id, provider_subscription_id)
        self.transitions.append(provider_event_id)
        return True

    async def get_projection(self, tenant_id: UUID, *, provider: str) -> _Projection | None:
        assert provider == billing_webhooks.POLAR_PROVIDER
        return self.projections.get(tenant_id)

    async def list_pending_webhooks(self, *, limit: int = 100) -> list[_InboxRow]:
        pending_statuses = {WebhookInboxStatus.RECEIVED.value, WebhookInboxStatus.FAILED.value}
        return [row for row in self.rows.values() if row.status in pending_statuses][:limit]

    async def mark_webhook_processed(
        self,
        *,
        provider: str,
        provider_event_id: str,
        status: WebhookInboxStatus,
    ) -> bool:
        assert provider == billing_webhooks.POLAR_PROVIDER
        row = self.rows[provider_event_id]
        row.status = status.value
        if status is WebhookInboxStatus.DISCARDED:
            self.skipped.append(provider_event_id)
        return True


def _app(provider: _ProviderStub, repository: _RepositoryStub) -> FastAPI:
    app = FastAPI()
    app.include_router(billing_webhooks.router)
    app.dependency_overrides[billing_webhooks.get_billing_provider] = lambda: provider
    app.dependency_overrides[billing_webhooks.get_billing_repository] = lambda: repository
    return app


def _event_body(
    *,
    event_id: str = "evt-1",
    event_type: str = "subscription.active",
    timestamp: str = "2026-09-20T12:00:00Z",
    status_value: str = "active",
    data_id: str = "sub-1",
    subscription_id: str | None = "sub-1",
) -> bytes:
    data: dict[str, object] = {
        "id": data_id,
        "customer_id": "cus-1",
        "tenant_id": str(TENANT_ID),
        "status": status_value,
        "current_period_end": "2026-10-20T12:00:00Z",
    }
    if subscription_id is not None:
        data["subscription_id"] = subscription_id
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "timestamp": timestamp,
            "data": data,
        },
        separators=(",", ":"),
    ).encode()


def _signature(raw_body: bytes) -> str:
    digest = hmac.new(SECRET, raw_body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def test_valid_signature_is_checked_over_exact_raw_body() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    raw_body = _event_body()

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert response.status_code == 202
    assert provider.verify_calls == [raw_body]
    assert provider.parse_calls == [raw_body]
    assert list(repository.rows) == ["evt-1"]
    assert repository.rows["evt-1"].status == WebhookInboxStatus.RECEIVED.value
    assert asyncio.run(repository.list_pending_webhooks()) == [repository.rows["evt-1"]]


def test_reserialized_payload_with_same_values_fails_raw_signature() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    signed_body = _event_body()
    changed_body = json.dumps(json.loads(signed_body), indent=2, sort_keys=True).encode()

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=changed_body,
            headers={"webhook-signature": _signature(signed_body)},
        )

    assert response.status_code == 401
    assert provider.verify_calls == [changed_body]
    assert provider.parse_calls == []
    assert repository.rows == {}


def test_missing_signature_header_is_rejected_without_provider_verification() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()

    with TestClient(_app(provider, repository)) as client:
        response = client.post("/billing/webhooks/polar", content=_event_body())

    assert response.status_code == 401
    assert provider.verify_calls == []


def test_invalid_signature_is_rejected() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=_event_body(),
            headers={"webhook-signature": "not-valid"},
        )

    assert response.status_code == 401
    assert provider.parse_calls == []
    assert repository.rows == {}


def test_oversized_body_is_rejected_before_signature_verification() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    body = b"x" * (billing_webhooks.MAX_WEBHOOK_BODY_BYTES + 1)

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=body,
            headers={"webhook-signature": "not-checked"},
        )

    assert response.status_code == 413
    assert provider.verify_calls == []
    assert repository.rows == {}


def test_replay_window_failure_is_rejected_before_repository_write() -> None:
    provider = _ProviderStub(replay_window_valid=False)
    repository = _RepositoryStub()
    raw_body = _event_body()

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert response.status_code == 401
    assert repository.rows == {}


def test_duplicate_event_has_one_inbox_row_one_transition_and_same_ack() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    raw_body = _event_body()

    with TestClient(_app(provider, repository)) as client:
        first = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )
        second = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert first.status_code == 202
    assert second.status_code == 202
    assert len(repository.rows) == 1
    assert repository.transitions == ["evt-1"]


def test_older_provider_event_does_not_regress_projection_and_stays_pending() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    newer = _event_body(event_id="evt-new", timestamp="2026-09-20T12:00:00Z")
    older = _event_body(
        event_id="evt-old",
        event_type="subscription.canceled",
        timestamp="2026-09-20T11:00:00Z",
    )

    with TestClient(_app(provider, repository)) as client:
        first = client.post(
            "/billing/webhooks/polar",
            content=newer,
            headers={"webhook-signature": _signature(newer)},
        )
        second = client.post(
            "/billing/webhooks/polar",
            content=older,
            headers={"webhook-signature": _signature(older)},
        )

    projection = repository.projections[TENANT_ID]
    assert first.status_code == 202
    assert second.status_code == 503
    assert projection.status is BillingSubscriptionStatus.ACTIVE
    assert projection.provider_event_id == "evt-new"
    assert repository.skipped == []
    assert repository.rows["evt-old"].status == WebhookInboxStatus.RECEIVED.value


def test_unknown_event_is_stored_and_acknowledged_without_projection() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    raw_body = _event_body(event_id="evt-unknown", event_type="customer.state_changed")

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert response.status_code == 202
    assert repository.rows["evt-unknown"].status == WebhookInboxStatus.RECEIVED.value
    assert repository.transitions == []


def test_projection_that_does_not_apply_is_not_acknowledged() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    repository.projection_result = False
    raw_body = _event_body()

    with TestClient(_app(provider, repository)) as client:
        first = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )
        second = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert first.status_code == 503
    assert second.status_code == 503
    assert repository.rows["evt-1"].status == WebhookInboxStatus.RECEIVED.value


def test_refund_event_does_not_store_or_clobber_provider_subscription_id() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    repository.projections[TENANT_ID] = _Projection(
        status=BillingSubscriptionStatus.ACTIVE,
        event_position=datetime.fromisoformat("2026-09-20T12:00:00+00:00"),
        provider_event_id="evt-active",
        provider_subscription_id="sub-existing",
    )
    raw_body = _event_body(
        event_id="evt-refund",
        event_type="refund.created",
        timestamp="2026-09-20T13:00:00Z",
        data_id="rfnd_abc",
        subscription_id=None,
        status_value="refunded",
    )

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    projection = repository.projections[TENANT_ID]
    assert response.status_code == 202
    assert projection.status is BillingSubscriptionStatus.REFUND_HOLD
    assert projection.provider_subscription_id == "sub-existing"
    assert projection.provider_subscription_id != "rfnd_abc"


@pytest.mark.parametrize(
    ("provider_status", "expected_status"),
    [
        ("unpaid", BillingSubscriptionStatus.PAST_DUE),
        ("ended", BillingSubscriptionStatus.CANCELED),
        ("Active", BillingSubscriptionStatus.ACTIVE),
    ],
)
def test_subscription_updated_uses_provider_status_vocabulary(
    provider_status: str,
    expected_status: BillingSubscriptionStatus,
) -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    raw_body = _event_body(
        event_id=f"evt-{provider_status}",
        event_type="subscription.updated",
        status_value=provider_status,
    )

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert response.status_code == 202
    assert repository.projections[TENANT_ID].status is expected_status
    assert repository.rows[f"evt-{provider_status}"].status == WebhookInboxStatus.RECEIVED.value


def test_unknown_subscription_status_stays_pending_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    raw_body = _event_body(
        event_id="evt-unknown-status",
        event_type="subscription.updated",
        status_value="mystery_status",
    )
    caplog.set_level(logging.WARNING, logger=billing_webhooks.logger.name)

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert response.status_code == 202
    assert repository.rows["evt-unknown-status"].status == WebhookInboxStatus.RECEIVED.value
    assert repository.transitions == []
    assert "mystery_status" in caplog.text

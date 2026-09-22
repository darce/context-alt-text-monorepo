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
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recognition.domain.portal_contracts import BillingSubscriptionStatus, WebhookInboxStatus
from recognition.infrastructure.billing.polar_provider import PolarBillingProvider
from recognition.interface_adapters.http.routers import billing_webhooks

SECRET = b"router-test-secret"
TENANT_ID = uuid4()
WEBHOOK_NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


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
    provider_customer_id: str | None = None


class _SessionStub:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.fail_commit = False

    async def commit(self) -> None:
        self.commit_calls += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")


def _header(headers: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name)
        if value:
            return value
    return None


class _ProviderStub:
    def __init__(self, *, replay_window_valid: bool = True) -> None:
        self.verify_calls: list[bytes] = []
        self.verify_headers: list[Mapping[str, str]] = []
        self.parse_calls: list[bytes] = []
        self._verified: set[bytes] = set()
        self.replay_window_valid = replay_window_valid

    async def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        self.verify_calls.append(raw_body)
        self.verify_headers.append(headers)
        signature = _header(
            headers,
            ("webhook-signature", "x-polar-signature", "polar-signature", "x-webhook-signature"),
        )
        if not isinstance(signature, str) or not signature:
            return False
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
        self.session = _SessionStub()
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
        if status is BillingSubscriptionStatus.PAST_DUE:
            assert past_due_since is not None
        else:
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
        self.projections[tenant_id] = _Projection(
            status, position, provider_event_id, provider_subscription_id, provider_customer_id
        )
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
    app.state.webhook_clock = lambda: WEBHOOK_NOW
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
    customer_id: str = "cus-1",
) -> bytes:
    data: dict[str, object] = {
        "id": data_id,
        "customer_id": customer_id,
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


_POLAR_HMAC_SECRET = "whsec_legacy-secret!"


class _UnusedHttpClient:
    async def post(self, url: str, **kwargs: object) -> object:
        raise AssertionError("webhook verification must not call Polar HTTP")

    async def get(self, url: str, **kwargs: object) -> object:
        raise AssertionError("webhook verification must not call Polar HTTP")


def _polar_headers(raw_body: bytes, *, webhook_id: str = "msg-1", timestamp: datetime = WEBHOOK_NOW) -> dict[str, str]:
    ts = str(int(timestamp.timestamp()))
    signed_content = f"{webhook_id}.{ts}.{raw_body.decode('utf-8')}".encode()
    signature = "v1," + base64.b64encode(
        hmac.new(_POLAR_HMAC_SECRET.encode("utf-8"), signed_content, hashlib.sha256).digest()
    ).decode("ascii")
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": signature,
    }


def _polar_app(repository: _RepositoryStub) -> FastAPI:
    app = FastAPI()
    app.state.webhook_clock = lambda: WEBHOOK_NOW
    app.include_router(billing_webhooks.router)
    provider = PolarBillingProvider(
        client=_UnusedHttpClient(),
        webhook_secret=_POLAR_HMAC_SECRET,
        product_ids={"pro": "product-pro"},
        base_url="https://sandbox.example.test",
        payments_enabled=False,
        environment="sandbox",
        seller_account="org-altcontext-test",
        allowed_return_origins={"https://app.example.test"},
        clock=lambda: WEBHOOK_NOW,
    )
    app.dependency_overrides[billing_webhooks.get_billing_provider] = lambda: provider
    app.dependency_overrides[billing_webhooks.get_billing_repository] = lambda: repository
    return app


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


def test_webhook_timestamp_tolerance_uses_injected_clock() -> None:
    """Reject stale delivery auth without rejecting old domain events."""
    provider = _ProviderStub()
    repository = _RepositoryStub()
    stale_delivery = WEBHOOK_NOW - timedelta(seconds=billing_webhooks.WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS + 1)
    fresh_delivery = WEBHOOK_NOW + timedelta(seconds=billing_webhooks.WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS)
    current_event = _event_body(
        event_id="evt-stale-delivery",
        timestamp=WEBHOOK_NOW.isoformat().replace("+00:00", "Z"),
    )
    old_event = _event_body(
        event_id="evt-old-domain",
        timestamp=(WEBHOOK_NOW - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    )

    with TestClient(_app(provider, repository)) as client:
        rejected = client.post(
            "/billing/webhooks/polar",
            content=current_event,
            headers={
                "webhook-signature": _signature(current_event),
                "webhook-timestamp": str(int(stale_delivery.timestamp())),
            },
        )
        accepted = client.post(
            "/billing/webhooks/polar",
            content=old_event,
            headers={
                "webhook-signature": _signature(old_event),
                "webhook-timestamp": str(int(fresh_delivery.timestamp())),
            },
        )

    assert rejected.status_code == 400
    assert accepted.status_code == 202
    assert "evt-stale-delivery" not in repository.rows
    assert "evt-old-domain" in repository.rows


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
    assert second.status_code == 202
    assert projection.status is BillingSubscriptionStatus.ACTIVE
    assert projection.provider_event_id == "evt-new"
    assert repository.skipped == []
    assert repository.rows["evt-old"].status == WebhookInboxStatus.RECEIVED.value


def test_redelivered_superseded_event_is_acknowledged_instead_of_retried_forever() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    newer = _event_body(event_id="evt-new", timestamp="2026-09-20T12:00:00Z")
    older = _event_body(
        event_id="evt-old",
        event_type="subscription.canceled",
        timestamp="2026-09-20T11:00:00Z",
    )

    with TestClient(_app(provider, repository)) as client:
        client.post(
            "/billing/webhooks/polar",
            content=newer,
            headers={"webhook-signature": _signature(newer)},
        )
        client.post(
            "/billing/webhooks/polar",
            content=older,
            headers={"webhook-signature": _signature(older)},
        )
        redelivery = client.post(
            "/billing/webhooks/polar",
            content=older,
            headers={"webhook-signature": _signature(older)},
        )

    projection = repository.projections[TENANT_ID]
    assert redelivery.status_code == 202
    assert "Retry-After" not in redelivery.headers
    assert len(repository.rows) == 2
    assert projection.provider_event_id == "evt-new"
    assert projection.status is BillingSubscriptionStatus.ACTIVE


def test_foreign_customer_cannot_repoint_another_tenants_projection() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    bound = _event_body(event_id="evt-bound", timestamp="2026-09-20T12:00:00Z")
    foreign = _event_body(
        event_id="evt-foreign",
        event_type="subscription.canceled",
        timestamp="2026-09-20T13:00:00Z",
        customer_id="cus-attacker",
        data_id="sub-attacker",
        subscription_id="sub-attacker",
    )

    with TestClient(_app(provider, repository)) as client:
        first = client.post(
            "/billing/webhooks/polar",
            content=bound,
            headers={"webhook-signature": _signature(bound)},
        )
        second = client.post(
            "/billing/webhooks/polar",
            content=foreign,
            headers={"webhook-signature": _signature(foreign)},
        )

    projection = repository.projections[TENANT_ID]
    assert first.status_code == 202
    assert second.status_code == 503
    assert projection.provider_customer_id == "cus-1"
    assert projection.status is BillingSubscriptionStatus.ACTIVE
    assert projection.provider_event_id == "evt-bound"
    assert repository.rows["evt-foreign"].status == WebhookInboxStatus.RECEIVED.value


def test_bound_customer_still_projects_later_events() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    first_body = _event_body(event_id="evt-1", timestamp="2026-09-20T12:00:00Z")
    later = _event_body(
        event_id="evt-2",
        event_type="subscription.canceled",
        timestamp="2026-09-20T13:00:00Z",
    )

    with TestClient(_app(provider, repository)) as client:
        for raw in (first_body, later):
            response = client.post(
                "/billing/webhooks/polar",
                content=raw,
                headers={"webhook-signature": _signature(raw)},
            )
            assert response.status_code == 202

    projection = repository.projections[TENANT_ID]
    assert projection.provider_event_id == "evt-2"
    assert projection.provider_customer_id == "cus-1"


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
    assert "mystery_status" not in caplog.text
    assert "projection_skipped" in caplog.text


def test_webhook_logs_never_include_body_signature_or_authorization(caplog: pytest.LogCaptureFixture) -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    accepted_body = _event_body(
        event_id="evt-safe-log",
        event_type="subscription.updated",
        status_value="body-marker-must-not-leak",
    )
    rejected_body = _event_body(event_id="evt-rejected-log", customer_id="rejected-body-marker-must-not-leak")
    accepted_signature = _signature(accepted_body)
    rejected_signature = "rejected-signature-must-not-leak"
    authorization = "Bearer authorization-must-not-leak"
    caplog.set_level(logging.WARNING, logger=billing_webhooks.logger.name)

    with TestClient(_app(provider, repository)) as client:
        accepted = client.post(
            "/billing/webhooks/polar",
            content=accepted_body,
            headers={
                "webhook-signature": accepted_signature,
                "Authorization": authorization,
            },
        )
        rejected = client.post(
            "/billing/webhooks/polar",
            content=rejected_body,
            headers={
                "webhook-signature": rejected_signature,
                "Authorization": authorization,
            },
        )

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert accepted.status_code == 202
    assert rejected.status_code == 401
    assert accepted_body.decode() not in log_text
    assert rejected_body.decode() not in log_text
    assert accepted_signature not in log_text
    assert rejected_signature not in log_text
    assert authorization not in log_text
    assert "body-marker-must-not-leak" not in log_text
    assert "rejected-body-marker-must-not-leak" not in log_text


def test_commit_failure_is_not_acknowledged_as_accepted() -> None:
    provider = _ProviderStub()
    repository = _RepositoryStub()
    repository.session.fail_commit = True
    raw_body = _event_body(event_id="evt-commit-fails")

    with TestClient(_app(provider, repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers={"webhook-signature": _signature(raw_body)},
        )

    assert response.status_code >= 500
    assert response.status_code != 202
    assert repository.session.commit_calls == 1


def test_polar_shaped_signature_is_accepted_before_inbox_write() -> None:
    repository = _RepositoryStub()
    raw_body = _event_body()

    with TestClient(_polar_app(repository)) as client:
        response = client.post(
            "/billing/webhooks/polar",
            content=raw_body,
            headers=_polar_headers(raw_body),
        )

    assert response.status_code == 202
    assert list(repository.rows) == ["sandbox:evt-1"]


def test_polar_shaped_missing_headers_tamper_and_replay_never_reach_inbox() -> None:
    repository = _RepositoryStub()
    raw_body = _event_body()
    valid = _polar_headers(raw_body)
    tampered = {**valid, "webhook-signature": valid["webhook-signature"][:-2] + "aa"}
    missing_id = {k: v for k, v in valid.items() if k != "webhook-id"}
    stale = _polar_headers(raw_body, timestamp=WEBHOOK_NOW - timedelta(minutes=6))

    with TestClient(_polar_app(repository)) as client:
        missing = client.post("/billing/webhooks/polar", content=raw_body, headers=missing_id)
        forged = client.post("/billing/webhooks/polar", content=raw_body, headers=tampered)
        replay = client.post("/billing/webhooks/polar", content=raw_body, headers=stale)
        body_changed = client.post(
            "/billing/webhooks/polar",
            content=raw_body + b" ",
            headers=valid,
        )

    assert missing.status_code == 401
    assert forged.status_code == 401
    assert replay.status_code == 401
    assert body_changed.status_code == 401
    assert repository.rows == {}
    assert repository.transitions == []

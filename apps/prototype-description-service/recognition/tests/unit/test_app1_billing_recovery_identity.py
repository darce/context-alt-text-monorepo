"""Enumeration observation identity, privacy, and tenant isolation."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from recognition.domain.portal_contracts import (
    RECONCILIATION_MAX_REMOTE_ID_LENGTH,
    EnumerationObservation,
    EnumerationObservationReason,
    EnumerationPage,
)
from recognition.tests.unit.test_app1_billing_provider import (
    _SELLER_ACCOUNT,
    FakeHttpClient,
    FakeResponse,
    _provider,
)

_VICTIM_EMAIL = "victim@example.test"
_PERIOD_END = "2026-10-20T12:00:00Z"
_MODIFIED_AT = "2026-09-20T12:00:00Z"


def _item(
    *,
    subscription_id: str | None = "sub-ok",
    customer_id: str = "cus-ok",
    tenant_id: UUID | None = None,
    external_id: str | None = None,
    metadata_tenant_id: str | None = None,
    organization_id: str = _SELLER_ACCOUNT,
    email: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    customer: dict[str, Any] = {
        "id": customer_id,
        "organization_id": organization_id,
    }
    if external_id is not None:
        customer["external_id"] = external_id
    elif tenant_id is not None:
        customer["external_id"] = f"sandbox:{tenant_id}"
    if email is not None:
        customer["email"] = email
    payload: dict[str, Any] = {
        "customer_id": customer_id,
        "status": "active",
        "current_period_end": _PERIOD_END,
        "modified_at": _MODIFIED_AT,
        "customer": customer,
    }
    if subscription_id is not None:
        payload["id"] = subscription_id
    if metadata_tenant_id is not None:
        payload["metadata"] = {"tenant_id": metadata_tenant_id}
    if extra:
        payload.update(extra)
    return payload


async def _enumerate(items: list[object]) -> EnumerationPage:
    client = FakeHttpClient(
        FakeResponse({"url": "unused"}),
        get_response=FakeResponse(
            {
                "items": items,
                "pagination": {"total_count": len(items), "max_page": 1},
            }
        ),
    )
    return await _provider(client).enumerate_subscriptions(
        cursor=None,
        limit=50,
        request_timeout=2.0,
    )


def _assert_safe_observations(
    observations: tuple[EnumerationObservation, ...],
    *forbidden: str,
) -> None:
    blob = str(observations)
    for value in forbidden:
        assert value not in blob
    remote_ids = [observation.remote_id for observation in observations]
    assert len(set(remote_ids)) == len(remote_ids)
    for observation in observations:
        assert observation.remote_id.startswith("digest:") or "@" not in observation.remote_id
        assert len(observation.remote_id) <= RECONCILIATION_MAX_REMOTE_ID_LENGTH
        assert "@" not in observation.remote_id
        for key, value in observation.details.items():
            assert "@" not in key
            assert "@" not in value
            assert value != _SELLER_ACCOUNT
            assert "example.test" not in value


@pytest.mark.asyncio
async def test_two_missing_ids_same_customer_stay_independently_accountable() -> None:
    tenant_id = uuid4()
    missing = _item(subscription_id=None, customer_id="cus-shared", tenant_id=tenant_id)
    page = await _enumerate(
        [
            missing,
            dict(missing),
            _item(subscription_id="sub-ok", customer_id="cus-ok", tenant_id=tenant_id),
        ]
    )

    missing_ids = [
        observation.remote_id
        for observation in page.observations
        if observation.reason is EnumerationObservationReason.MISSING_REMOTE_ID
    ]
    assert len(missing_ids) == 2
    assert missing_ids[0] != missing_ids[1]
    assert all(remote_id.startswith("digest:") for remote_id in missing_ids)
    assert len(page.items) == 1
    assert page.items[0].provider_subscription_id == "sandbox:sub-ok"


@pytest.mark.asyncio
async def test_two_non_object_items_stay_independently_accountable() -> None:
    tenant_id = uuid4()
    page = await _enumerate(
        [
            "not-an-object",
            "not-an-object",
            _item(subscription_id="sub-ok", tenant_id=tenant_id),
        ]
    )

    malformed = [
        observation
        for observation in page.observations
        if observation.reason is EnumerationObservationReason.MALFORMED_ITEM
    ]
    assert len(malformed) == 2
    assert malformed[0].remote_id != malformed[1].remote_id
    assert all(observation.remote_id.startswith("digest:") for observation in malformed)
    assert all(observation.details.get("shape") == "non_object" for observation in malformed)
    assert len(page.items) == 1
    assert page.items[0].tenant_id == tenant_id


@pytest.mark.asyncio
async def test_overlong_ids_with_common_prefix_do_not_collapse() -> None:
    tenant_id = uuid4()
    prefix = "sub-" + ("a" * 60)
    first = prefix + ("x" * 65)
    second = prefix + ("y" * 65)
    assert first[:64] == second[:64]
    assert len(first) == 129
    page = await _enumerate(
        [
            _item(subscription_id=first, customer_id="cus-a", tenant_id=tenant_id),
            _item(subscription_id=second, customer_id="cus-b", tenant_id=tenant_id),
            _item(subscription_id="sub-ok", customer_id="cus-ok", tenant_id=tenant_id),
        ]
    )

    assert len(page.items) == 1
    assert page.items[0].provider_subscription_id == "sandbox:sub-ok"
    assert all(
        item.provider_subscription_id is None
        or len(item.provider_subscription_id) <= RECONCILIATION_MAX_REMOTE_ID_LENGTH
        for item in page.items
    )
    overlong = [
        observation
        for observation in page.observations
        if observation.reason is EnumerationObservationReason.MALFORMED_ITEM
    ]
    assert len(overlong) == 2
    assert overlong[0].remote_id != overlong[1].remote_id
    assert all(observation.remote_id.startswith("digest:") for observation in overlong)
    assert all(len(observation.remote_id) <= RECONCILIATION_MAX_REMOTE_ID_LENGTH for observation in overlong)
    blob = str(page.observations)
    assert first not in blob
    assert second not in blob


@pytest.mark.asyncio
async def test_unsafe_email_and_organization_payload_are_digested() -> None:
    tenant_id = uuid4()
    page = await _enumerate(
        [
            _item(
                subscription_id=_VICTIM_EMAIL,
                customer_id="cus-email-id",
                tenant_id=tenant_id,
            ),
            _item(
                subscription_id="sub-unsafe-org",
                customer_id="cus-unsafe-org",
                tenant_id=tenant_id,
                organization_id=_VICTIM_EMAIL,
            ),
            _item(subscription_id="sub-ok", customer_id="cus-ok", tenant_id=tenant_id),
        ]
    )

    assert len(page.items) == 1
    assert page.items[0].provider_subscription_id == "sandbox:sub-ok"
    assert len(page.observations) == 2
    _assert_safe_observations(page.observations, _VICTIM_EMAIL, "victim")
    assert all("@" not in str(item.provider_subscription_id) for item in page.items)
    org_mismatch = [
        observation
        for observation in page.observations
        if observation.reason is EnumerationObservationReason.SELLER_MISMATCH
    ]
    assert len(org_mismatch) == 1
    assert org_mismatch[0].details.get("field_class") == "organization_id"
    assert _VICTIM_EMAIL not in org_mismatch[0].details.values()
    unsafe_id = [
        observation
        for observation in page.observations
        if observation.reason is EnumerationObservationReason.MALFORMED_ITEM
    ]
    assert len(unsafe_id) == 1
    assert unsafe_id[0].remote_id.startswith("digest:")
    assert unsafe_id[0].details.get("field_class") == "subscription_id"


@pytest.mark.asyncio
async def test_foreign_environment_then_local_metadata_is_quarantined() -> None:
    local_tenant = uuid4()
    foreign_tenant = uuid4()
    page = await _enumerate(
        [
            _item(
                subscription_id="sub-foreign-then-local",
                customer_id="cus-foreign-local",
                external_id=f"live:{foreign_tenant}",
                metadata_tenant_id=f"sandbox:{local_tenant}",
            ),
            _item(subscription_id="sub-ok", customer_id="cus-ok", tenant_id=local_tenant),
        ]
    )

    assert [item.tenant_id for item in page.items] == [local_tenant]
    assert page.items[0].provider_subscription_id == "sandbox:sub-ok"
    reasons = [observation.reason for observation in page.observations]
    assert EnumerationObservationReason.ENVIRONMENT_MISMATCH in reasons
    assert all(item.tenant_id != foreign_tenant for item in page.items)
    assert "sub-foreign-then-local" not in {item.provider_subscription_id for item in page.items}


@pytest.mark.asyncio
async def test_conflicting_local_tenants_are_quarantined() -> None:
    first_tenant = uuid4()
    second_tenant = uuid4()
    page = await _enumerate(
        [
            _item(
                subscription_id="sub-conflict",
                customer_id="cus-conflict",
                external_id=f"sandbox:{first_tenant}",
                metadata_tenant_id=f"sandbox:{second_tenant}",
            ),
            _item(subscription_id="sub-ok", customer_id="cus-ok", tenant_id=first_tenant),
        ]
    )

    assert [item.tenant_id for item in page.items] == [first_tenant]
    assert page.items[0].provider_subscription_id == "sandbox:sub-ok"
    reasons = [observation.reason for observation in page.observations]
    assert EnumerationObservationReason.TENANT_UNPARSEABLE in reasons
    assert all(item.provider_subscription_id != "sandbox:sub-conflict" for item in page.items)


@pytest.mark.asyncio
async def test_scoped_subscription_id_stays_within_remote_id_bound() -> None:
    tenant_id = uuid4()
    overlong_id = "sub-" + ("z" * 125)
    assert len(overlong_id) == 129
    in_bound_id = "sub-" + ("w" * (RECONCILIATION_MAX_REMOTE_ID_LENGTH - len("sandbox:") - 4))
    page = await _enumerate(
        [
            _item(subscription_id=overlong_id, customer_id="cus-long", tenant_id=tenant_id),
            _item(subscription_id=in_bound_id, customer_id="cus-fit", tenant_id=tenant_id),
        ]
    )

    assert len(page.items) == 1
    assert page.items[0].provider_subscription_id == f"sandbox:{in_bound_id}"
    assert len(page.items[0].provider_subscription_id or "") <= RECONCILIATION_MAX_REMOTE_ID_LENGTH
    assert len(page.observations) == 1
    assert page.observations[0].reason is EnumerationObservationReason.MALFORMED_ITEM
    assert page.observations[0].remote_id.startswith("digest:")
    assert len(page.observations[0].remote_id) <= RECONCILIATION_MAX_REMOTE_ID_LENGTH
    assert overlong_id not in str(page.observations)
    assert page.observations[0].details.get("field_class") == "subscription_id"


@pytest.mark.asyncio
async def test_good_items_are_processed_beside_each_malformed_class() -> None:
    good_tenant = uuid4()
    other_tenant = uuid4()
    prefix = "sub-" + ("p" * 60)
    page = await _enumerate(
        [
            _item(subscription_id="sub-good-a", customer_id="cus-good-a", tenant_id=good_tenant),
            _item(subscription_id=None, customer_id="cus-shared", tenant_id=good_tenant),
            _item(subscription_id=None, customer_id="cus-shared", tenant_id=good_tenant),
            "not-an-object",
            {"also": "not-subscription"},
            _item(
                subscription_id=prefix + ("x" * 65),
                customer_id="cus-long-a",
                tenant_id=good_tenant,
            ),
            _item(
                subscription_id=_VICTIM_EMAIL,
                customer_id="cus-email-id",
                tenant_id=good_tenant,
            ),
            _item(
                subscription_id="sub-org-email",
                customer_id="cus-org-email",
                tenant_id=good_tenant,
                organization_id=_VICTIM_EMAIL,
            ),
            _item(
                subscription_id="sub-foreign",
                customer_id="cus-foreign",
                external_id=f"live:{other_tenant}",
                metadata_tenant_id=f"sandbox:{good_tenant}",
            ),
            _item(
                subscription_id="sub-conflict",
                customer_id="cus-conflict",
                external_id=f"sandbox:{good_tenant}",
                metadata_tenant_id=f"sandbox:{other_tenant}",
            ),
            _item(subscription_id="sub-good-b", customer_id="cus-good-b", tenant_id=good_tenant),
        ]
    )

    assert [item.provider_subscription_id for item in page.items] == [
        "sandbox:sub-good-a",
        "sandbox:sub-good-b",
    ]
    assert all(item.tenant_id == good_tenant for item in page.items)
    reasons = {observation.reason for observation in page.observations}
    assert EnumerationObservationReason.MISSING_REMOTE_ID in reasons
    assert EnumerationObservationReason.MALFORMED_ITEM in reasons
    assert EnumerationObservationReason.SELLER_MISMATCH in reasons
    assert EnumerationObservationReason.ENVIRONMENT_MISMATCH in reasons
    assert EnumerationObservationReason.TENANT_UNPARSEABLE in reasons
    _assert_safe_observations(page.observations, _VICTIM_EMAIL)
    assert len({observation.remote_id for observation in page.observations}) == len(page.observations)

"""Metered scene requests must carry the originator's retry key."""

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from db.models.scene import DescribeDemandLease, DescribeOperation, DescribeRun
from db.models.tenant import Tenant
from scene.interface_adapters.http.routers.describe import _usage_operation_id
from scene.tests.test_app1_usage_scene_census import (
    PNG_B,
    TENANT_ID,
    _Auth,
    _census_client,
    _FakeAdmission,
    _multipart,
)


@pytest.mark.parametrize("route", ["multipart", "async"])
@pytest.mark.parametrize(
    ("operation_id", "expected_status", "code"),
    [(None, 400, "missing_operation_id"), ("x" * 129, 422, "invalid_operation_id")],
)
def test_metered_invalid_key_rejected_before_reservation_and_persistence(
    monkeypatch, route, operation_id, expected_status, code
):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, session_factory):
        data, files = _multipart(operation_id=operation_id)
        response = client.post(f"/scene/describe/{route}", data=data, files=files)
        assert response.status_code == expected_status, response.text
        detail = response.json()["detail"]
        assert detail["code"] == code
        assert "operation_id" in detail["message"]
        assert admission.reserves == []

        async def persisted_counts():
            async with session_factory() as session:
                return [
                    await session.scalar(select(func.count()).select_from(model))
                    for model in (DescribeOperation, DescribeRun)
                ]

        assert asyncio.run(persisted_counts()) == [0, 0]


@pytest.mark.parametrize("route", ["multipart", "async"])
def test_same_key_reuses_one_reservation_and_run(monkeypatch, route):
    admission = _FakeAdmission()
    with _census_client(admission, monkeypatch) as (client, _session_factory):
        data, files = _multipart(operation_id="originator-scene-action")
        first = client.post(f"/scene/describe/{route}", data=data, files=files)
        replay = client.post(f"/scene/describe/{route}", data=data, files=files)
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    identity_field = "job_id" if route == "async" else "operation_id"
    assert first.json()[identity_field] == replay.json()[identity_field]
    assert len(admission._by_operation) == 1
    assert {call["operation_id"] for call in admission.reserves} == {"originator-scene-action"}


def test_first_caller_key_replay_and_payload_mismatch_have_one_reservation(monkeypatch):
    admission = _FakeAdmission()
    operation_id = "gate3-first-use-operation"

    async def operation_and_lease_counts(session_factory):
        async with session_factory() as session:
            operation_count = await session.scalar(select(func.count()).select_from(DescribeOperation))
            lease_count = await session.scalar(select(func.count()).select_from(DescribeDemandLease))
            return operation_count, lease_count

    with _census_client(admission, monkeypatch) as (client, session_factory):
        data, files = _multipart(operation_id=operation_id)
        first = client.post("/scene/describe/multipart", data=data, files=files)
        assert first.status_code == 200, first.text
        assert first.json()["operation_id"] == operation_id
        assert asyncio.run(operation_and_lease_counts(session_factory)) == (1, 1)
        assert len(admission.reserves) == 1
        assert len(admission._by_operation) == 1

        data, files = _multipart(operation_id=operation_id)
        replay = client.post("/scene/describe/multipart", data=data, files=files)
        assert replay.status_code == 200, replay.text
        assert replay.json()["operation_id"] == operation_id
        assert asyncio.run(operation_and_lease_counts(session_factory)) == (1, 1)
        assert len(admission.reserves) == 1
        assert len(admission._by_operation) == 1

        data, files = _multipart(operation_id=operation_id, body=PNG_B)
        mismatch = client.post("/scene/describe/multipart", data=data, files=files)
        assert mismatch.status_code == 409, mismatch.text
        assert mismatch.json()["detail"]["code"] == "operation_mismatch"
        assert mismatch.json()["detail"]["operation_id"] is None
        assert asyncio.run(operation_and_lease_counts(session_factory)) == (1, 1)
        assert len(admission.reserves) == 1
        assert len(admission._by_operation) == 1


def test_same_caller_key_is_independent_per_tenant(monkeypatch):
    admission = _FakeAdmission()
    operation_id = "gate3-tenant-scoped-operation"
    other_tenant = uuid4()

    async def add_other_tenant(session_factory):
        async with session_factory() as session:
            session.add(Tenant(id=other_tenant, site_url=f"http://{other_tenant.hex}.census.test.local"))
            await session.commit()

    async def operation_rows(session_factory):
        async with session_factory() as session:
            rows = (await session.scalars(select(DescribeOperation))).all()
            return {(row.tenant_id, row.operation_id, row.request_digest) for row in rows}

    with _census_client(admission, monkeypatch) as (client, session_factory):
        asyncio.run(add_other_tenant(session_factory))
        data, files = _multipart(operation_id=operation_id)
        first = client.post("/scene/describe/multipart", data=data, files=files)
        assert first.status_code == 200, first.text
        assert first.json()["operation_id"] == operation_id

        monkeypatch.setattr(_Auth, "tenant_claim", str(other_tenant))
        data, files = _multipart(operation_id=operation_id, tenant_id=other_tenant)
        second = client.post("/scene/describe/multipart", data=data, files=files)
        assert second.status_code == 200, second.text
        assert second.json()["operation_id"] == operation_id

        rows = asyncio.run(operation_rows(session_factory))
        assert {(tenant_id, key) for tenant_id, key, _digest in rows} == {
            (TENANT_ID, operation_id),
            (other_tenant, operation_id),
        }
        assert len(rows) == 2
        assert len(admission.reserves) == 2
        assert set(admission._by_operation) == {(TENANT_ID, operation_id), (other_tenant, operation_id)}


@pytest.mark.parametrize("key, expected_status", [(None, 400), (" ", 400), ("x" * 129, 422)])
def test_metered_helper_rejects_invalid_key_instead_of_minting(key, expected_status):
    with pytest.raises(HTTPException) as caught:
        _usage_operation_id(key, metered=True)
    assert caught.value.status_code == expected_status
    assert "operation_id" in caught.value.detail["message"]


def test_unmetered_helper_keeps_generated_key_behavior():
    assert len(_usage_operation_id()) == 32
    assert len(_usage_operation_id("x" * 129)) == 32
    assert _usage_operation_id(" caller-key ", metered=True) == "caller-key"

"""Metered scene requests must carry the originator's retry key."""

import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from db.models.scene import DescribeOperation, DescribeRun
from scene.interface_adapters.http.routers.describe import _usage_operation_id
from scene.tests.test_app1_usage_scene_census import (
    _FakeAdmission,
    _census_client,
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

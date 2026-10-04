"""APP-1: metered describe-run submits require a caller-owned operation key."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import func, select

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from db.models.scene import DescribeRun, DescribeRunItem
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from scene.tests.demo_quota_harness import demo_quota_client

KEY = "app1-key-0123456789abcdef"


class _RecordingAdmission:
    def __init__(self) -> None:
        self.reserves: list[dict] = []

    async def reserve(
        self,
        tenant_id,
        *,
        idempotency_key,
        job_id,
        cost_units,
        operation_id=None,
        request_fingerprint=None,
        queue_bytes=0,
    ):
        self.reserves.append(
            {
                "tenant_id": tenant_id,
                "idempotency_key": idempotency_key,
                "operation_id": operation_id,
                "cost_units": cost_units,
                "request_fingerprint": request_fingerprint,
                "queue_bytes": queue_bytes,
            }
        )
        return UsageTicket(
            uuid.uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=operation_id or idempotency_key,
            request_fingerprint=request_fingerprint or "",
            job_id=job_id,
            fence_token="fence-app1-key-required",
        )

    async def commit(self, ticket):
        del ticket

    async def release(self, ticket):
        del ticket

    async def commit_fenced(self, ticket, *, fence_token):
        del ticket, fence_token

    async def release_fenced(self, ticket, *, fence_token):
        del ticket, fence_token


def _install_admission(client) -> _RecordingAdmission:
    admission = _RecordingAdmission()
    client.app.state.usage_admission_service = admission
    client.app.dependency_overrides[get_usage_admission_service] = lambda: admission
    return admission


def _no_worker(monkeypatch) -> None:
    async def _noop(**_kwargs):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def _submit(client, tenant_id: str, *, key: str | None = None, operation_id: str | None = None):
    data = {"tenant_id": str(tenant_id), "media_ids": json.dumps([70])}
    if key is not None:
        data["idempotency_key"] = key
    if operation_id is not None:
        data["operation_id"] = operation_id
    files = [("image_70", ("70.png", b"\x89PNG\r\n\x1a\n", "image/png"))]
    return client.post("/scene/describe/run", data=data, files=files)


def _row_counts(session_factory) -> tuple[int, int]:
    async def _read() -> tuple[int, int]:
        async with session_factory() as session:
            runs = (await session.execute(select(func.count()).select_from(DescribeRun))).scalar_one()
            items = (await session.execute(select(func.count()).select_from(DescribeRunItem))).scalar_one()
            return int(runs), int(items)

    return asyncio.run(_read())


def test_keyless_submit_is_rejected_before_image_read_or_admission(monkeypatch):
    _no_worker(monkeypatch)

    async def _unexpected_image_read(*_args, **_kwargs):
        raise AssertionError("a keyless submit must be rejected before reading image parts")

    monkeypatch.setattr(describe_run_mod, "_read_image_parts", _unexpected_image_read)
    with demo_quota_client(tables="run") as (client, session_factory, _provisioned, tenant_id, _slug):
        admission = _install_admission(client)
        response = _submit(client, tenant_id)

        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "idempotency_key_required"
        assert detail["field"] == "idempotency_key"
        assert detail["message"]
        assert admission.reserves == []
        assert _row_counts(session_factory) == (0, 0)


@pytest.mark.parametrize(
    ("key", "operation_id"),
    [(KEY, None), (None, "caller-op-aaaaaaaa")],
    ids=["idempotency_key", "operation_id"],
)
def test_either_caller_identity_accepts_a_run(monkeypatch, key, operation_id):
    _no_worker(monkeypatch)
    with demo_quota_client(tables="run") as (client, session_factory, _provisioned, tenant_id, _slug):
        admission = _install_admission(client)
        response = _submit(client, tenant_id, key=key, operation_id=operation_id)

        assert response.status_code == 202, response.text
        assert len(admission.reserves) == 1
        assert _row_counts(session_factory) == (1, 1)


def test_same_key_replay_creates_one_run_and_one_reservation(monkeypatch):
    _no_worker(monkeypatch)
    with demo_quota_client(tables="run") as (client, session_factory, _provisioned, tenant_id, _slug):
        admission = _install_admission(client)
        first = _submit(client, tenant_id, key=KEY)
        replay = _submit(client, tenant_id, key=KEY)

        assert first.status_code == 202, first.text
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == first.json()["run_id"]
        assert len(admission.reserves) == 1
        assert _row_counts(session_factory) == (1, 1)

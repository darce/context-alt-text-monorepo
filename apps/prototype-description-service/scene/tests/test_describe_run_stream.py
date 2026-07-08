"""Describe-run status, cancel, and stream routes."""

from __future__ import annotations

import json
import uuid

import pytest

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.domain.describe_run import DescribeRunStatus
from scene.tests.test_describe_run_worker import TENANT_ID, _client, _submit


@pytest.fixture(autouse=True)
def _reset_sse_exit_event():
    # sse_starlette caches a module-global asyncio.Event bound to the first loop;
    # each TestClient uses a fresh loop, so reset it per test to avoid a
    # cross-loop "bound to a different event loop" RuntimeError.
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit_event = None
    yield
    AppStatus.should_exit_event = None


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def _create_run(client) -> str:
    response = _submit(client, [70])
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_status_and_cancel_routes(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        status_response = client.get(f"/scene/describe/run/{run_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == DescribeRunStatus.PENDING
        assert "eta_seconds" in status_response.json()

        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["cancel_requested"] is True


def test_stream_emits_progress_and_done_for_terminal_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200  # PENDING -> CANCELLED (terminal)

        with client.stream("GET", f"/scene/describe/run/{run_id}/stream") as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert "event: progress" in body
    assert "event: done" in body
    progress_line = next(line for line in body.splitlines() if line.startswith("data: "))
    payload = json.loads(progress_line.removeprefix("data: "))
    assert payload["type"] == "describe_progress"
    assert payload["run_id"] == run_id
    assert payload["gpu_state"] is None
    assert "eta_seconds" in payload


class _Snap:
    def __init__(self, status: str, phase: str, completed: int, total: int = 2):
        self.id = uuid.uuid4()
        self.tenant_id = TENANT_ID
        self.status = status
        self.phase = phase
        self.completed_items = completed
        self.failed_items = 0
        self.skipped_items = 0
        self.total_items = total
        self.cancel_requested = False
        self.started_at = None


def test_stream_emits_multiple_progress_events_as_run_advances(monkeypatch):
    """S3-01: the poll loop re-reads state and emits a progress event per advance,
    then a terminal done event — not one stale snapshot."""
    monkeypatch.setattr(describe_run_mod, "_STREAM_POLL_INTERVAL", 0.01)

    snaps = [
        _Snap("pending", "queued", 0),
        _Snap("running", "describing", 1),
        _Snap("completed", "complete", 2),
    ]
    calls = {"i": 0}

    async def fake_get_run(self, *, tenant_id, run_id):
        idx = min(calls["i"], len(snaps) - 1)
        calls["i"] += 1
        return snaps[idx]

    monkeypatch.setattr(DescribeRunRepository, "get_run", fake_get_run)

    with _client() as (client, _):
        rid = str(uuid.uuid4())
        with client.stream("GET", f"/scene/describe/run/{rid}/stream") as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert body.count("event: progress") >= 2, body
    assert "event: done" in body
    # the last emitted status must be the terminal one
    data_lines = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    assert data_lines[-1]["status"] == "completed"
    # earlier snapshots were distinct (not a single stale read)
    statuses = [d["status"] for d in data_lines]
    assert "pending" in statuses and "running" in statuses


def test_stream_sets_tenant_context_on_each_poll_session(monkeypatch):
    """BE-02: each fresh poll session must scope RLS, not just _prepare_repo."""
    _no_worker(monkeypatch)
    calls: list = []
    real = describe_run_mod.set_tenant_context

    async def recorder(session, tenant_id):
        calls.append(tenant_id)
        await real(session, tenant_id)

    monkeypatch.setattr(describe_run_mod, "set_tenant_context", recorder)
    with _client() as (client, _):
        run_id = _create_run(client)
        client.delete(f"/scene/describe/run/{run_id}")  # PENDING -> CANCELLED (terminal)
        calls.clear()
        with client.stream("GET", f"/scene/describe/run/{run_id}/stream") as response:
            "".join(response.iter_text())
    # _prepare_repo scopes the request session (1) + the poll loop scopes its own
    # fresh session (>=1) -> requiring >=2 proves the poll session was scoped.
    assert calls.count(TENANT_ID) >= 2


def test_stream_missing_run_emits_error(monkeypatch):
    async def fake_get_run(self, *, tenant_id, run_id):
        return None

    monkeypatch.setattr(DescribeRunRepository, "get_run", fake_get_run)
    with _client() as (client, _):
        rid = str(uuid.uuid4())
        with client.stream("GET", f"/scene/describe/run/{rid}/stream") as response:
            body = "".join(response.iter_text())
    assert "event: error" in body
    assert "describe run not found" in body

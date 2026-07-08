"""WBUX-4 S6-01: HTTP-level coverage for the describe-run status-poll and cancel
routes.

The INT-03 stream removal (commit 9b9aa45) deleted test_describe_run_stream.py,
which also carried the ONLY route-level test for GET /scene/describe/run/{id}
(status poll) and DELETE /scene/describe/run/{id} (cancel). This restores that
coverage without the removed SSE stream assertions.
"""

from __future__ import annotations

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.domain.describe_run import DescribeRunStatus
from scene.tests.test_describe_run_worker import _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def _create_run(client) -> str:
    response = _submit(client, [70])
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_status_route_returns_run_snapshot(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        status_response = client.get(f"/scene/describe/run/{run_id}")
        assert status_response.status_code == 200, status_response.text
        body = status_response.json()
        assert body["run_id"] == run_id
        assert body["status"] == DescribeRunStatus.PENDING
        assert "eta_seconds" in body


def test_status_route_404_for_unknown_run(monkeypatch):
    import uuid

    _no_worker(monkeypatch)
    with _client() as (client, _):
        missing = uuid.uuid4()
        resp = client.get(f"/scene/describe/run/{missing}")
        assert resp.status_code == 404


def test_cancel_route_flags_cancel_requested(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _):
        run_id = _create_run(client)
        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200, cancel_response.text
        body = cancel_response.json()
        assert body["cancel_requested"] is True
        # A cancel on a still-PENDING run resolves terminal-CANCELLED immediately.
        assert body["status"] == DescribeRunStatus.CANCELLED


def test_cancel_route_404_for_unknown_run(monkeypatch):
    import uuid

    _no_worker(monkeypatch)
    with _client() as (client, _):
        missing = uuid.uuid4()
        resp = client.delete(f"/scene/describe/run/{missing}")
        assert resp.status_code == 404

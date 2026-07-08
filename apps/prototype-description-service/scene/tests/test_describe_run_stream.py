"""Describe-run status, cancel, and stream routes."""

from __future__ import annotations

import json
import uuid

from scene.domain.describe_run import DescribeRunStatus
from scene.tests.test_describe_run_worker import TENANT_ID, _client


def _create_run(client) -> str:
    response = client.post("/scene/describe/run", json={"tenant_id": str(TENANT_ID), "media_ids": [70]})
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_status_and_cancel_routes():
    with _client() as (client, _):
        run_id = _create_run(client)
        status_response = client.get(f"/scene/describe/run/{run_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == DescribeRunStatus.PENDING

        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["cancel_requested"] is True


def test_stream_emits_progress_and_done_for_terminal_run():
    with _client() as (client, _):
        run_id = _create_run(client)
        cancel_response = client.delete(f"/scene/describe/run/{run_id}")
        assert cancel_response.status_code == 200

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

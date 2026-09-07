"""GUIDEDFIX-2: the server discloses the generation budget it enforces.

The guided client used to wait on a locally invented ceiling because
``DescribeRunResponse`` never carried the server's own bound ([RES-02],
[PERF-09]). ``deadline_seconds`` is snapshotted at accept and replayed
unchanged on every poll, so one run shows the client one stable number.
"""

from __future__ import annotations

import uuid

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.config.settings import DescriptionSettings
from scene.tests.test_describe_run_worker import TENANT_ID, _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def test_submit_discloses_the_configured_generation_timeout(monkeypatch):
    _no_worker(monkeypatch)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "123.5")
    with _client() as (client, _sf):
        response = _submit(client, [70])
        assert response.status_code == 202, response.text
        assert response.json()["deadline_seconds"] == DescriptionSettings().generation_timeout_seconds
        assert response.json()["deadline_seconds"] == 123.5


def test_accepted_run_persists_the_deadline_on_the_run_row(monkeypatch):
    _no_worker(monkeypatch)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "77")
    with _client() as (client, sf):
        response = _submit(client, [70])
        assert response.status_code == 202, response.text
        run_id = uuid.UUID(response.json()["run_id"])

        import asyncio

        async def _row():
            async with sf() as s:
                return await DescribeRunRepository(s).get_run(tenant_id=TENANT_ID, run_id=run_id)

        run = asyncio.run(_row())
        assert run is not None
        assert run.deadline_seconds == 77.0


def test_status_poll_replays_the_accept_time_deadline_after_env_change(monkeypatch):
    """The client must see one stable number per run, not a re-read of settings."""
    _no_worker(monkeypatch)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "180")
    with _client() as (client, _sf):
        submitted = _submit(client, [70])
        assert submitted.status_code == 202, submitted.text
        run_id = submitted.json()["run_id"]
        assert submitted.json()["deadline_seconds"] == 180.0

        monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "9")
        assert DescriptionSettings().generation_timeout_seconds == 9.0

        polled = client.get(f"/scene/describe/run/{run_id}")
        assert polled.status_code == 200, polled.text
        assert polled.json()["deadline_seconds"] == 180.0


def test_deadline_is_a_positive_float_on_every_run_created_through_the_route(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _sf):
        response = _submit(client, [70, 71])
        assert response.status_code == 202, response.text
        deadline = response.json()["deadline_seconds"]
        assert isinstance(deadline, float)
        assert deadline > 0

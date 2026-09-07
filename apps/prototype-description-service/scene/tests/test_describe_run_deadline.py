"""GUIDEDFIX-2: the server discloses the generation budget it actually enforces.

The guided client used to wait on a locally invented ceiling because
``DescribeRunResponse`` never carried the server's own bound ([RES-02],
[PERF-09]). ``deadline_seconds`` is snapshotted at accept and replayed
unchanged on every poll, so one run shows the client one stable number.

[S01] The disclosed number is the whole run's enforced generation budget:
the per-item envelope the worker enforces (naming budget + the describe
timeout the worker is handed) times the run's unique item count, because the
worker processes items serially. It excludes GPU warm-up by contract — the
client adds that leg itself. These tests pin the number to those two knobs
independently, never by restating the route's own expression.
"""

from __future__ import annotations

import uuid

import scene.application.describe_run_worker as describe_run_worker
import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.application.describe_run_worker import item_envelope_seconds
from scene.config.settings import DescriptionSettings
from scene.domain.description import DescriptionAdapterKind
from scene.tests.test_describe_run_worker import TENANT_ID, _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def _spy_worker(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _spy(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _spy)
    return calls


class _LocalCpuAdapter:
    """Stand-in for the local_cpu adapter: only ``kind`` steers the budget."""

    kind = DescriptionAdapterKind.LOCAL_CPU


def test_submit_discloses_the_run_budget_the_worker_enforces(monkeypatch):
    """S01: the disclosed budget is the enforced one, written out independently.

    Predicted RED on the pre-fix route: it persisted
    ``settings.generation_timeout_seconds`` verbatim, so a 2-item run disclosed
    123.5 while the worker was allowed 2 x (10 + 123.5) = 267.0. The expected
    value here is a literal built from the two knobs the worker reads, not a
    restatement of the route's expression.
    """
    _no_worker(monkeypatch)
    monkeypatch.setattr(describe_run_worker, "NAMING_BUDGET_SECONDS", 10.0)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "123.5")
    with _client() as (client, _sf):
        response = _submit(client, [70, 71])
        assert response.status_code == 202, response.text
        assert response.json()["deadline_seconds"] == 267.0
        assert response.json()["deadline_seconds"] != DescriptionSettings().generation_timeout_seconds


def test_disclosed_deadline_matches_the_timeout_the_worker_is_actually_handed(monkeypatch):
    """The disclosure and the worker's argument must come from one expression."""
    calls = _spy_worker(monkeypatch)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "40")
    with _client() as (client, _sf):
        response = _submit(client, [70, 71, 72])
        assert response.status_code == 202, response.text
        assert len(calls) == 1
        worker_timeout = calls[0]["timeout_seconds"]
        assert response.json()["deadline_seconds"] == item_envelope_seconds(worker_timeout) * 3


def test_local_cpu_deadline_follows_the_adapter_not_the_description_setting(monkeypatch):
    """S01 second axis: local_cpu enforces VlmSettings, not ACX_DESCRIPTION_TIMEOUT_SECONDS.

    Pre-fix, a local_cpu run disclosed 180.0 while a stalled item died at ~30s.
    """
    calls = _spy_worker(monkeypatch)
    monkeypatch.setattr(describe_run_worker, "NAMING_BUDGET_SECONDS", 10.0)
    monkeypatch.setattr(describe_run_mod, "get_description_adapter", lambda: _LocalCpuAdapter())
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("ACX_VLM_TIMEOUT_SECONDS", "20")
    with _client() as (client, _sf):
        response = _submit(client, [70])
        assert response.status_code == 202, response.text
        assert calls[0]["timeout_seconds"] == 20.0
        assert response.json()["deadline_seconds"] == 30.0
        assert response.json()["deadline_seconds"] != 180.0


def test_deadline_scales_with_the_number_of_unique_items(monkeypatch):
    """Items run serially, so the run's budget is per-item envelope x item count.

    Duplicates are deduped before inference, so they must not inflate the budget.
    """
    _no_worker(monkeypatch)
    monkeypatch.setattr(describe_run_worker, "NAMING_BUDGET_SECONDS", 10.0)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "20")
    with _client() as (client, _sf):
        one = _submit(client, [70])
        four = _submit(client, [70, 71, 72, 73])
        duplicated = _submit(client, [70, 70, 70], images_for=[70])
        assert one.json()["deadline_seconds"] == 30.0
        assert four.json()["deadline_seconds"] == 120.0
        assert duplicated.json()["deadline_seconds"] == 30.0


def test_accepted_run_persists_the_deadline_on_the_run_row(monkeypatch):
    _no_worker(monkeypatch)
    monkeypatch.setattr(describe_run_worker, "NAMING_BUDGET_SECONDS", 10.0)
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
        assert run.deadline_seconds == 87.0


def test_status_poll_replays_the_accept_time_deadline_after_env_change(monkeypatch):
    """The client must see one stable number per run, not a re-read of settings."""
    _no_worker(monkeypatch)
    monkeypatch.setattr(describe_run_worker, "NAMING_BUDGET_SECONDS", 10.0)
    monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "180")
    with _client() as (client, _sf):
        submitted = _submit(client, [70])
        assert submitted.status_code == 202, submitted.text
        run_id = submitted.json()["run_id"]
        assert submitted.json()["deadline_seconds"] == 190.0

        monkeypatch.setenv("ACX_DESCRIPTION_TIMEOUT_SECONDS", "9")
        assert DescriptionSettings().generation_timeout_seconds == 9.0

        polled = client.get(f"/scene/describe/run/{run_id}")
        assert polled.status_code == 200, polled.text
        assert polled.json()["deadline_seconds"] == 190.0


def test_deadline_is_a_positive_float_on_every_run_created_through_the_route(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _sf):
        response = _submit(client, [70, 71])
        assert response.status_code == 202, response.text
        deadline = response.json()["deadline_seconds"]
        assert isinstance(deadline, float)
        assert deadline > 0

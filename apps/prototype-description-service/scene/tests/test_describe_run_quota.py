"""GUIDEDFIX-2 [S07]/[S08]: demo-quota behaviour of the keyed describe-run submit.

The idempotency reordering (reserve first, then charge) asserts an invariant no
existing test covered: one key spends at most one run's worth of demo quota, no
matter how many times the caller retries or how two racing retries interleave.
The two idempotency test modules both drive a non-demo auth context, so quota is
inert there. These tests use the real demo registry harness instead, so
``demo_instances.recognition_used`` is the assertion surface.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import func, select

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from db.models.scene import DescribeRun, DescribeRunItem
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from scene.application.describe_run_repository import DescribeRunRepository
from scene.tests.demo_quota_harness import demo_quota_client
from scene.tests.demo_quota_harness import recognition_used as _used

KEY_A = "quota-key-aaaaaaaaaaaa"
KEY_B = "quota-key-bbbbbbbbbbbb"


class _PassAdmission:
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
        del queue_bytes
        return UsageTicket(
            uuid.uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=operation_id or idempotency_key,
            request_fingerprint=request_fingerprint or "",
            job_id=job_id,
            fence_token="fence-quota-run",
        )

    async def commit(self, ticket):
        del ticket

    async def release(self, ticket):
        del ticket

    async def commit_fenced(self, ticket, *, fence_token):
        del ticket, fence_token

    async def release_fenced(self, ticket, *, fence_token):
        del ticket, fence_token


def _install_admission(client) -> _PassAdmission:
    admission = _PassAdmission()
    client.app.state.usage_admission_service = admission
    client.app.dependency_overrides[get_usage_admission_service] = lambda: admission
    return admission


def _no_worker(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _noop(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)
    return calls


def _submit(client, tenant_id: str, media_ids: list[int], *, key: str | None = None):
    files = [(f"image_{m}", (f"{m}.png", b"\x89PNG\r\n\x1a\n", "image/png")) for m in media_ids]
    data = {"tenant_id": str(tenant_id), "media_ids": json.dumps(media_ids)}
    if key is not None:
        data["idempotency_key"] = key
    return client.post("/scene/describe/run", data=data, files=files or None)


def _row_counts(sf) -> tuple[int, int]:
    async def _read() -> tuple[int, int]:
        async with sf() as s:
            runs = (await s.execute(select(func.count()).select_from(DescribeRun))).scalar_one()
            items = (await s.execute(select(func.count()).select_from(DescribeRunItem))).scalar_one()
            return int(runs), int(items)

    return asyncio.run(_read())


def test_first_accept_charges_the_demo_quota_exactly_once(monkeypatch):
    """Baseline for the two invariants below: N unique items cost N units, once."""
    _no_worker(monkeypatch)
    with demo_quota_client(recognition_quota=5, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        accepted = _submit(client, tenant_id, [70, 71], key=KEY_A)
        assert accepted.status_code == 202, accepted.text
        assert _used(sf, slug) == 2


def test_replaying_one_key_never_charges_the_demo_quota_twice(monkeypatch):
    """[S08] The whole point of the token: a blind retry must be free.

    Charging on replay would let a flaky network drain a demo instance's shared
    compute budget, which is exactly the cost the key was introduced to bound.
    """
    enqueues = _no_worker(monkeypatch)
    with demo_quota_client(recognition_quota=5, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        first = _submit(client, tenant_id, [70, 71], key=KEY_A)
        assert first.status_code == 202, first.text
        assert _used(sf, slug) == 2

        replay = _submit(client, tenant_id, [70, 71], key=KEY_A)
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == first.json()["run_id"]
        # Charged once, enqueued once, and one run row exists.
        assert _used(sf, slug) == 2
        assert len(enqueues) == 1
        assert _row_counts(sf)[0] == 1


def test_a_race_loser_rolls_back_before_it_can_spend_demo_quota(monkeypatch):
    """[S08] The reservation ordering's stated invariant, under a real budget.

    The submit route charges only *after* ``create_run`` returns, so the loser of
    a two-retry race must exit through the IntegrityError branch having spent
    nothing. The race window is opened deterministically by blinding the
    pre-check read once (returning None as it would for a caller whose read ran
    before the winner's insert committed); the unique index is then the only
    thing standing between the loser and a second paid run.
    """
    enqueues = _no_worker(monkeypatch)
    real_lookup = DescribeRunRepository.get_run_by_idempotency_key
    blinded: list[int] = []

    async def _blind_first_precheck(self, *, tenant_id, idempotency_key):
        if not blinded:
            blinded.append(1)
            return None
        return await real_lookup(self, tenant_id=tenant_id, idempotency_key=idempotency_key)

    with demo_quota_client(recognition_quota=5, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        winner = _submit(client, tenant_id, [70, 71], key=KEY_A)
        assert winner.status_code == 202, winner.text
        assert _used(sf, slug) == 2

        monkeypatch.setattr(DescribeRunRepository, "get_run_by_idempotency_key", _blind_first_precheck)
        loser = _submit(client, tenant_id, [70, 71], key=KEY_A)

        assert blinded == [1], "the pre-check was never reached; the race window did not open"
        assert loser.status_code == 202, loser.text
        assert loser.json()["run_id"] == winner.json()["run_id"]
        # The loser's insert violated the unique index and rolled back: no second
        # charge, no second run, no second background job.
        assert _used(sf, slug) == 2
        assert _row_counts(sf)[0] == 1
        assert len(enqueues) == 1


def test_distinct_keys_still_charge_per_run(monkeypatch):
    """Guard against over-correcting: dedupe is per key, not per payload."""
    _no_worker(monkeypatch)
    with demo_quota_client(recognition_quota=5, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        assert _submit(client, tenant_id, [70], key=KEY_A).status_code == 202
        assert _submit(client, tenant_id, [70], key=KEY_B).status_code == 202
        assert _used(sf, slug) == 2


def test_over_quota_demo_key_is_rejected_before_the_run_is_inserted(monkeypatch):
    """[S07] The 429 must not be paid for with an insert-then-rollback.

    Predicted RED on the pre-fix route: rejection lived only in
    ``maybe_consume_demo_quota``, which runs *after* ``create_run`` has flushed
    the run row plus one item per media id with the submitted bytes inline (up
    to ``max_description_image_bytes`` each, up to 200 items). Every rejected
    request therefore paid ~N x image-size of write IO before being told no.
    """
    _no_worker(monkeypatch)
    real_create = DescribeRunRepository.create_run
    created: list[tuple] = []

    async def _spy_create(self, **kwargs):
        created.append((kwargs.get("media_ids"),))
        return await real_create(self, **kwargs)

    monkeypatch.setattr(DescribeRunRepository, "create_run", _spy_create)

    with demo_quota_client(recognition_quota=2, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        rejected = _submit(client, tenant_id, [70, 71, 72], key=KEY_A)
        assert rejected.status_code == 429, rejected.text
        assert rejected.json()["detail"]["code"] == "demo_quota_exceeded"
        assert created == [], "create_run ran before the over-quota key was rejected"
        assert _used(sf, slug) == 0
        assert _row_counts(sf) == (0, 0)

        # The cheap pre-check is an optimisation, not a new gate: a request that
        # fits still goes all the way through and is charged.
        ok = _submit(client, tenant_id, [70, 71], key=KEY_B)
        assert ok.status_code == 202, ok.text
        assert len(created) == 1
        assert _used(sf, slug) == 2


def test_a_non_demo_key_is_untouched_by_the_pre_check(monkeypatch):
    """[S07] The pre-check reads the demo registry only; other tenants pass through."""
    _no_worker(monkeypatch)
    with demo_quota_client(recognition_quota=1, non_demo=True, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        response = _submit(client, tenant_id, [70, 71, 72], key=KEY_A)
        assert response.status_code == 202, response.text
        assert _used(sf, slug) == 0
        assert uuid.UUID(response.json()["run_id"])


def test_lost_202_replay_after_last_demo_quota_unit_does_not_429(monkeypatch):
    """Same-fingerprint retry after the last quota unit must replay, not 429."""
    enqueues = _no_worker(monkeypatch)
    with demo_quota_client(recognition_quota=2, tables="run") as (client, sf, _p, tenant_id, slug):
        _install_admission(client)
        first = _submit(client, tenant_id, [70, 71], key=KEY_A)
        assert first.status_code == 202, first.text
        assert _used(sf, slug) == 2

        replay = _submit(client, tenant_id, [70, 71], key=KEY_A)
        assert replay.status_code == 202, replay.text
        assert replay.json()["run_id"] == first.json()["run_id"]
        assert _used(sf, slug) == 2
        assert len(enqueues) == 1
        assert _row_counts(sf)[0] == 1

        new_key = _submit(client, tenant_id, [70, 71], key=KEY_B)
        assert new_key.status_code == 429, new_key.text
        assert new_key.json()["detail"]["code"] == "demo_quota_exceeded"

        changed = _submit(client, tenant_id, [72, 73], key=KEY_A)
        assert changed.status_code == 409, changed.text

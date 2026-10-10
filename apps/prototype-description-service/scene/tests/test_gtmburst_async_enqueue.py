"""GTMBURST-ASYNC-01/02: real persistence with faults before worker delivery.

TEST-06 / TEST-15 (heuristics-canon v0.25.6): removing enqueue ownership
must make the fresh-key retry fail; removing reseeding must hide the item.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import FormData, Headers, UploadFile

from db.models import Tenant
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from recognition.domain.portal_contracts import UsageTicket
from scene.domain.describe_run import TERMINAL_RUN_STATUSES, DescribeItemStatus
from scene.interface_adapters.http.routers import describe as route

TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
IMAGE = b"enqueue-image"


class CountingGate(route.AsyncAdmissionGate):
    def __init__(self):
        super().__init__(max_jobs=1, max_retained_image_bytes=len(IMAGE))
        self.releases = 0

    def release(self, image_len):
        self.releases += 1
        super().release(image_len)


class Admission:
    def __init__(self):
        self.released = []

    async def reserve(self, tenant_id, *, idempotency_key, job_id, cost_units, **kwargs):
        return UsageTicket(
            uuid.uuid4(),
            tenant_id,
            idempotency_key,
            cost_units,
            operation_id=kwargs["operation_id"],
            request_fingerprint=kwargs["request_fingerprint"],
            job_id=job_id,
            fence_token="enqueue-fence",
        )

    async def commit(self, ticket):
        pass

    async def release(self, ticket):
        self.released.append(ticket)

    async def release_fenced(self, ticket, *, fence_token):
        assert fence_token == ticket.fence_token
        await self.release(ticket)


class Harness:
    def __init__(self, factory):
        self.factory = factory
        self.admission = Admission()

    async def submit(self, *, tasks=None, operation=None, image=IMAGE, session=None):
        operation = operation or uuid.uuid4().hex
        form = FormData(
            [
                ("request", json.dumps({"tenant_id": str(TENANT), "media_id": 42})),
                ("operation_id", operation),
                (
                    "image_42",
                    UploadFile(
                        io.BytesIO(image), filename="image.jpg", headers=Headers({"content-type": "image/jpeg"})
                    ),
                ),
            ]
        )

        async def request_form():
            return form

        async def invoke(current):
            return await route.enqueue_describe_image(
                background_tasks=tasks if tasks is not None else BackgroundTasks(),
                request=SimpleNamespace(form=request_form),
                auth=SimpleNamespace(tenant_claim=str(TENANT), user_id=None),
                session=current,
                cpu_adapter=SimpleNamespace(),
                gpu_adapter=SimpleNamespace(n_passes=1),
                usage_admission_service=self.admission,
            )

        if session is not None:
            return await invoke(session)
        async with self.factory() as current:
            return await invoke(current)

    async def rows(self):
        async with self.factory() as session:
            return list((await session.scalars(select(DescribeRun))).all()), list(
                (await session.scalars(select(DescribeRunItem))).all()
            )


@pytest.fixture
def gate(monkeypatch):
    gate = CountingGate()
    monkeypatch.setattr(route, "_ASYNC_ADMISSION", gate)

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(route, "_maybe_purge_expired_single_runs", noop)
    monkeypatch.setattr(route, "dump_load_snapshot", noop)
    monkeypatch.setattr(route, "run_async_describe_job", noop)
    return gate


@pytest_asyncio.fixture
async def harness(tmp_path, gate):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'enqueue.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                Tenant.__table__,
                DescribeRun.__table__,
                DescribeRunItem.__table__,
            ],
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Tenant(id=TENANT, site_url="https://enqueue.test"))
        await session.commit()
    try:
        yield Harness(factory)
    finally:
        await engine.dispose()


def inject_fault(monkeypatch, stage, session, *, barrier=None):
    owner, name = {
        "factory": (route, "worker_session_factory"),
        "audit": (route, "_BackgroundDescriptionAuditSink"),
        "metrics": (route, "_DescriptionMetricsSink"),
        "create": (route.DescribeRunRepository, "create_single_run"),
        "bind": (route, "_bind_run_usage"),
        "quota": (route, "maybe_consume_demo_quota"),
        "quota_commit_after": (route, "maybe_consume_demo_quota"),
        "commit": (session, "commit"),
        "commit_after": (session, "commit"),
        "purge": (route, "_maybe_purge_expired_single_runs"),
        "snapshot": (route, "dump_load_snapshot"),
        "read": (route.DescribeRunRepository, "get_single_run_item"),
        "projection": (route, "_job_result_from_item"),
        "registration": (BackgroundTasks, "add_task"),
    }[stage]
    original = getattr(owner, name)

    def fail(*args, **kwargs):
        # Even an add_task implementation which appends before failing must
        # leave no reachable worker after enqueue cleanup has released its slot.
        if stage == "registration":
            original(*args, **kwargs)
        raise RuntimeError(f"injected {stage}")

    async def fail_async(*args, **kwargs):
        if stage in {"create", "commit_after"}:
            await original(*args, **kwargs)
        if stage == "quota_commit_after":
            # The real demo-quota producer may durably commit the request
            # transaction before restoring its safety/tenant settings.
            await session.commit()
        if barrier is not None:
            barrier.set()
            await asyncio.Event().wait()
        fail(*args, **kwargs)

    monkeypatch.setattr(
        owner, name, fail if stage in {"factory", "audit", "metrics", "projection", "registration"} else fail_async
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage",
    [
        "factory",
        "audit",
        "metrics",
        "create",
        "bind",
        "quota",
        "quota_commit_after",
        "commit",
        "commit_after",
        "read",
        "projection",
        "registration",
    ],
)
async def test_fault_releases_slot_bytes_and_reconciles_orphan(harness, gate, monkeypatch, stage):
    tasks = BackgroundTasks()
    async with harness.factory() as session:
        with monkeypatch.context() as fault:
            inject_fault(fault, stage, session)
            with pytest.raises(HTTPException) as failure:
                await harness.submit(tasks=tasks, session=session)
            assert failure.value.status_code == 500
            assert f"injected {stage}" in str(failure.value.__cause__)
        assert gate.releases == 1, f"{stage} leaked or double-released admission"
        assert (gate._job_count, gate._retained_image_bytes) == (0, 0)
        assert tasks.tasks == [], "failed response retained a worker"
    runs, items = await harness.rows()
    if stage in {"quota_commit_after", "commit_after", "read", "projection", "registration"}:
        assert len(items) == 1
        assert items[0].status == DescribeItemStatus.FAILED
        assert items[0].image_bytes is None
        assert runs[0].status in TERMINAL_RUN_STATUSES
    else:
        assert not runs and not items, "uncommitted enqueue survived cleanup"
    assert len(harness.admission.released) == 1
    retry_tasks = BackgroundTasks()
    result = await harness.submit(tasks=retry_tasks)
    assert result.status == "queued", f"{stage}: fresh key did not enqueue"
    await retry_tasks()
    assert gate.releases == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["create", "bind", "quota", "quota_commit_after", "commit", "commit_after", "purge", "snapshot", "read"]
)
async def test_cancellation_propagates_and_drains_enqueue(harness, gate, monkeypatch, stage):
    barrier = asyncio.Event()
    tasks = BackgroundTasks()
    async with harness.factory() as session:
        with monkeypatch.context() as fault:
            inject_fault(fault, stage, session, barrier=barrier)
            pending = asyncio.create_task(harness.submit(tasks=tasks, session=session))
            await asyncio.wait_for(barrier.wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        assert gate.releases == 1, f"cancellation at {stage} leaked admission"
        assert (gate._job_count, gate._retained_image_bytes) == (0, 0)
        assert not tasks.tasks
    runs, items = await harness.rows()
    if stage in {"quota_commit_after", "commit_after", "purge", "snapshot", "read"}:
        assert len(items) == 1
        assert items[0].status == DescribeItemStatus.FAILED
        assert items[0].image_bytes is None
        assert runs[0].status in TERMINAL_RUN_STATUSES
    else:
        assert not runs
    # Preserve admit_usage's cancellation contract: durable terminal evidence
    # enables recovery; local capacity release is separate from billing.
    assert not harness.admission.released
    retry_tasks = BackgroundTasks()
    await harness.submit(tasks=retry_tasks)
    await retry_tasks()
    assert gate.releases == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["normal", "crash", "cancel"])
async def test_worker_owns_one_release_without_releasing_another_job(harness, gate, monkeypatch, outcome):
    gate._max_jobs = 2
    gate._max_retained_image_bytes = len(IMAGE) * 2
    tasks = BackgroundTasks()
    result = await harness.submit(tasks=tasks)
    assert result.status == "queued"
    assert gate.releases == 0
    assert gate.try_acquire(len(IMAGE)) is None  # unrelated live reservation

    async def worker(**kwargs):
        if outcome == "crash":
            raise RuntimeError("worker crashed")
        if outcome == "cancel":
            raise asyncio.CancelledError()

    monkeypatch.setattr(route, "run_async_describe_job", worker)
    if outcome == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await tasks()
    else:
        await tasks()
    assert gate.releases == 1
    assert (gate._job_count, gate._retained_image_bytes) == (1, len(IMAGE))


@pytest.mark.asyncio
async def test_replay_conflict_and_tenant_isolation(harness, gate):
    operation = uuid.uuid4().hex
    tasks = BackgroundTasks()
    first = await harness.submit(tasks=tasks, operation=operation)
    replay_tasks = BackgroundTasks()
    replay = await harness.submit(tasks=replay_tasks, operation=operation)
    assert replay.job_id == first.job_id
    assert not replay_tasks.tasks
    assert gate._job_count == 1
    with pytest.raises(HTTPException) as conflict:
        await harness.submit(operation=operation, image=b"different")
    assert conflict.value.status_code == 409
    async with harness.factory() as session:
        with pytest.raises(HTTPException) as hidden:
            await route.get_describe_job(
                first.job_id, auth=SimpleNamespace(tenant_claim=str(uuid.uuid4())), session=session
            )
        assert hidden.value.status_code == 404
        own = await route.get_describe_job(
            first.job_id, auth=SimpleNamespace(tenant_claim=str(TENANT)), session=session
        )
        assert own.job_id == first.job_id
    await tasks()
    assert gate.releases == 1


@pytest.mark.asyncio
async def test_response_read_reseeds_after_real_commit(harness, gate, monkeypatch):
    # Ordering surrogate only. PostgreSQL enforcement is a separate gate.
    async with harness.factory() as session:
        tenant_context = None
        commit = session.commit
        read = route.DescribeRunRepository.get_single_run_item

        async def seed(current, tenant):
            nonlocal tenant_context
            if current is session:
                tenant_context = tenant

        async def commit_and_reset():
            nonlocal tenant_context
            await commit()
            tenant_context = None

        async def restricted_read(repo, **kwargs):
            if repo._session is session and tenant_context != kwargs["tenant_id"]:
                return None
            return await read(repo, **kwargs)

        monkeypatch.setattr(route, "set_tenant_context", seed)
        monkeypatch.setattr(session, "commit", commit_and_reset)
        monkeypatch.setattr(route.DescribeRunRepository, "get_single_run_item", restricted_read)
        tasks = BackgroundTasks()
        result = await harness.submit(tasks=tasks, session=session)
        assert result.status == "queued"
        await tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_failure", ["exception", "cancellation"])
async def test_cancellation_during_cleanup_is_propagated_after_durable_drain(harness, gate, monkeypatch, first_failure):
    cleanup_entered = asyncio.Event()
    finish_cleanup = asyncio.Event()
    enqueue_entered = asyncio.Event()
    original = route.DescribeRunRepository.set_item_failed

    async def delayed_cleanup(repo, **kwargs):
        cleanup_entered.set()
        await finish_cleanup.wait()
        return await original(repo, **kwargs)

    monkeypatch.setattr(route.DescribeRunRepository, "set_item_failed", delayed_cleanup)
    tasks = BackgroundTasks()
    async with harness.factory() as session:
        stage = "projection" if first_failure == "exception" else "snapshot"
        inject_fault(monkeypatch, stage, session, barrier=enqueue_entered)
        pending = asyncio.create_task(harness.submit(tasks=tasks, session=session))
        if first_failure == "cancellation":
            await asyncio.wait_for(enqueue_entered.wait(), 5)
            pending.cancel()
        await asyncio.wait_for(cleanup_entered.wait(), 5)
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done(), "cancellation abandoned the cleanup transaction"
        finish_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert gate.releases == 1
    assert (gate._job_count, gate._retained_image_bytes) == (0, 0)
    assert not tasks.tasks
    runs, items = await harness.rows()
    assert items[0].status == DescribeItemStatus.FAILED
    assert items[0].image_bytes is None
    assert runs[0].status in TERMINAL_RUN_STATUSES


@pytest.mark.asyncio
async def test_cleanup_database_failure_is_logged_without_success_or_slot_leak(harness, gate, monkeypatch, caplog):
    async def unavailable(repo, **kwargs):
        raise RuntimeError("reconciliation database unavailable")

    monkeypatch.setattr(route.DescribeRunRepository, "set_item_failed", unavailable)
    async with harness.factory() as session:
        inject_fault(monkeypatch, "projection", session)
        with pytest.raises(HTTPException) as failure:
            await harness.submit(session=session)
    assert failure.value.status_code == 500
    assert "injected projection" in str(failure.value.__cause__)
    assert "undelivered describe job cleanup failed" in caplog.text
    assert gate.releases == 1
    assert (gate._job_count, gate._retained_image_bytes) == (0, 0)
    # DB unavailability cannot be disguised as successful reconciliation.
    # The queued durable row remains for the existing restart recovery path.
    runs, items = await harness.rows()
    assert items[0].status == DescribeItemStatus.QUEUED


@pytest.mark.asyncio
async def test_failed_racing_create_does_not_reconcile_the_winning_enqueue(harness, gate, monkeypatch):
    gate._max_jobs = 2
    gate._max_retained_image_bytes = len(IMAGE) * 2
    operation = uuid.uuid4().hex
    winner_tasks = BackgroundTasks()
    winner = await harness.submit(tasks=winner_tasks, operation=operation)
    reserve = harness.admission.reserve

    async def replay_ticket(*args, **kwargs):
        return replace(await reserve(*args, **kwargs), job_id=winner.job_id)

    async def lookup_before_winner_committed(*args, **kwargs):
        return None

    # Model an operation replay whose initial SELECT preceded the winner's
    # commit. The real duplicate INSERT fails; this request owns no durable row.
    loser_tasks = BackgroundTasks()
    with monkeypatch.context() as race:
        race.setattr(harness.admission, "reserve", replay_ticket)
        race.setattr(route, "_run_by_usage_operation", lookup_before_winner_committed)
        with pytest.raises(HTTPException) as failure:
            await harness.submit(tasks=loser_tasks, operation=operation)
    assert failure.value.status_code == 500
    runs, items = await harness.rows()
    assert len(items) == 1
    assert items[0].status == DescribeItemStatus.QUEUED, "losing create failed the winner's live job"
    assert items[0].image_bytes == IMAGE
    assert not loser_tasks.tasks
    assert gate.releases == 1
    assert (gate._job_count, gate._retained_image_bytes) == (1, len(IMAGE))
    assert not harness.admission.released, "replay released the winner's usage ticket"
    await winner_tasks()
    assert gate.releases == 2

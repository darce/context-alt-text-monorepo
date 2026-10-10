"""GTMBURST-ASYNC-01/02/03: enqueue ownership and composed background scheduling.

TEST-06 / TEST-15 (heuristics-canon v0.25.6): removing enqueue ownership
must make the fresh-key retry fail; removing reseeding must hide the item;
removing worker priority must strand work behind failed/cancelled auth telemetry.
"""

from __future__ import annotations

import asyncio
import io
import json
import uuid
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import FormData, Headers, UploadFile

from db.models import Tenant
from db.models.base_imports import Base
from db.models.scene import DescribeRun, DescribeRunItem
from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps import auth as production_auth
from recognition.interface_adapters.http.deps import get_optional_session
from recognition.interface_adapters.http.deps.usage_admission import get_usage_admission_service
from scene.domain.describe_run import TERMINAL_RUN_STATUSES, DescribeItemStatus
from scene.interface_adapters.http.deps import get_async_gpu_description_adapter, get_description_adapter
from scene.interface_adapters.http.routers import describe as route

TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
IMAGE = b"enqueue-image"


class AuthenticatedEnqueueApp:
    """Real auth dependency, telemetry callback and Starlette response scheduler.

    Auth lookup and telemetry storage are seams; record_api_key_use itself is
    deliberately left intact. The worker seam verifies committed ownership and
    persists a known terminal failure, without exercising GPU/billing services.
    """

    def __init__(self, monkeypatch, factory):
        self.outcome = "healthy"
        self.telemetry_entered = asyncio.Event()
        self.telemetry_calls = 0
        self.telemetry_commits = 0
        self.telemetry_closes = 0
        self.worker_runs = []
        self.sent = []
        self.admission = Admission()
        self.tenant = TENANT

        async def noop(*args, **kwargs):
            pass

        async def lookup(*args, **kwargs):
            return str(self.tenant), "scheduler-api-key", None, False

        async def touch(repo, api_key_id):
            assert api_key_id == "scheduler-api-key"
            self.telemetry_calls += 1
            self.telemetry_entered.set()
            if self.outcome == "cancellation":
                await asyncio.Event().wait()

        async def commit():
            self.telemetry_commits += 1

        async def close():
            self.telemetry_closes += 1
            if self.outcome == "exception":
                # Production callback's finally can fail even though its update
                # body catches ordinary errors. Starlette must still own work.
                raise RuntimeError("auth telemetry close failed")

        monkeypatch.setattr(production_auth, "_lookup_api_key", lookup)
        monkeypatch.setattr(
            production_auth,
            "get_security_settings",
            lambda: SimpleNamespace(auth_enabled=True, api_key_header="authorization", api_key_hash_algorithm="sha256"),
        )
        monkeypatch.setattr(
            production_auth,
            "async_session_factory",
            lambda: SimpleNamespace(commit=commit, rollback=noop, close=close),
        )
        monkeypatch.setattr(production_auth.SqlAlchemyApiKeyRepository, "touch_by_id", touch)
        monkeypatch.setattr(route, "maybe_consume_demo_quota", noop)
        monkeypatch.setattr(route, "worker_session_factory", lambda session: factory)

        async def worker(*, tenant_id, run_id, session_factory, **kwargs):
            assert any(message["type"] == "http.response.body" for message in self.sent), "worker ran before response"
            async with session_factory() as session:
                await route.set_tenant_context(session, tenant_id)
                repo = route.DescribeRunRepository(session)
                item = await repo.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
                assert item is not None, "worker did not receive a committed job"
                assert item.status == DescribeItemStatus.QUEUED
                assert item.image_bytes == IMAGE
                self.worker_runs.append(run_id)
                await repo.set_item_failed(
                    tenant_id=tenant_id, run_id=run_id, media_id=item.media_id, error="scheduler test worker failure"
                )
                await session.commit()

        monkeypatch.setattr(route, "run_async_describe_job", worker)
        self.app = FastAPI()
        self.app.include_router(route.router, prefix="/scene")

        async def session_dependency():
            async with factory() as session:
                yield session

        async def admission_dependency():
            return self.admission

        async def adapter_dependency():
            return SimpleNamespace(n_passes=1)

        self.app.dependency_overrides[get_optional_session] = session_dependency
        self.app.dependency_overrides[get_usage_admission_service] = admission_dependency
        self.app.dependency_overrides[get_description_adapter] = adapter_dependency
        self.app.dependency_overrides[get_async_gpu_description_adapter] = adapter_dependency

    async def __call__(self, scope, receive, send):
        async def observe(message):
            self.sent.append(message)
            await send(message)

        await self.app(scope, receive, observe)

    async def submit(self, client):
        self.sent.clear()
        return await client.post(
            "/scene/describe/async",
            headers={"Authorization": "Bearer scheduler-test-key", "X-Tenant-ID": str(self.tenant)},
            data={
                "request": json.dumps({"tenant_id": str(self.tenant), "media_id": 42}),
                "operation_id": uuid.uuid4().hex,
            },
            files={"image_42": ("image.jpg", IMAGE, "image/jpeg")},
        )

    def sent_result(self):
        start = next(message for message in self.sent if message["type"] == "http.response.start")
        assert start["status"] == 200
        body = b"".join(message.get("body", b"") for message in self.sent if message["type"] == "http.response.body")
        result = json.loads(body)
        assert result["status"] == "queued"
        return result


async def exercise_auth_telemetry_outcome(app, client, gate, outcome):
    """Observe the sent 200 even when the after-response callback propagates."""
    app.outcome = outcome
    pending = asyncio.create_task(app.submit(client))
    try:
        if outcome == "cancellation":
            await asyncio.wait_for(app.telemetry_entered.wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        elif outcome == "exception":
            with pytest.raises(RuntimeError, match="auth telemetry close failed"):
                await asyncio.wait_for(pending, 5)
        else:
            response = await asyncio.wait_for(pending, 5)
            assert response.status_code == 200
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
    result = app.sent_result()
    assert app.worker_runs == [uuid.UUID(result["job_id"])], "auth telemetry prevented committed worker delivery"
    assert app.telemetry_calls == app.telemetry_closes == 1, "production auth telemetry was discarded"
    assert app.telemetry_commits == (0 if outcome == "cancellation" else 1)
    assert gate.releases == 1, "worker leaked or double-released admission"
    assert (gate._job_count, gate._retained_image_bytes) == (0, 0)
    return uuid.UUID(result["job_id"])


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


@pytest.fixture
def scheduler_store(monkeypatch):
    """Commit visibility surrogate for scheduling only; never PostgreSQL evidence."""
    committed = {}

    class Session:
        def __init__(self):
            self.pending = {}

        async def commit(self):
            committed.update(self.pending)
            self.pending.clear()

        async def rollback(self):
            self.pending.clear()

    @asynccontextmanager
    async def factory():
        yield Session()

    class Repository:
        def __init__(self, session):
            self.session = session

        async def create_single_run(self, *, tenant_id, media_id, image_bytes, run_id, **kwargs):
            self.session.pending[run_id] = SimpleNamespace(
                tenant_id=tenant_id,
                media_id=media_id,
                status=DescribeItemStatus.QUEUED,
                image_bytes=image_bytes,
                last_error=None,
            )

        async def get_single_run_item(self, *, tenant_id, run_id):
            item = committed.get(run_id)
            return item if item is not None and item.tenant_id == tenant_id else None

        async def set_item_failed(self, *, tenant_id, run_id, media_id, error):
            item = await self.get_single_run_item(tenant_id=tenant_id, run_id=run_id)
            assert item is not None and item.media_id == media_id
            self.session.pending[run_id] = SimpleNamespace(
                **{**vars(item), "status": DescribeItemStatus.FAILED, "image_bytes": None, "last_error": error}
            )

    async def noop(*args, **kwargs):
        pass

    monkeypatch.setattr(route, "DescribeRunRepository", Repository)
    monkeypatch.setattr(route, "_run_by_usage_operation", noop)
    monkeypatch.setattr(route, "_bind_run_usage", noop)
    monkeypatch.setattr(route, "set_tenant_context", noop)
    monkeypatch.setattr(route, "require_tenant_record", noop)
    return SimpleNamespace(factory=factory, items=committed)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["healthy", "exception", "cancellation"])
async def test_auth_telemetry_cannot_strand_committed_worker(scheduler_store, gate, monkeypatch, outcome):
    app = AuthenticatedEnqueueApp(monkeypatch, scheduler_store.factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        job_id = await exercise_auth_telemetry_outcome(app, client, gate, outcome)
        item = scheduler_store.items[job_id]
        assert item.status == DescribeItemStatus.FAILED
        assert item.image_bytes is None
        assert item.last_error == "scheduler test worker failure"
        app.outcome = "healthy"
        retry = await asyncio.wait_for(app.submit(client), 5)
        assert retry.status_code == 200, retry.text
        retry_id = uuid.UUID(retry.json()["job_id"])
        assert retry_id != job_id
        assert app.worker_runs == [job_id, retry_id]
        assert scheduler_store.items[retry_id].status == DescribeItemStatus.FAILED
        assert gate.releases == 2
        assert (gate._job_count, gate._retained_image_bytes) == (0, 0)


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

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import IdentityClusteringJob
from recognition.application.embedding.detector import DetectionAdapterError, StubFaceDetector
from recognition.application.embedding.generator import StubEmbeddingGenerator
from recognition.domain.job import JobStatus
from recognition.worker import scan_worker as scan_worker_module
from recognition.worker.handlers.base import JobHandler


class _FakeDetector:
    def __init__(self, adapter: object, client: object | None = None) -> None:
        self.adapter = adapter
        self.client = client


class _FakeGenerator:
    def __init__(self, adapter: object) -> None:
        self.adapter = adapter


@pytest.mark.asyncio
async def test_scan_worker_main_uses_database_settings_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    used: dict[str, object] = {}

    class _FakeConnection:
        async def execute(self, _statement) -> None:  # noqa: ANN001
            return None

    class _FakeConnectContext:
        async def __aenter__(self) -> _FakeConnection:
            return _FakeConnection()

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

    class _FakeEngine:
        def connect(self) -> _FakeConnectContext:
            return _FakeConnectContext()

        async def dispose(self) -> None:
            return None

    class _FakeWorker:
        def __init__(self, config, *, metrics=None) -> None:  # noqa: ANN001
            used["dsn"] = config.postgres_dsn
            used["metrics"] = metrics

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def run_forever(self) -> None:
            raise asyncio.CancelledError()

    exporter_calls: list[object] = []

    def _fake_start_exporter(*, metrics, config) -> None:  # noqa: ANN001
        exporter_calls.append((metrics, config))

    monkeypatch.setattr(
        scan_worker_module,
        "get_database_settings",
        lambda: SimpleNamespace(postgres_dsn="postgresql+asyncpg://context:context@localhost:5432/alt_context_service"),
    )
    monkeypatch.setattr(scan_worker_module, "create_async_engine", lambda dsn, **_kwargs: _FakeEngine())
    monkeypatch.setattr(scan_worker_module, "ScanWorker", _FakeWorker)
    # Composition root starts the exporter once — never bind a real port in unit tests.
    monkeypatch.setattr(scan_worker_module, "start_process_metrics_exporter", _fake_start_exporter)

    await scan_worker_module._main()

    assert used["dsn"] == "postgresql+asyncpg://context:context@localhost:5432/alt_context_service"
    assert used["metrics"] is not None
    assert len(exporter_calls) == 1
    assert exporter_calls[0][0] is used["metrics"]


@pytest.mark.asyncio
async def test_scan_worker_reuses_shared_insightface_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    adapter = object()
    calls = 0

    async def _fake_build_embedding_runtime(*, settings, http_client=None, adapter_provider=None, metrics=None, **_kwargs):
        nonlocal calls
        calls += 1
        return _FakeDetector(adapter, client=http_client), _FakeGenerator(adapter)

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    monkeypatch.setattr(scan_worker_module, "build_embedding_runtime", _fake_build_embedding_runtime)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    await worker._ensure_embedding_runtime()
    await worker._ensure_embedding_runtime()

    assert calls == 1
    assert worker._embedding_runtime_ready is True
    assert isinstance(worker._detector, _FakeDetector)
    assert isinstance(worker._generator, _FakeGenerator)
    assert worker._detector.adapter is adapter
    assert worker._generator.adapter is adapter

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_scan_worker_retries_runtime_init_after_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from recognition.application.embedding.detector import UnavailableFaceDetector
    from recognition.application.embedding.generator import UnavailableEmbeddingGenerator

    calls = 0

    async def _failing_build(*, settings, http_client=None, adapter_provider=None, metrics=None, **_kwargs):
        nonlocal calls
        calls += 1
        return (
            UnavailableFaceDetector("transient load failure"),
            UnavailableEmbeddingGenerator("transient load failure"),
        )

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    monkeypatch.setattr(scan_worker_module, "build_embedding_runtime", _failing_build)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    await worker._ensure_embedding_runtime()

    assert calls == 1
    assert worker._embedding_runtime_ready is False
    assert worker._embedding_retry_after is not None
    # S3CR-02: no httpx client while runtime is not ready.
    assert worker._http_client is None
    assert not isinstance(worker._scan_handler._detector, StubFaceDetector)
    assert not isinstance(worker._scan_handler._generator, StubEmbeddingGenerator)

    with pytest.raises(DetectionAdapterError, match="transient load failure"):
        await worker._scan_handler._detector.detect(["http://example.test/image.jpg"])

    worker._embedding_retry_after = None
    await worker._ensure_embedding_runtime()
    assert calls == 2
    assert worker._http_client is None

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# Phase 4: MV refresh suppression (finding 1169)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suppress_mv_refresh_flag_initialises_false(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Worker must initialise _suppress_mv_refresh_once=False (no stale-flag state on startup)."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    assert worker._retry_suppressed_job_id is None
    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_refresh_mv_skips_when_next_job_matches_suppressed_id(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """_refresh_mv_if_needed must skip the DB refresh when the suppressed job ID matches the next pending job."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    target_job_id = uuid.uuid4()
    worker._retry_suppressed_job_id = target_job_id
    # Make _last_mv_refresh_time old enough that refresh would normally fire.
    worker._last_mv_refresh_time = datetime.min.replace(tzinfo=UTC)

    committed: list[bool] = []
    scalar_calls: list[object] = []

    class _FakeResult:
        def __init__(self, value: object) -> None:
            self._value = value

        def scalar(self) -> object:
            return self._value

    class _FakeSession:
        async def commit(self) -> None:
            committed.append(True)

        async def scalar(self, stmt: object) -> object:  # noqa: ANN001
            scalar_calls.append(stmt)
            return target_job_id  # next job matches the suppressed ID

    now = datetime.now(tz=UTC)
    await worker._refresh_mv_if_needed(_FakeSession(), now)

    suppressed_after: uuid.UUID | None = worker._retry_suppressed_job_id
    assert suppressed_after is None, "suppressed ID must be cleared"
    assert committed == [], "commit must not be called when MV refresh is suppressed"
    assert len(scalar_calls) == 1, "should peek the pending queue once"

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_refresh_mv_proceeds_when_next_job_differs_from_suppressed_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """_refresh_mv_if_needed must proceed with refresh when the next pending job is a different job."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    suppressed_id = uuid.uuid4()
    different_id = uuid.uuid4()
    worker._retry_suppressed_job_id = suppressed_id
    # Make _last_mv_refresh_time RECENT so the elapsed check aborts before any DB write.
    worker._last_mv_refresh_time = datetime.now(tz=UTC)

    class _FakeSession:
        async def commit(self) -> None:
            pass

        async def scalar(self, stmt: object) -> object:  # noqa: ANN001
            return different_id  # next job does NOT match

    now = datetime.now(tz=UTC)
    await worker._refresh_mv_if_needed(_FakeSession(), now)

    # Suppressed ID must be cleared even when suppression didn't apply.
    suppressed_after: uuid.UUID | None = worker._retry_suppressed_job_id
    assert suppressed_after is None

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_refresh_mv_skip_does_not_advance_last_refresh_time(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A headroom skip must remain eligible for the next worker cycle."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    from recognition.infrastructure.repositories import cluster_repository

    class _FakeClusterRepository:
        def __init__(self, _session) -> None:
            pass

        async def refresh_centroids_view_concurrent(self):
            return cluster_repository.MvRefreshOutcome.SKIPPED_HEADROOM

    monkeypatch.setattr(cluster_repository, "SqlAlchemyClusterRepository", _FakeClusterRepository)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    previous_refresh_time = datetime(2020, 1, 1, tzinfo=UTC)
    worker._last_mv_refresh_time = previous_refresh_time
    committed: list[bool] = []

    class _FakeSession:
        async def commit(self) -> None:
            committed.append(True)

    await worker._refresh_mv_if_needed(_FakeSession(), datetime.now(tz=UTC))

    assert committed == []
    assert worker._last_mv_refresh_time == previous_refresh_time

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# E15-11-BR-11 regression: factory must survive _ensure_embedding_runtime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_handler_keeps_object_store_factory_after_embedding_init(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """E15-11-BR-11: ScanWorker.__init__ wires an ObjectStoreFactory into the
    scan handler. _ensure_embedding_runtime later rebuilds the handler with
    the (now-real) detector + generator. That rebuild must preserve the
    factory; otherwise multipart queue items pass through as raw file:/// /
    strings to the detector and worker-side cleanup is silently disabled.
    """

    async def _fake_build(*, settings, http_client=None, adapter_provider=None, metrics=None, **_kwargs):
        return _FakeDetector(object(), client=http_client), _FakeGenerator(object())

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    monkeypatch.setattr(scan_worker_module, "build_embedding_runtime", _fake_build)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )

    initial_factory = worker._scan_handler._object_store_factory
    assert initial_factory is not None, "constructor must wire ObjectStoreFactory"

    await worker._ensure_embedding_runtime()

    rebuilt_factory = worker._scan_handler._object_store_factory
    assert rebuilt_factory is not None, (
        "BR-11: _ensure_embedding_runtime must preserve the ObjectStoreFactory "
        "when rebuilding the scan handler with the production detector/generator"
    )

    # Detector should now be the production InsightFace stub-equivalent.
    assert isinstance(worker._scan_handler._detector, _FakeDetector)

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_scan_handler_factory_persists_through_embedding_failure_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When the InsightFace adapter fails to load, _ensure_embedding_runtime
    installs fail-closed detector/generator and rebuilds the handler. The
    factory must survive that failure rebuild as well — otherwise a
    transient adapter failure permanently disables multipart support."""

    async def _failing_build(*, settings, http_client=None, adapter_provider=None, metrics=None, **_kwargs):
        from recognition.application.embedding.detector import UnavailableFaceDetector
        from recognition.application.embedding.generator import UnavailableEmbeddingGenerator

        return UnavailableFaceDetector("transient failure"), UnavailableEmbeddingGenerator("transient failure")

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    monkeypatch.setattr(scan_worker_module, "build_embedding_runtime", _failing_build)

    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )

    await worker._ensure_embedding_runtime()

    assert worker._scan_handler._object_store_factory is not None, (
        "BR-11: factory must survive the fail-closed rebuild on adapter failure"
    )

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# WORKEROBS-6: _process_pending_clustering_jobs phase extraction
# Characterization tests pin the claim / dispatch / failure-recovery seams that
# the 134-line god-method splits into. The retry-classification path was an
# untested risky internal before this slice.
# ---------------------------------------------------------------------------


async def _noop_async(*_args: object, **_kwargs: object) -> None:
    return None


class _FakeAsyncCtx:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


class _FakeScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _RecordingFreshSession:
    def __init__(self, failed_job: object) -> None:
        self._failed_job = failed_job
        self.committed = False

    async def execute(self, _stmt: object) -> _FakeScalarResult:
        return _FakeScalarResult(self._failed_job)

    async def commit(self) -> None:
        self.committed = True


class _RollbackOnlySession:
    def __init__(self) -> None:
        self.rolled_back = False

    async def rollback(self) -> None:
        self.rolled_back = True


def _make_test_worker(monkeypatch: pytest.MonkeyPatch, tmp_path) -> scan_worker_module.ScanWorker:  # noqa: ANN001
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    return scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )


@pytest.mark.asyncio
async def test_claim_next_clustering_job_returns_none_when_queue_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)

    class _EmptySession:
        async def execute(self, _stmt: object) -> _FakeScalarResult:
            return _FakeScalarResult(None)

    out = await worker._claim_next_clustering_job(session=_EmptySession(), now=datetime.now(tz=UTC))
    assert out is None

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_dispatch_unsupported_job_type_marks_failed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(scan_worker_module, "ensure_job_context", _noop_async)
    worker._job_handlers = {}

    job = SimpleNamespace(job_type="bogus", status=None, error_message=None, completed_at=None)

    class _FlushSession:
        async def flush(self) -> None:
            return None

    await worker._dispatch_clustering_job(job=job, session=_FlushSession())
    assert job.status == JobStatus.FAILED
    assert job.error_message == "unsupported job_type: bogus"
    assert job.completed_at is not None

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_dispatch_known_job_type_invokes_handler(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)

    class _RecordingHandler(JobHandler[IdentityClusteringJob]):
        def __init__(self) -> None:
            self.handled: list[tuple[object, object]] = []

        async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
            self.handled.append((job, session))

    handler = _RecordingHandler()
    worker._job_handlers = {"clustering": handler}
    job = SimpleNamespace(job_type="clustering")
    sentinel_session = object()

    await worker._dispatch_clustering_job(job=job, session=sentinel_session)
    assert handler.handled == [(job, sentinel_session)]

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_record_failure_requeues_transient_under_budget(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", _noop_async)
    monkeypatch.setattr(scan_worker_module, "set_tenant_context", _noop_async)

    job_id = uuid.uuid4()
    failed_job = SimpleNamespace(
        id=job_id,
        payload={"retry_count": 0},
        status=None,
        started_at=object(),
        completed_at=object(),
        error_message=None,
    )
    fresh = _RecordingFreshSession(failed_job)
    monkeypatch.setattr(worker, "_session_factory", lambda: _FakeAsyncCtx(fresh))
    main = _RollbackOnlySession()

    await worker._record_clustering_job_failure(
        exc=OSError("transient"), session=main, job_id=job_id, tenant_id=uuid.uuid4()
    )

    assert main.rolled_back is True
    assert failed_job.status == JobStatus.PENDING
    assert failed_job.started_at is None
    assert failed_job.completed_at is None
    assert worker._retry_suppressed_job_id == job_id
    assert failed_job.payload["retry_count"] == 1
    assert failed_job.payload["last_error_code"] == "OSError"
    assert fresh.committed is True

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_record_failure_fails_deterministic_without_retry(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", _noop_async)
    monkeypatch.setattr(scan_worker_module, "set_tenant_context", _noop_async)

    job_id = uuid.uuid4()
    failed_job = SimpleNamespace(
        id=job_id, payload={"retry_count": 0}, status=None, started_at=object(), completed_at=None, error_message=None
    )
    fresh = _RecordingFreshSession(failed_job)
    monkeypatch.setattr(worker, "_session_factory", lambda: _FakeAsyncCtx(fresh))

    await worker._record_clustering_job_failure(
        exc=ValueError("deterministic"), session=_RollbackOnlySession(), job_id=job_id, tenant_id=uuid.uuid4()
    )

    assert failed_job.status == JobStatus.FAILED
    assert failed_job.error_message == "deterministic"
    assert failed_job.completed_at is not None
    assert worker._retry_suppressed_job_id is None
    assert failed_job.payload["retry_count"] == 1

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_record_failure_fails_transient_when_budget_exhausted(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", _noop_async)
    monkeypatch.setattr(scan_worker_module, "set_tenant_context", _noop_async)

    job_id = uuid.uuid4()
    # retry_count already at max_attempts -> new_retry_count == max+1, not < max -> permanent fail.
    failed_job = SimpleNamespace(
        id=job_id,
        payload={"retry_count": worker._config.max_attempts},
        status=None,
        started_at=object(),
        completed_at=None,
        error_message=None,
    )
    fresh = _RecordingFreshSession(failed_job)
    monkeypatch.setattr(worker, "_session_factory", lambda: _FakeAsyncCtx(fresh))

    await worker._record_clustering_job_failure(
        exc=OSError("transient-but-exhausted"), session=_RollbackOnlySession(), job_id=job_id, tenant_id=uuid.uuid4()
    )

    assert failed_job.status == JobStatus.FAILED
    assert worker._retry_suppressed_job_id is None

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# WORKEROBS-6 (descsvc8a-BR-02): orchestrator -> seam wiring
# The extract-method refactor introduced a thin _process_pending_clustering_jobs
# orchestrator whose try/except hands the claimed job's captured identity to the
# failure-recovery seam. These pin that handoff end-to-end (previously only the
# seams were unit-tested and the except block carried `# pragma: no cover`).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_pending_jobs_returns_false_when_no_job_claimed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)

    async def _claim(*, session: object, now: object) -> object | None:
        return None

    monkeypatch.setattr(worker, "_claim_next_clustering_job", _claim)

    result = await worker._process_pending_clustering_jobs(session=object(), now=datetime.now(tz=UTC))
    assert result is False

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_process_pending_jobs_returns_true_on_handler_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    worker = _make_test_worker(monkeypatch, tmp_path)
    job = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), job_type="clustering")

    async def _claim(*, session: object, now: object) -> object:
        return job

    monkeypatch.setattr(worker, "_claim_next_clustering_job", _claim)

    class _OkHandler(JobHandler[IdentityClusteringJob]):
        def __init__(self) -> None:
            self.calls = 0

        async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
            self.calls += 1

    handler = _OkHandler()
    worker._job_handlers = {"clustering": handler}

    recovery_called = False

    async def _record(**_kwargs: object) -> None:
        nonlocal recovery_called
        recovery_called = True

    monkeypatch.setattr(worker, "_record_clustering_job_failure", _record)

    result = await worker._process_pending_clustering_jobs(session=object(), now=datetime.now(tz=UTC))
    assert result is True
    assert handler.calls == 1
    assert recovery_called is False

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_process_pending_jobs_routes_handler_failure_to_recovery_seam(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A handler that raises must route the job's captured identity and the raised
    exception into _record_clustering_job_failure, and the orchestrator must still
    return True (the failure is handled durably, not propagated)."""
    worker = _make_test_worker(monkeypatch, tmp_path)

    job_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    job = SimpleNamespace(id=job_id, tenant_id=tenant_id, job_type="clustering")

    async def _claim(*, session: object, now: object) -> object:
        return job

    monkeypatch.setattr(worker, "_claim_next_clustering_job", _claim)

    boom = RuntimeError("handler exploded")

    class _ExplodingHandler(JobHandler[IdentityClusteringJob]):
        async def handle(self, job: IdentityClusteringJob, session: AsyncSession) -> None:
            raise boom

    worker._job_handlers = {"clustering": _ExplodingHandler()}

    recorded: dict[str, object] = {}

    async def _record(*, exc: Exception, session: object, job_id: object, tenant_id: object) -> None:
        recorded.update(exc=exc, session=session, job_id=job_id, tenant_id=tenant_id)

    monkeypatch.setattr(worker, "_record_clustering_job_failure", _record)

    sentinel_session = object()
    result = await worker._process_pending_clustering_jobs(session=sentinel_session, now=datetime.now(tz=UTC))

    assert result is True
    assert recorded["exc"] is boom
    assert recorded["session"] is sentinel_session
    assert recorded["job_id"] == job_id
    assert recorded["tenant_id"] == tenant_id

    await worker.__aexit__(None, None, None)


# ---------------------------------------------------------------------------
# FIR-4-E2E-10: runtime-ready claim guard (clustering still processes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_can_claim_scan_items_false_when_runtime_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    worker._embedding_runtime_ready = False
    assert worker._can_claim_scan_items() is False
    worker._embedding_runtime_ready = True
    assert worker._can_claim_scan_items() is True
    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_can_claim_scan_items_true_in_test_mode_even_when_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(runtime_mode="test", blob_root=tmp_path / "blobs"),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    worker._embedding_runtime_ready = False
    assert worker._can_claim_scan_items() is True
    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_run_forever_skips_pending_claim_when_runtime_not_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When embedding runtime is not ready, do not claim scan items; clustering still runs."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(
            postgres_dsn="sqlite+aiosqlite:///:memory:",
            poll_interval_seconds=0,
        )
    )
    worker._embedding_runtime_ready = False

    claim_calls: list[object] = []
    clustering_calls = 0
    cycles = 0

    class _FakeRepo:
        async def reclaim_stale_items(self, **_kwargs):  # noqa: ANN001
            return 0

        async def claim_pending_items_any(self, **kwargs):  # noqa: ANN001
            claim_calls.append(kwargs)
            return []

        async def mark_job_running(self, **_kwargs):  # noqa: ANN001
            return None

    class _FakeQueue:
        def __init__(self, _repo) -> None:  # noqa: ANN001
            pass

        async def terminate_stalled_jobs(self, **_kwargs):  # noqa: ANN001
            return 0

    class _FakeSession:
        async def commit(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):  # noqa: ANN001
            return None

    async def _probe() -> None:
        return None

    async def _refresh(_session, _now) -> None:  # noqa: ANN001
        return None

    async def _clustering(*, session, now):  # noqa: ANN001
        nonlocal clustering_calls, cycles
        clustering_calls += 1
        cycles += 1
        if cycles >= 2:
            raise asyncio.CancelledError()
        return False  # no clustering job; would fall through to claim without the guard

    async def _rls(_session) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(worker, "_probe_and_publish_embedding_runtime_capability", _probe)
    monkeypatch.setattr(worker, "_refresh_mv_if_needed", _refresh)
    monkeypatch.setattr(worker, "_process_pending_clustering_jobs", _clustering)
    monkeypatch.setattr(worker, "_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", _rls)
    monkeypatch.setattr(scan_worker_module, "SqlAlchemyScanQueueRepository", lambda _s: _FakeRepo())
    monkeypatch.setattr(scan_worker_module, "ScanQueueService", _FakeQueue)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()

    assert clustering_calls == 2
    assert claim_calls == [], "must not claim pending scan items while runtime is not ready"

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_run_forever_claims_when_runtime_ready(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Ready runtime may claim; clustering branch still preferred when it returns True."""
    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(
            postgres_dsn="sqlite+aiosqlite:///:memory:",
            poll_interval_seconds=0,
        )
    )
    worker._embedding_runtime_ready = True

    claim_calls: list[object] = []
    cycles = 0

    class _FakeRepo:
        async def reclaim_stale_items(self, **_kwargs):  # noqa: ANN001
            return 0

        async def claim_pending_items_any(self, **kwargs):  # noqa: ANN001
            claim_calls.append(kwargs)
            return []

        async def mark_job_running(self, **_kwargs):  # noqa: ANN001
            return None

    class _FakeQueue:
        def __init__(self, _repo) -> None:  # noqa: ANN001
            pass

        async def terminate_stalled_jobs(self, **_kwargs):  # noqa: ANN001
            return 0

    class _FakeSession:
        async def commit(self) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):  # noqa: ANN001
            return None

    async def _probe() -> None:
        return None

    async def _refresh(_session, _now) -> None:  # noqa: ANN001
        return None

    async def _clustering(*, session, now):  # noqa: ANN001
        nonlocal cycles
        cycles += 1
        if cycles >= 2:
            raise asyncio.CancelledError()
        return False

    async def _rls(_session) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(worker, "_probe_and_publish_embedding_runtime_capability", _probe)
    monkeypatch.setattr(worker, "_refresh_mv_if_needed", _refresh)
    monkeypatch.setattr(worker, "_process_pending_clustering_jobs", _clustering)
    monkeypatch.setattr(worker, "_session_factory", lambda: _FakeSession())
    monkeypatch.setattr(scan_worker_module, "enable_rls_bypass", _rls)
    monkeypatch.setattr(scan_worker_module, "SqlAlchemyScanQueueRepository", lambda _s: _FakeRepo())
    monkeypatch.setattr(scan_worker_module, "ScanQueueService", _FakeQueue)

    with pytest.raises(asyncio.CancelledError):
        await worker.run_forever()

    assert len(claim_calls) == 1

    await worker.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_unavailable_detector_demotes_sticky_ready_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """R2-06: mid-life Unavailable detector must demote ready and block claims."""
    from recognition.application.embedding.detector import UnavailableFaceDetector
    from recognition.application.embedding.generator import UnavailableEmbeddingGenerator

    monkeypatch.setattr(
        scan_worker_module,
        "get_recognition_settings",
        lambda: SimpleNamespace(
            runtime_mode="prod",
            blob_root=tmp_path / "blobs",
            face_pipeline=SimpleNamespace(profile="insightface"),
        ),
    )
    worker = scan_worker_module.ScanWorker(
        scan_worker_module.ScanWorkerConfig(postgres_dsn="sqlite+aiosqlite:///:memory:")
    )
    # Simulate prior success then mid-life Unavailable swap.
    worker._embedding_runtime_ready = True
    worker._detector = UnavailableFaceDetector("mid-life outage")
    worker._generator = UnavailableEmbeddingGenerator("mid-life outage")

    assert worker._can_claim_scan_items() is False
    assert worker._embedding_runtime_ready is False

    rebuilds = 0

    async def _rebuild(*, settings, http_client=None, adapter_provider=None, metrics=None, **_kwargs):
        nonlocal rebuilds
        rebuilds += 1
        return UnavailableFaceDetector("still down"), UnavailableEmbeddingGenerator("still down")

    monkeypatch.setattr(scan_worker_module, "build_embedding_runtime", _rebuild)
    worker._embedding_retry_after = None
    await worker._ensure_embedding_runtime()
    assert rebuilds == 1
    assert worker._embedding_runtime_ready is False
    assert worker._can_claim_scan_items() is False

    await worker.__aexit__(None, None, None)

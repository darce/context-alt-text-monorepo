from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from db.models import IdentityClusteringJob
from recognition.worker.handlers.clustering import ClusteringJobHandler, CurationJobHandler


class _FakeSession:
    async def flush(self) -> None:
        return None

    async def execute(self, _statement, _params=None):  # noqa: ANN001
        return None


class _FakeClusterRepository:
    def __init__(self, snapshot_version: int) -> None:
        self.snapshot_version = snapshot_version
        self.snapshot_calls: list[str] = []

    async def get_snapshot(self, tenant_id: str):
        self.snapshot_calls.append(tenant_id)
        return ([], [], self.snapshot_version, None)


class _FakeClusterService:
    def __init__(self, snapshot_version: int) -> None:
        self.cluster_repository = _FakeClusterRepository(snapshot_version)
        self.calls: list[tuple[str, str | None, bool]] = []

    async def cluster_unclustered_identities(self, tenant_id: str, job_id: str | None = None, **kwargs):
        self.calls.append((tenant_id, job_id, bool(kwargs.get("commit", True))))
        callback = kwargs.get("progress_callback")
        if callback is not None:
            await callback(4, 4)
        return SimpleNamespace(completed=4, total=4)


class _FailingClusterService:
    """Cluster service that always raises a deterministic error."""

    def __init__(self, snapshot_version: int = 0, error: Exception | None = None) -> None:
        self.cluster_repository = _FakeClusterRepository(snapshot_version)
        self.error = error or RuntimeError("integrity violation")
        self.calls: list[tuple[str, str | None]] = []

    async def cluster_unclustered_identities(self, tenant_id: str, job_id: str | None = None, **kwargs):
        self.calls.append((tenant_id, job_id))
        raise self.error


@pytest.mark.asyncio
async def test_clustering_job_handler_records_snapshot_version_on_completion(monkeypatch) -> None:
    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    handler = ClusteringJobHandler(cluster_service=_FakeClusterService(snapshot_version=987654321))
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={"scan_job_id": str(uuid.uuid4())},
    )

    await handler.handle(job, _FakeSession())

    assert job.status == "completed"
    assert job.snapshot_version == 987654321
    assert job.source_job_id == job.id


# ---------------------------------------------------------------------------
# Phase 1: Failure-durability scaffolds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clustering_job_handler_propagates_exception(monkeypatch) -> None:
    """ClusteringJobHandler must propagate exceptions so the worker can handle durability.

    The handler itself is NOT responsible for persisting failed status — that
    responsibility belongs to scan_worker._process_pending_clustering_jobs()
    which must use a fresh session after rollback.
    """

    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    error = RuntimeError("deterministic integrity error")
    handler = ClusteringJobHandler(cluster_service=_FailingClusterService(error=error))
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={"scan_job_id": str(uuid.uuid4())},
    )

    with pytest.raises(RuntimeError, match="deterministic integrity error"):
        await handler.handle(job, _FakeSession())


@pytest.mark.asyncio
async def test_clustering_job_handler_does_not_swallow_errors(monkeypatch) -> None:
    """Verify the handler does not catch and swallow clustering exceptions.

    This test documents the expected contract: exceptions from cluster_service
    must propagate up so the worker layer can persist failure state in a
    fresh session without relying on the already-rolled-back main session.
    """

    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    class _SentinelError(Exception):
        pass

    handler = ClusteringJobHandler(cluster_service=_FailingClusterService(error=_SentinelError("sentinel")))
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={},
    )

    with pytest.raises(_SentinelError):
        await handler.handle(job, _FakeSession())


# ---------------------------------------------------------------------------
# Phase 2: Durable checkpoint tests
# ---------------------------------------------------------------------------


class _FakeSessionFactory:
    """Records UPDATE statements issued by the checkpoint writer."""

    def __init__(self) -> None:
        self.committed_updates: list[dict] = []

    def __call__(self):
        return _FakeSessionContext(self)


class _FakeSessionContext:
    def __init__(self, factory: _FakeSessionFactory) -> None:
        self._factory = factory
        self._pending: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, stmt, params=None):  # noqa: ANN001
        # Capture the values from the UPDATE statement via its _values attr.
        values = {}
        if hasattr(stmt, "_values"):
            for col, val in stmt._values.items():
                values[str(col)] = val.value if hasattr(val, "value") else val
        self._pending.append(values)
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self._factory.committed_updates.extend(self._pending)
        self._pending.clear()


@pytest.mark.asyncio
async def test_clustering_job_handler_checkpoint_uses_fresh_session(monkeypatch) -> None:
    """Progress callback must commit to a fresh session so checkpoints survive main-session rollback."""

    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    factory = _FakeSessionFactory()
    handler = ClusteringJobHandler(
        cluster_service=_FakeClusterService(snapshot_version=1),
        session_factory=factory,
    )
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={},
    )

    await handler.handle(job, _FakeSession())

    # At least one checkpoint commit must have gone through the fresh session.
    assert len(factory.committed_updates) >= 1, "expected at least one durable checkpoint commit"
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_clustering_job_handler_checkpoint_updates_in_memory_job(monkeypatch) -> None:
    """progress_callback must update in-memory job fields so the final flush sees current values."""

    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    handler = ClusteringJobHandler(
        cluster_service=_FakeClusterService(snapshot_version=0),
        session_factory=_FakeSessionFactory(),
    )
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={},
    )

    await handler.handle(job, _FakeSession())

    # The callback fires with (4, 4); the final flush then sets to result.completed=4/total=4.
    assert job.processed_identities == 4
    assert job.total_identities == 4


# ---------------------------------------------------------------------------
# RLS tenant context: defense-in-depth tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clustering_job_handler_calls_ensure_job_context_before_clustering(monkeypatch) -> None:
    """ensure_job_context must be called before cluster_unclustered_identities.

    The scan worker commits the 'running' status before the clustering handler
    runs, which clears SET LOCAL tenant context.  The handler must re-establish
    context before delegating to the orchestrator so that the first chunk
    already runs with a valid tenant context and bypass flag.
    """
    call_order: list[str] = []

    async def _tracking_context(*, session, job):  # noqa: ANN001
        call_order.append("ensure_job_context")

    class _OrderTrackingClusterService(_FakeClusterService):
        async def cluster_unclustered_identities(self, *args, **kwargs):
            call_order.append("cluster_unclustered_identities")
            return await super().cluster_unclustered_identities(*args, **kwargs)

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _tracking_context)

    handler = ClusteringJobHandler(
        cluster_service=_OrderTrackingClusterService(snapshot_version=1),
        session_factory=_FakeSessionFactory(),
    )
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="clustering",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Clustering",
        payload={"scan_job_id": str(uuid.uuid4())},
    )

    await handler.handle(job, _FakeSession())

    assert "ensure_job_context" in call_order, "ensure_job_context was never called"
    assert "cluster_unclustered_identities" in call_order, "cluster_unclustered_identities was never called"
    first_context_idx = call_order.index("ensure_job_context")
    first_cluster_idx = call_order.index("cluster_unclustered_identities")
    assert first_context_idx < first_cluster_idx, (
        f"ensure_job_context must be called before cluster_unclustered_identities; actual call order: {call_order}"
    )


# ---------------------------------------------------------------------------
# CurationJobHandler: refresh_metrics wiring (E15-13-BR-20)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_curation_job_handler_passes_refresh_metrics_into_run_curation_job(monkeypatch) -> None:
    """Queued curation jobs must wire refresh_metrics so /metrics counters increment."""

    async def _noop_context(*, session, job):  # noqa: ANN001
        return None

    monkeypatch.setattr("recognition.worker.handlers.clustering.ensure_job_context", _noop_context)

    async def _fake_build_cluster_service(*, session, tenant_id):  # noqa: ANN001
        return SimpleNamespace(
            assignment_writer=SimpleNamespace(cluster_repository=object()),
        )

    monkeypatch.setattr(
        "recognition.worker.handlers.clustering.build_cluster_service",
        _fake_build_cluster_service,
    )

    captured: dict[str, object] = {}

    async def _fake_run_curation_job(**kwargs):
        captured.update(kwargs)
        return {"clusters_recomputed": 1}

    monkeypatch.setattr(
        "recognition.worker.handlers.clustering.run_curation_job",
        _fake_run_curation_job,
    )

    handler = CurationJobHandler()
    job = IdentityClusteringJob(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        job_type="curation",
        status="running",
        progress=0.0,
        total_identities=0,
        processed_identities=0,
        message="Curation",
        payload={"cluster_ids": [str(uuid.uuid4())]},
    )

    await handler.handle(job, _FakeSession())

    assert "refresh_metrics" in captured, (
        "CurationJobHandler must pass refresh_metrics into run_curation_job so queued "
        "curation jobs increment curation_refresh_attempts_total/_duration/_in_flight."
    )
    assert captured["refresh_metrics"] is not None, (
        "refresh_metrics must be a non-null collector — run_curation_job skips metric writes when it is None."
    )

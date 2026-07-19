from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from recognition.application.embedding.detector import DetectionAdapterError, DetectionTimeoutError
from recognition.application.embedding.generator import EmbeddingAdapterError, EmbeddingTimeoutError
from recognition.application.scan import service as scan_service_module
from recognition.application.scan.service import PersistIntegrityError, ScanService
from recognition.application.tasks import scan as scan_tasks
from recognition.domain.job import JobStatus


class _PhaseSession:
    def __init__(self) -> None:
        self.job = SimpleNamespace(status=JobStatus.PENDING, started_at=None)
        self.commit_calls = 0
        self.rollback_calls = 0
        self._in_transaction = True

    async def get(self, _model, _job_id):
        return self.job

    async def commit(self) -> None:
        self.commit_calls += 1
        self._in_transaction = False

    async def rollback(self) -> None:
        self.rollback_calls += 1
        self._in_transaction = True

    def in_transaction(self) -> bool:
        return self._in_transaction


class _SessionContext:
    active_count = 0

    async def __aenter__(self):
        type(self).active_count += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        type(self).active_count -= 1
        return False


@pytest.mark.asyncio
async def test_process_scan_job_uses_shared_three_phase_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _PhaseSession()
    job_id = uuid.uuid4()
    helper_state = {"called": False}
    events: list[tuple[str, bool]] = []

    class FakeDetector:
        async def detect(self, sources):
            events.append(("detect", session.in_transaction()))
            assert session.in_transaction() is False
            return []

    service = ScanService(
        session=session,
        detector=FakeDetector(),
        generator=MagicMock(),
    )

    save_job_results = AsyncMock(return_value=SimpleNamespace(id=job_id))
    monkeypatch.setattr(service, "save_job_results", save_job_results)

    async def fake_run_scan_three_phase(*, mark_running, detect, persist):
        helper_state["called"] = True
        await mark_running()
        detections = await detect()
        return await persist(detections)

    monkeypatch.setattr(scan_service_module, "run_scan_three_phase", fake_run_scan_three_phase, raising=False)

    await service.process_scan_job(
        tenant_id=str(uuid.uuid4()),
        job_id=job_id,
        media_ids=["1"],
        media_sources=["http://example.test/1.jpg"],
    )

    assert helper_state["called"] is True
    assert events == [("detect", False)]
    assert session.commit_calls == 1
    save_job_results.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_scan_job_inline_uses_shared_three_phase_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    helper_state = {"called": False}
    events: list[str] = []

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session

        async def mark_job_running(self, received_job_id):
            assert _SessionContext.active_count == 1
            events.append(f"running:{received_job_id}")
            return SimpleNamespace(id=received_job_id)

        async def save_job_results(self, **kwargs):
            assert _SessionContext.active_count == 1
            events.append(f"saved:{kwargs['job_id']}")
            return SimpleNamespace(id=kwargs["job_id"])

    class FakeDetector:
        async def detect(self, sources):
            assert _SessionContext.active_count == 0
            events.append("detect")
            return []

    class FakeGenerator:
        def __init__(self, adapter) -> None:
            self.adapter = adapter

        async def generate(self, face_images):
            return []

    async def fake_run_scan_three_phase(*, mark_running, detect, persist):
        helper_state["called"] = True
        await mark_running()
        detections = await detect()
        return await persist(detections)

    import recognition.config as recognition_config
    import recognition.infrastructure.embeddings.runtime_factory as runtime_factory

    monkeypatch.setattr(
        recognition_config,
        "get_settings",
        lambda: SimpleNamespace(runtime_mode="prod", face_pipeline=SimpleNamespace(profile="insightface")),
    )
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)
    monkeypatch.setattr(scan_service_module, "run_scan_three_phase", fake_run_scan_three_phase, raising=False)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator(object())

    monkeypatch.setattr(runtime_factory, "build_embedding_runtime", _fake_build)

    async def fake_adapter_provider():
        return object()

    await scan_tasks.process_scan_job_inline(
        tenant_id=tenant_id,
        job_id=job_id,
        media_ids=["1"],
        media_sources=["http://example.test/1.jpg"],
        session_factory=lambda: _SessionContext(),
        adapter_provider=fake_adapter_provider,
    )

    assert helper_state["called"] is True
    assert events == [f"running:{job_id}", "detect", f"saved:{job_id}"]


@pytest.mark.parametrize(
    ("exc", "expected_text", "phase"),
    [
        (DetectionTimeoutError(media_id="media-1", timeout_s=0.5), "timed out", "detect"),
        (DetectionAdapterError(media_id="media-1", error_message="detector boom"), "detector boom", "detect"),
        (EmbeddingTimeoutError(media_id="media-1", timeout_s=0.5), "timed out", "persist"),
        (EmbeddingAdapterError(media_id="media-1", error_message="generator boom"), "generator boom", "persist"),
    ],
)
@pytest.mark.asyncio
async def test_process_scan_job_marks_job_failed_on_typed_adapter_failures(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    expected_text: str,
    phase: str,
) -> None:
    session = _PhaseSession()
    job_id = uuid.uuid4()
    events: list[tuple[str, str | None]] = []

    class FakeDetector:
        async def detect(self, sources):
            events.append(("detect", None))
            if phase == "detect":
                raise exc
            return []

    service = ScanService(
        session=session,
        detector=FakeDetector(),
        generator=MagicMock(),
    )

    original_mark_running = service.mark_job_running

    async def tracking_mark_running(received_job_id):
        events.append(("running", str(received_job_id)))
        return await original_mark_running(received_job_id)

    async def failing_save_job_results(**kwargs):
        events.append(("persist", None))
        if phase == "persist":
            raise exc
        return SimpleNamespace(id=kwargs["job_id"])

    monkeypatch.setattr(service, "mark_job_running", tracking_mark_running)
    monkeypatch.setattr(service, "save_job_results", failing_save_job_results)

    with pytest.raises(type(exc)):
        await service.process_scan_job(
            tenant_id=str(uuid.uuid4()),
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
        )

    assert events[0] == ("running", str(job_id))
    assert session.job.status is JobStatus.FAILED
    assert expected_text in (session.job.error_message or "")
    assert session.job.completed_at is not None


@pytest.mark.asyncio
async def test_process_scan_job_marks_job_failed_on_persist_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR4-BR-03 [RLSE-05, OBS-08]: PersistIntegrityError → mark_job_failed (not RUNNING).

    Covers analyze_media / process_scan_job catch-set (batch/HTTP path).
    """
    session = _PhaseSession()
    job_id = uuid.uuid4()
    events: list[tuple[str, str | None]] = []
    integrity_exc = PersistIntegrityError("embedding length 127 != pgvector_dimension 128")

    class FakeDetector:
        async def detect(self, sources):
            events.append(("detect", None))
            return []

    service = ScanService(
        session=session,
        detector=FakeDetector(),
        generator=MagicMock(),
    )

    original_mark_running = service.mark_job_running

    async def tracking_mark_running(received_job_id):
        events.append(("running", str(received_job_id)))
        return await original_mark_running(received_job_id)

    async def failing_save_job_results(**kwargs):
        events.append(("persist", None))
        raise integrity_exc

    monkeypatch.setattr(service, "mark_job_running", tracking_mark_running)
    monkeypatch.setattr(service, "save_job_results", failing_save_job_results)

    with pytest.raises(PersistIntegrityError, match="embedding length"):
        await service.process_scan_job(
            tenant_id=str(uuid.uuid4()),
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
        )

    assert events[0] == ("running", str(job_id))
    assert ("persist", None) in events
    assert session.job.status is JobStatus.FAILED
    assert session.job.error_message
    assert "embedding length" in (session.job.error_message or "")
    assert session.job.completed_at is not None


class _IntegrityTrackingSession:
    """Session that records add/flush/rollback/commit ordering for integrity RED tests."""

    def __init__(self) -> None:
        self.job = SimpleNamespace(
            status=JobStatus.PENDING,
            started_at=None,
            error_message=None,
            completed_at=None,
        )
        self.ops: list[str] = []
        self.pending: list[object] = []
        self.committed_batches: list[list[object]] = []
        self._in_transaction = True

    async def get(self, _model, _job_id):
        return self.job

    def add(self, obj) -> None:
        self.pending.append(obj)
        self.ops.append("add")

    def add_all(self, objs) -> None:
        self.pending.extend(list(objs))
        self.ops.append("add_all")

    async def flush(self) -> None:
        self.ops.append("flush")

    async def rollback(self) -> None:
        self.ops.append("rollback")
        self.pending.clear()
        self._in_transaction = True

    async def commit(self) -> None:
        self.ops.append("commit")
        self.committed_batches.append(list(self.pending))
        self.pending.clear()
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction


@pytest.mark.asyncio
async def test_process_scan_job_rolls_back_partial_identity_before_mark_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOCAL47C-02: partial identity work must not survive the FAILED transition.

    If save_job_results flushes/adds identity rows for earlier media and then
    raises PersistIntegrityError, process_scan_job must rollback before
    mark_job_failed so the failure-status commit does not persist partial
    identity rows or pending reconciliation events.
    """
    session = _IntegrityTrackingSession()
    job_id = uuid.uuid4()
    integrity_exc = PersistIntegrityError("embedding length 127 != pgvector_dimension 128")
    partial_row = SimpleNamespace(kind="partial_identity", media_id=1)

    class FakeDetector:
        async def detect(self, sources):
            return []

    service = ScanService(
        session=session,
        detector=FakeDetector(),
        generator=MagicMock(),
    )

    async def failing_save_job_results(**kwargs):
        # Simulate first media persisted (flushed) then later media integrity failure.
        session.add(partial_row)
        await session.flush()
        raise integrity_exc

    monkeypatch.setattr(service, "save_job_results", failing_save_job_results)

    with pytest.raises(PersistIntegrityError, match="embedding length"):
        await service.process_scan_job(
            tenant_id=str(uuid.uuid4()),
            job_id=job_id,
            media_ids=["1", "2"],
            media_sources=["http://example.test/1.jpg", "http://example.test/2.jpg"],
        )

    assert session.job.status is JobStatus.FAILED
    assert "embedding length" in (session.job.error_message or "")
    assert "rollback" in session.ops, "must rollback before writing FAILED status"
    # Failure-status commit is the last commit; rollback must precede it.
    last_commit_idx = max(i for i, op in enumerate(session.ops) if op == "commit")
    last_rollback_idx = max(i for i, op in enumerate(session.ops) if op == "rollback")
    assert last_rollback_idx < last_commit_idx, "rollback must precede the FAILED commit"
    all_committed = [item for batch in session.committed_batches for item in batch]
    assert not any(getattr(item, "kind", None) == "partial_identity" for item in all_committed), (
        "partial identity rows must not be committed with FAILED status"
    )

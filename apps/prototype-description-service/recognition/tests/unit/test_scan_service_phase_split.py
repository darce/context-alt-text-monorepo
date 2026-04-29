from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from recognition.application.embedding.detector import DetectionAdapterError, DetectionTimeoutError
from recognition.application.embedding.generator import EmbeddingAdapterError, EmbeddingTimeoutError
from recognition.application.scan import service as scan_service_module
from recognition.application.scan.service import ScanService
from recognition.application.tasks import scan as scan_tasks
from recognition.domain.job import JobStatus


class _PhaseSession:
    def __init__(self) -> None:
        self.job = SimpleNamespace(status=JobStatus.PENDING, started_at=None)
        self.commit_calls = 0
        self._in_transaction = True

    async def get(self, _model, _job_id):
        return self.job

    async def commit(self) -> None:
        self.commit_calls += 1
        self._in_transaction = False

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

    import recognition.application.embedding.detector as detector_module
    import recognition.application.embedding.generator as generator_module
    import recognition.config as recognition_config

    monkeypatch.setattr(recognition_config, "get_settings", lambda: SimpleNamespace(runtime_mode="prod"))
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)
    monkeypatch.setattr(scan_service_module, "run_scan_three_phase", fake_run_scan_three_phase, raising=False)
    monkeypatch.setattr(detector_module, "InsightFaceFaceDetector", lambda adapter: FakeDetector())
    monkeypatch.setattr(generator_module, "InsightFaceEmbeddingGenerator", FakeGenerator)

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

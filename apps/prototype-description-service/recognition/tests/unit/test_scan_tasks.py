"""Unit tests for scan task boundary handling."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from recognition.application.embedding.detector import DetectionAdapterError, DetectionTimeoutError, FaceDetection
from recognition.application.embedding.generator import EmbeddingAdapterError, EmbeddingTimeoutError
from recognition.application.integrations import AdapterBreakerOpenError
from recognition.application.tasks import scan as scan_tasks


class _FakeSessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def rollback(self) -> None:
        return None


def _prod_settings() -> SimpleNamespace:
    return SimpleNamespace(
        runtime_mode="prod",
        face_pipeline=SimpleNamespace(profile="insightface"),
    )


@pytest.mark.asyncio
async def test_process_scan_job_inline_marks_job_failed_on_generator_breaker_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    events: list[tuple[str, str | None]] = []

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session

        async def mark_job_running(self, received_job_id):
            events.append(("running", str(received_job_id)))
            return SimpleNamespace(id=received_job_id)

        async def mark_job_failed(self, received_job_id, error_message: str):
            events.append(("failed", error_message))
            return SimpleNamespace(id=received_job_id)

        async def save_job_results(self, **kwargs):
            events.append(("saved", None))
            return SimpleNamespace(id=kwargs["job_id"])

    class FakeDetector:
        async def detect(self, sources):
            return [
                FaceDetection(
                    media_id="1",
                    bbox=(0, 0, 10, 10),
                    confidence=0.9,
                    embedding=None,
                )
            ]

    class FakeGenerator:
        async def generate(self, face_images):
            raise AdapterBreakerOpenError("insightface.analyze")

    import recognition.application.scan.service as scan_service_module

    # String-form targets resolve via importlib.import_module → live sys.modules
    # (not package attributes that can drift after del/reimport isolation tests).
    monkeypatch.setattr("recognition.config.get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.runtime_factory.build_embedding_runtime",
        _fake_build,
    )

    async def fake_adapter_provider():
        return object()

    with pytest.raises(AdapterBreakerOpenError):
        await scan_tasks.process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
            session_factory=lambda: _FakeSessionContext(),
            adapter_provider=fake_adapter_provider,
        )

    assert events[0] == ("running", job_id)
    assert events[1][0] == "failed"
    assert "insightface.analyze" in (events[1][1] or "")
    assert all(name != "saved" for name, _ in events)


@pytest.mark.asyncio
async def test_process_scan_job_inline_marks_job_failed_on_detector_breaker_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    events: list[tuple[str, str | None]] = []

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session

        async def mark_job_running(self, received_job_id):
            events.append(("running", str(received_job_id)))
            return SimpleNamespace(id=received_job_id)

        async def mark_job_failed(self, received_job_id, error_message: str):
            events.append(("failed", error_message))
            return SimpleNamespace(id=received_job_id)

        async def save_job_results(self, **kwargs):
            events.append(("saved", None))
            return SimpleNamespace(id=kwargs["job_id"])

    class FakeDetector:
        async def detect(self, sources):
            raise AdapterBreakerOpenError("insightface.detect_faces")

    class FakeGenerator:
        async def generate(self, face_images):
            raise AssertionError("generator should not run when detector breaker is open")

    import recognition.application.scan.service as scan_service_module

    monkeypatch.setattr("recognition.config.get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.runtime_factory.build_embedding_runtime",
        _fake_build,
    )

    async def fake_adapter_provider():
        return object()

    with pytest.raises(AdapterBreakerOpenError):
        await scan_tasks.process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
            session_factory=lambda: _FakeSessionContext(),
            adapter_provider=fake_adapter_provider,
        )

    assert events[0] == ("running", job_id)
    assert events[1][0] == "failed"
    assert "insightface.detect_faces" in (events[1][1] or "")
    assert all(name != "saved" for name, _ in events)


@pytest.mark.asyncio
async def test_process_scan_job_inline_marks_job_failed_when_adapter_init_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    events: list[tuple[str, str | None]] = []

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session
            self.detector = detector

        async def mark_job_running(self, received_job_id):
            events.append(("running", str(received_job_id)))
            return SimpleNamespace(id=received_job_id)

        async def mark_job_failed(self, received_job_id, error_message: str):
            events.append(("failed", error_message))
            return SimpleNamespace(id=received_job_id)

        async def save_job_results(self, **kwargs):
            events.append(("saved", None))
            return SimpleNamespace(id=kwargs["job_id"])

    import recognition.application.scan.service as scan_service_module

    monkeypatch.setattr("recognition.config.get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def failing_adapter_provider():
        raise RuntimeError("model cache missing")

    with pytest.raises(DetectionAdapterError, match="model cache missing"):
        await scan_tasks.process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
            session_factory=lambda: _FakeSessionContext(),
            adapter_provider=failing_adapter_provider,
        )

    assert events[0] == ("running", job_id)
    assert events[1][0] == "failed"
    assert "model cache missing" in (events[1][1] or "")
    assert all(name != "saved" for name, _ in events)


@pytest.mark.parametrize(
    ("exc", "expected_text", "stage"),
    [
        (DetectionTimeoutError(media_id="media-1", timeout_s=0.5), "timed out", "detector"),
        (EmbeddingTimeoutError(media_id="media-1", timeout_s=0.5), "timed out", "generator"),
        (DetectionAdapterError(media_id="media-1", error_message="detector boom"), "detector boom", "detector"),
        (EmbeddingAdapterError(media_id="media-1", error_message="generator boom"), "generator boom", "generator"),
    ],
)
@pytest.mark.asyncio
async def test_process_scan_job_inline_marks_job_failed_on_typed_adapter_failures(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    expected_text: str,
    stage: str,
) -> None:
    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    events: list[tuple[str, str | None]] = []

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session

        async def mark_job_running(self, received_job_id):
            events.append(("running", str(received_job_id)))
            return SimpleNamespace(id=received_job_id)

        async def mark_job_failed(self, received_job_id, error_message: str):
            events.append(("failed", error_message))
            return SimpleNamespace(id=received_job_id)

        async def save_job_results(self, **kwargs):
            events.append(("saved", None))
            return SimpleNamespace(id=kwargs["job_id"])

    class FakeDetector:
        async def detect(self, sources):
            if stage == "detector":
                raise exc
            return [
                FaceDetection(
                    media_id="1",
                    bbox=(0, 0, 10, 10),
                    confidence=0.9,
                    embedding=None,
                )
            ]

    class FakeGenerator:
        async def generate(self, face_images):
            if stage == "generator":
                raise exc
            raise AssertionError("generator should only run for generator-stage failures")

    import recognition.application.scan.service as scan_service_module

    monkeypatch.setattr("recognition.config.get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.runtime_factory.build_embedding_runtime",
        _fake_build,
    )

    async def fake_adapter_provider():
        return object()

    with pytest.raises(type(exc)):
        await scan_tasks.process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
            session_factory=lambda: _FakeSessionContext(),
            adapter_provider=fake_adapter_provider,
        )

    assert events[0] == ("running", job_id)
    assert events[1][0] == "failed"
    assert expected_text in (events[1][1] or "")
    assert all(name != "saved" for name, _ in events)


@pytest.mark.asyncio
async def test_process_scan_job_inline_marks_job_failed_on_persist_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR4-BR-03 [RLSE-05, OBS-08]: persist integrity must fail the job (not stuck RUNNING).

    Real producer shape: wrong-width embedding raises PersistIntegrityError from
    _persist_identities; inline catch-set must map it to mark_job_failed.
    """
    from recognition.application.scan.service import PersistIntegrityError

    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    events: list[tuple[str, str | None]] = []
    integrity_exc = PersistIntegrityError("embedding length 127 != pgvector_dimension 128")

    class FakeScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session

        async def mark_job_running(self, received_job_id):
            events.append(("running", str(received_job_id)))
            return SimpleNamespace(id=received_job_id)

        async def mark_job_failed(self, received_job_id, error_message: str):
            events.append(("failed", error_message))
            return SimpleNamespace(id=received_job_id)

        async def save_job_results(self, **kwargs):
            # Real persist-time integrity failure (wrong-width embedding path).
            raise integrity_exc

    class FakeDetector:
        async def detect(self, sources):
            import numpy as np

            # Real producer shape: corner bbox + wrong-width embedding + model_id.
            return [
                FaceDetection(
                    media_id="1",
                    bbox=(10, 10, 50, 50),
                    confidence=0.95,
                    embedding=np.zeros(127, dtype=np.float32),
                    model_id="sface@test",
                )
            ]

    class FakeGenerator:
        async def generate(self, face_images):
            raise AssertionError("face_pipeline embeds in detect; generator unused")

    import recognition.application.scan.service as scan_service_module

    monkeypatch.setattr("recognition.config.get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.runtime_factory.build_embedding_runtime",
        _fake_build,
    )

    with pytest.raises(PersistIntegrityError, match="embedding length"):
        await scan_tasks.process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=["1"],
            media_sources=["http://example.test/1.jpg"],
            session_factory=lambda: _FakeSessionContext(),
        )

    assert events[0] == ("running", job_id)
    assert events[1][0] == "failed"
    assert events[1][1]
    assert "embedding length" in (events[1][1] or "")


class _InlineIntegritySession:
    """Tracks per-session add/flush/rollback/commit for inline integrity RED tests."""

    instances: list = []

    def __init__(self) -> None:
        self.ops: list[str] = []
        self.pending: list[object] = []
        self.committed_batches: list[list[object]] = []
        self.job = SimpleNamespace(
            status="pending",
            started_at=None,
            error_message=None,
            completed_at=None,
        )
        type(self).instances.append(self)

    async def __aenter__(self):
        self.ops.append("enter")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        # Do not auto-rollback: production must call rollback explicitly (or
        # equivalent) before the failure-status transition when partial work
        # was staged on this session.
        self.ops.append("exit")
        return False

    async def get(self, _model, _job_id):
        return self.job

    def add(self, obj) -> None:
        self.pending.append(obj)
        self.ops.append("add")

    async def flush(self) -> None:
        self.ops.append("flush")

    async def rollback(self) -> None:
        self.ops.append("rollback")
        self.pending.clear()

    async def commit(self) -> None:
        self.ops.append("commit")
        self.committed_batches.append(list(self.pending))
        self.pending.clear()


@pytest.mark.asyncio
async def test_process_scan_job_inline_rolls_back_partial_identity_before_mark_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOCAL47C-02: inline path must rollback partial persist before FAILED.

    When the persistence phase stages identity work then raises
    PersistIntegrityError, process_scan_job_inline must rollback that
    session before the failure-status transition so no partial identity
    rows are committed.
    """
    from recognition.application.scan.service import PersistIntegrityError, ScanService

    tenant_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    integrity_exc = PersistIntegrityError("embedding length 127 != pgvector_dimension 128")
    partial_row = SimpleNamespace(kind="partial_identity", media_id=1)
    _InlineIntegritySession.instances = []
    events: list[tuple[str, str | None]] = []

    class TrackingScanService:
        def __init__(self, session, detector=None, generator=None, object_store_factory=None) -> None:
            self.session = session
            self._real = ScanService(session=session)

        async def mark_job_running(self, received_job_id):
            events.append(("running", str(received_job_id)))
            return await self._real.mark_job_running(received_job_id)

        async def mark_job_failed(self, received_job_id, error_message: str):
            events.append(("failed", error_message))
            return await self._real.mark_job_failed(received_job_id, error_message)

        async def save_job_results(self, **kwargs):
            # First media staged, later media raises deterministic integrity error.
            self.session.add(partial_row)
            await self.session.flush()
            raise integrity_exc

    class FakeDetector:
        async def detect(self, sources):
            return []

    class FakeGenerator:
        async def generate(self, face_images):
            raise AssertionError("generator unused when detect returns empty")

    import recognition.application.scan.service as scan_service_module

    monkeypatch.setattr("recognition.config.get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", TrackingScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(
        "recognition.infrastructure.embeddings.runtime_factory.build_embedding_runtime",
        _fake_build,
    )

    with pytest.raises(PersistIntegrityError, match="embedding length"):
        await scan_tasks.process_scan_job_inline(
            tenant_id=tenant_id,
            job_id=job_id,
            media_ids=["1", "2"],
            media_sources=["http://example.test/1.jpg", "http://example.test/2.jpg"],
            session_factory=lambda: _InlineIntegritySession(),
        )

    assert events[0][0] == "running"
    assert events[1][0] == "failed"
    assert "embedding length" in (events[1][1] or "")

    # The dirty persist session must have rolled back before FAILED was written.
    dirty_sessions = [s for s in _InlineIntegritySession.instances if "add" in s.ops]
    assert dirty_sessions, "persist phase must stage partial identity work"
    dirty = dirty_sessions[0]
    assert "rollback" in dirty.ops, "persist session must rollback before FAILED transition"
    all_committed = [item for s in _InlineIntegritySession.instances for batch in s.committed_batches for item in batch]
    assert not any(getattr(item, "kind", None) == "partial_identity" for item in all_committed), (
        "partial identity rows must not be committed after integrity failure"
    )

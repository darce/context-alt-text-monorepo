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
    import recognition.config as recognition_config
    import recognition.infrastructure.embeddings.runtime_factory as runtime_factory

    monkeypatch.setattr(recognition_config, "get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(runtime_factory, "build_embedding_runtime", _fake_build)

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
    import recognition.config as recognition_config
    import recognition.infrastructure.embeddings.runtime_factory as runtime_factory

    monkeypatch.setattr(recognition_config, "get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(runtime_factory, "build_embedding_runtime", _fake_build)

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
    import recognition.config as recognition_config

    monkeypatch.setattr(recognition_config, "get_settings", _prod_settings)
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
    import recognition.config as recognition_config
    import recognition.infrastructure.embeddings.runtime_factory as runtime_factory

    monkeypatch.setattr(recognition_config, "get_settings", _prod_settings)
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)

    async def _fake_build(*, settings, http_client=None, adapter_provider=None):
        return FakeDetector(), FakeGenerator()

    monkeypatch.setattr(runtime_factory, "build_embedding_runtime", _fake_build)

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

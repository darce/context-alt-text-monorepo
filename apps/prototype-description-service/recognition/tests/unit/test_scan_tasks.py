"""Unit tests for scan task boundary handling."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from recognition.application.embedding.detector import FaceDetection
from recognition.application.integrations import AdapterBreakerOpenError
from recognition.application.tasks import scan as scan_tasks


class _FakeSessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


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
        def __init__(self, adapter) -> None:
            self.adapter = adapter

        async def generate(self, face_images):
            raise AdapterBreakerOpenError("insightface.analyze")

    import recognition.config as recognition_config

    monkeypatch.setattr(recognition_config, "get_settings", lambda: SimpleNamespace(runtime_mode="prod"))
    monkeypatch.setattr(scan_tasks, "set_tenant_context", AsyncMock())

    import recognition.application.scan.service as scan_service_module
    import recognition.application.embedding.detector as detector_module
    import recognition.application.embedding.generator as generator_module

    monkeypatch.setattr(scan_service_module, "ScanService", FakeScanService)
    monkeypatch.setattr(detector_module, "InsightFaceFaceDetector", lambda adapter: FakeDetector())
    monkeypatch.setattr(generator_module, "InsightFaceEmbeddingGenerator", FakeGenerator)

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

"""FIR-4 S4: ReconcileResult, embedding dim guard, wide scan_media_reconciled event."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from db.settings import get_database_settings
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.scan.capability import ScanWorkerCounters, format_capability_reason
from recognition.application.scan.service import ReconcileResult, ScanService
from recognition.interface_adapters.http.middleware.correlation import (
    _correlation_id_var,
    generate_correlation_id,
)

_DB_SETTINGS = get_database_settings()
_DIM = int(_DB_SETTINGS.pgvector_dimension)


def _unit_emb(dim: int | None = None) -> np.ndarray:
    vec = np.zeros(dim if dim is not None else _DIM, dtype=np.float32)
    vec[0] = 1.0
    return vec


class _FixedDetector(FaceDetectorProtocol):
    def __init__(self, detections: list[FaceDetection]) -> None:
        self._detections = detections

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        return list(self._detections)


class _FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeSession:
    """Minimal session for unit-level persist / log tests (no real DB)."""

    def __init__(self, existing: list[object] | None = None) -> None:
        self.existing = list(existing or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flush_calls = 0

    async def execute(self, _stmt):  # noqa: ANN001
        return _FakeResult(self.existing)

    def add_all(self, rows: list[object]) -> None:
        self.added.extend(rows)
        self.existing.extend(rows)

    async def delete(self, row: object) -> None:
        self.deleted.append(row)
        if row in self.existing:
            self.existing.remove(row)

    async def flush(self) -> None:
        self.flush_calls += 1


def _det(
    *,
    media_id: str = "42",
    bbox: tuple[int, int, int, int] = (10, 10, 50, 50),
    model_id: str = "stub-detector@test",
    emb_dim: int | None = None,
) -> FaceDetection:
    return FaceDetection(
        media_id=media_id,
        bbox=bbox,
        confidence=0.95,
        embedding=_unit_emb(emb_dim),
        model_id=model_id,
    )


def _existing_row(
    *,
    bbox: tuple[int, int, int, int] = (10, 10, 50, 50),
    tenant_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    x1, y1, x2, y2 = bbox
    return SimpleNamespace(
        tenant_id=tenant_id or uuid.uuid4(),
        media_id=42,
        bbox_x=x1,
        bbox_y=y1,
        bbox_width=x2 - x1,
        bbox_height=y2 - y1,
        confidence=0.9,
        embedding=_unit_emb().tolist(),
        embedding_model="old-model",
        pose_pitch=None,
        pose_yaw=None,
        pose_roll=None,
        quality_score=None,
        image_phash=None,
        updated_at=None,
    )


@pytest.mark.asyncio
async def test_reconcile_result_new_only() -> None:
    session = _FakeSession()
    service = ScanService(session=session, detector=_FixedDetector([_det()]))
    result = await service.process_media_item(
        tenant_id=str(uuid.uuid4()),
        media_id=42,
        media_url="http://example.test/42.jpg",
    )
    assert isinstance(result, ReconcileResult)
    assert result.detected == 1
    assert result.matched == 0
    assert result.new == 1
    assert result.total == 1
    assert int(result) == 1


@pytest.mark.asyncio
async def test_reconcile_result_matched_on_rescan() -> None:
    tenant = uuid.uuid4()
    existing = _existing_row(tenant_id=tenant)
    session = _FakeSession(existing=[existing])
    service = ScanService(
        session=session,
        detector=_FixedDetector([_det(bbox=(12, 12, 52, 52))]),
    )
    result = await service.process_media_item(
        tenant_id=str(tenant),
        media_id=42,
        media_url="http://example.test/42.jpg",
    )
    assert result.detected == 1
    assert result.matched == 1
    assert result.new == 0
    assert result.total == 1
    assert session.added == []


@pytest.mark.asyncio
async def test_reconcile_result_mixed_matched_and_new() -> None:
    tenant = uuid.uuid4()
    existing = _existing_row(tenant_id=tenant, bbox=(10, 10, 50, 50))
    session = _FakeSession(existing=[existing])
    dets = [
        _det(bbox=(12, 12, 52, 52)),  # IoU match
        _det(bbox=(200, 200, 240, 240)),  # new
    ]
    service = ScanService(session=session, detector=_FixedDetector(dets))
    result = await service.process_media_item(
        tenant_id=str(tenant),
        media_id=42,
        media_url="http://example.test/42.jpg",
    )
    assert result.detected == 2
    assert result.matched == 1
    assert result.new == 1
    assert result.total == 2


@pytest.mark.asyncio
async def test_embedding_length_guard_names_dims() -> None:
    session = _FakeSession()
    wrong = _det(emb_dim=max(1, _DIM - 1))
    service = ScanService(session=session, detector=_FixedDetector([wrong]))
    with pytest.raises(ValueError, match=rf"embedding length {_DIM - 1} != pgvector_dimension {_DIM}"):
        await service.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=99,
            media_url="http://example.test/99.jpg",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["insightface", "face_pipeline"])
async def test_wide_event_shape_both_profiles(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    monkeypatch.setattr(
        "recognition.application.scan.service._face_pipeline_profile",
        lambda: profile,
    )
    session = _FakeSession()
    model_id = "stub-detector@test"
    service = ScanService(session=session, detector=_FixedDetector([_det(model_id=model_id)]))
    corr = generate_correlation_id()
    token = _correlation_id_var.set(corr)
    tenant = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    try:
        with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
            await service.process_media_item(
                tenant_id=tenant,
                media_id=42,
                media_url="http://example.test/42.jpg",
                job_id=job_id,
            )
    finally:
        _correlation_id_var.reset(token)

    records = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"]
    assert len(records) == 1
    rec = records[0]
    assert rec.getMessage() == "scan_media_reconciled"
    assert rec.media_id == 42
    assert rec.tenant_id == tenant
    assert rec.job_id == job_id
    assert rec.correlation_id == corr
    assert rec.detected == 1
    assert rec.matched == 0
    assert rec.new == 1
    assert rec.embedding_model == model_id
    assert rec.profile == profile
    assert isinstance(rec.duration_ms, (int, float))
    assert rec.duration_ms >= 0


@pytest.mark.asyncio
async def test_process_media_item_emits_one_event(caplog: pytest.LogCaptureFixture) -> None:
    session = _FakeSession()
    service = ScanService(session=session, detector=_FixedDetector([_det()]))
    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await service.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=1,
            media_url="http://example.test/1.jpg",
        )
    assert sum(1 for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled") == 1


@pytest.mark.asyncio
async def test_save_job_results_emits_one_event_per_media(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP / inline path: save_job_results emits one wide event per media id."""
    job_id = uuid.uuid4()
    tenant = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        status=None,
        processed_media=0,
        identities_detected=0,
        completed_at=None,
    )

    class _JobSession(_FakeSession):
        async def get(self, _model, _id):  # noqa: ANN001
            return job

        async def commit(self) -> None:
            return None

    session = _JobSession()
    service = ScanService(session=session, detector=MagicMock(), generator=MagicMock())
    dets = [
        _det(media_id="http://example.test/1.jpg", bbox=(10, 10, 40, 40)),
        _det(media_id="http://example.test/2.jpg", bbox=(10, 10, 40, 40)),
    ]
    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await service.save_job_results(
            job_id=job_id,
            tenant_id=str(tenant),
            media_ids=["1", "2"],
            media_sources=["http://example.test/1.jpg", "http://example.test/2.jpg"],
            detections=dets,
        )
    events = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"]
    assert len(events) == 2
    assert job.identities_detected == 2


@pytest.mark.asyncio
async def test_worker_handler_emits_one_event_and_updates_counters(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker path: handler process_media_item → one event + counter record."""
    from recognition.application.scan.queue_repository import ScanQueueItem
    from recognition.domain.job import JobStatus
    from recognition.worker.handlers.scan import ScanItemHandler

    tenant = uuid.uuid4()
    job_id = uuid.uuid4()
    item_id = uuid.uuid4()
    item = ScanQueueItem(
        id=item_id,
        job_id=job_id,
        tenant_id=tenant,
        media_id=7,
        media_url="http://example.test/7.jpg",
        status=JobStatus.RUNNING,
        attempts=1,
        identities_detected=0,
        last_error=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        correlation_id="corr-worker-1",
        correlation_source=None,
    )

    completed: dict[str, object] = {}

    class _Repo:
        async def mark_item_completed(self, *, item_id, completed_at, identities_detected):  # noqa: ANN001
            completed["item_id"] = item_id
            completed["identities_detected"] = identities_detected

        async def release_item_for_retry(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("should not retry")

        async def mark_item_failed(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("should not fail")

    class _SessionCtx(_FakeSession):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            return None

    session = _SessionCtx()

    class _Factory:
        def __call__(self):
            return session

    counters = ScanWorkerCounters()
    detector = _FixedDetector([_det(media_id="7")])
    handler = ScanItemHandler(
        session_factory=_Factory(),  # type: ignore[arg-type]
        detector=detector,
        generator=MagicMock(),
        max_attempts=3,
        max_concurrency=1,
        counters=counters,
    )

    monkeypatch.setattr(
        "recognition.worker.handlers.scan.enable_rls_bypass",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "recognition.worker.handlers.scan.SqlAlchemyScanQueueRepository",
        lambda _session: _Repo(),
    )
    handler._refresh_job_progress = AsyncMock()  # type: ignore[method-assign]
    handler._build_scan_service = lambda _session: ScanService(  # type: ignore[method-assign]
        session=session,
        detector=detector,
        generator=MagicMock(),
    )

    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await handler.process_items(claimed=[item])

    events = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"]
    assert len(events) == 1
    assert completed["identities_detected"] == 1
    assert counters.media_processed == 1
    assert counters.faces_detected == 1
    assert counters.rows_matched == 0
    assert counters.rows_new == 1


def test_capability_reason_always_includes_zero_counters() -> None:
    reason = format_capability_reason(profile="insightface")
    assert reason.startswith("profile=insightface")
    assert "media_processed=0" in reason
    assert "faces_detected=0" in reason
    assert "rows_matched=0" in reason
    assert "rows_new=0" in reason


def test_scan_worker_counters_record_cumulative() -> None:
    c = ScanWorkerCounters()
    c.record(detected=2, matched=1, new=1)
    c.record(detected=0, matched=0, new=0)
    assert c.media_processed == 2
    assert c.faces_detected == 2
    assert c.rows_matched == 1
    assert c.rows_new == 1
    assert "media_processed=2" in c.format_suffix()

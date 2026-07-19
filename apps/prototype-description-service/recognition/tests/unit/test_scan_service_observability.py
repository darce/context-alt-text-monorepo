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
        self.commit_calls = 0
        self.rollback_calls = 0

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

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        # The worker drops staged identity work via session.rollback() before any
        # failure-status write (scan.py failure path, LOCAL47C-03); the fake must
        # model it or the retry-release path is never reached.
        self.rollback_calls += 1


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
            # Worker path: flush-only until caller commit, then emit (S4CR-03).
            await session.commit()
            service.emit_pending_scan_media_reconciled()
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
    # Worker path: detect + persist scoped honestly (S4CR-01).
    assert isinstance(rec.persist_ms, (int, float))
    assert rec.persist_ms >= 0
    assert isinstance(rec.detect_ms, (int, float))
    assert rec.detect_ms >= 0
    assert getattr(rec, "duration_ms", None) is None
    assert session.commit_calls >= 1


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
        # No event until after durable commit boundary.
        assert sum(1 for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled") == 0
        await session.commit()
        service.emit_pending_scan_media_reconciled()
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
    for rec in events:
        assert isinstance(rec.persist_ms, (int, float))
        assert rec.persist_ms >= 0
        # Detect is out of scope on save_job_results — do not fake detect_ms.
        assert not hasattr(rec, "detect_ms")


@pytest.mark.asyncio
async def test_save_job_results_zero_detection_media_emits_detected_zero(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S4CR-02: media with no faces still run _persist_identities + emit detected=0."""
    job_id = uuid.uuid4()
    tenant = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        status=None,
        processed_media=0,
        identities_detected=0,
        completed_at=None,
    )
    existing_m2 = _existing_row(tenant_id=tenant)
    existing_m2.media_id = 2

    class _JobSession(_FakeSession):
        async def get(self, _model, _id):  # noqa: ANN001
            return job

    # Empty dets orphan-clean existing rows (verified on a single-media job).
    session_orphan = _JobSession(existing=[existing_m2])
    service_orphan = ScanService(session=session_orphan, detector=MagicMock(), generator=MagicMock())
    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await service_orphan.save_job_results(
            job_id=job_id,
            tenant_id=str(tenant),
            media_ids=["2"],
            media_sources=["http://example.test/2.jpg"],
            detections=[],
        )
    assert existing_m2 in session_orphan.deleted
    orphan_events = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"]
    assert len(orphan_events) == 1
    assert orphan_events[0].media_id == 2
    assert orphan_events[0].detected == 0
    assert orphan_events[0].matched == 0
    assert orphan_events[0].new == 0

    # Mixed job: media 1 has faces, media 2 has zero detections → two events.
    caplog.clear()
    session_mixed = _JobSession()
    service_mixed = ScanService(session=session_mixed, detector=MagicMock(), generator=MagicMock())
    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await service_mixed.save_job_results(
            job_id=job_id,
            tenant_id=str(tenant),
            media_ids=["1", "2"],
            media_sources=["http://example.test/1.jpg", "http://example.test/2.jpg"],
            detections=[_det(media_id="http://example.test/1.jpg", bbox=(10, 10, 40, 40))],
        )
    mixed = {r.media_id: r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"}
    assert set(mixed) == {1, 2}
    assert mixed[1].detected == 1
    assert mixed[2].detected == 0
    assert mixed[2].matched == 0
    assert mixed[2].new == 0


@pytest.mark.asyncio
async def test_save_job_results_no_events_when_later_media_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S4CR-03: batch failure before commit emits zero events for earlier media."""
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

    session = _JobSession()
    service = ScanService(session=session, detector=MagicMock(), generator=MagicMock())
    dets = [
        _det(media_id="http://example.test/1.jpg", bbox=(10, 10, 40, 40)),
        _det(
            media_id="http://example.test/2.jpg",
            bbox=(10, 10, 40, 40),
            emb_dim=max(1, _DIM - 1),
        ),
    ]
    with (
        caplog.at_level(logging.INFO, logger="recognition.application.scan.service"),
        pytest.raises(ValueError, match=r"embedding length"),
    ):
        await service.save_job_results(
            job_id=job_id,
            tenant_id=str(tenant),
            media_ids=["1", "2"],
            media_sources=["http://example.test/1.jpg", "http://example.test/2.jpg"],
            detections=dets,
        )
    events = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"]
    assert events == []
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_no_event_when_detect_or_persist_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """S4CR-05: detect/persist exceptions emit no scan_media_reconciled (worker + inline)."""

    class _BoomDetector(FaceDetectorProtocol):
        async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
            raise RuntimeError("detect boom")

    session = _FakeSession()
    service = ScanService(session=session, detector=_BoomDetector())
    with (
        caplog.at_level(logging.INFO, logger="recognition.application.scan.service"),
        pytest.raises(RuntimeError, match="detect boom"),
    ):
        await service.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=1,
            media_url="http://example.test/1.jpg",
        )
    assert [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"] == []

    # Persist-path raise (wrong-dim embedding) on process_media_item.
    session2 = _FakeSession()
    service2 = ScanService(
        session=session2,
        detector=_FixedDetector([_det(emb_dim=max(1, _DIM - 1))]),
    )
    with (
        caplog.at_level(logging.INFO, logger="recognition.application.scan.service"),
        pytest.raises(ValueError, match=r"embedding length"),
    ):
        await service2.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=2,
            media_url="http://example.test/2.jpg",
        )
    assert [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"] == []

    # Inline save_job_results raise.
    job_id = uuid.uuid4()
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

    session3 = _JobSession()
    service3 = ScanService(session=session3, detector=MagicMock(), generator=MagicMock())
    with (
        caplog.at_level(logging.INFO, logger="recognition.application.scan.service"),
        pytest.raises(ValueError, match=r"embedding length"),
    ):
        await service3.save_job_results(
            job_id=job_id,
            tenant_id=str(uuid.uuid4()),
            media_ids=["3"],
            media_sources=["http://example.test/3.jpg"],
            detections=[_det(media_id="http://example.test/3.jpg", emb_dim=max(1, _DIM - 1))],
        )
    assert [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"] == []


@pytest.mark.asyncio
async def test_emit_failure_does_not_fail_scan(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4CR-06: telemetry exception is swallowed; scan still succeeds."""
    session = _FakeSession()
    service = ScanService(session=session, detector=_FixedDetector([_det()]))
    service._cached_face_pipeline_profile = None

    def _boom_settings(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("settings boom")

    # get_settings is imported inside _face_pipeline_profile from recognition.config
    monkeypatch.setattr("recognition.config.get_settings", _boom_settings)

    with caplog.at_level(logging.ERROR, logger="recognition.application.scan.service"):
        result = await service.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=1,
            media_url="http://example.test/1.jpg",
        )
        await session.commit()
        # Telemetry runs post-commit; failure must not undo scan success.
        service.emit_pending_scan_media_reconciled()
    assert result.total == 1
    assert session.commit_calls >= 1
    assert any("scan_media_reconciled emission failed" in r.getMessage() for r in caplog.records)


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


@pytest.mark.asyncio
async def test_worker_handler_commit_failure_no_event_no_counter_bump(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E-01/06: commit after successful flush fails → no event, no counter, retry."""
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
        media_id=9,
        media_url="http://example.test/9.jpg",
        status=JobStatus.RUNNING,
        attempts=1,
        identities_detected=0,
        last_error=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        correlation_id="corr-worker-fail",
        correlation_source=None,
    )

    released: dict[str, object] = {}

    class _Repo:
        async def mark_item_completed(self, **_kwargs):  # noqa: ANN001
            return None

        async def release_item_for_retry(self, *, item_id, error_message):  # noqa: ANN001
            released["item_id"] = item_id
            released["error_message"] = error_message

        async def mark_item_failed(self, **_kwargs):  # noqa: ANN001
            raise AssertionError("should retry, not permanent fail")

    class _SessionCtx(_FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self._n = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            self._n += 1
            # First commit is the success-path durable gate; fail it. Failure-path
            # commit (retry state) must succeed so the handler finishes cleanly.
            if self._n == 1:
                raise RuntimeError("commit boom after flush")

    session = _SessionCtx()

    class _Factory:
        def __call__(self):
            return session

    counters = ScanWorkerCounters()
    detector = _FixedDetector([_det(media_id="9")])
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
    assert events == []
    assert counters.media_processed == 0
    assert counters.faces_detected == 0
    assert counters.rows_matched == 0
    assert counters.rows_new == 0
    assert released["item_id"] == item_id
    assert "commit boom" in str(released["error_message"])


@pytest.mark.asyncio
async def test_process_media_item_blob_read_ms_on_file_uri(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """E2E-09: file:// ObjectStore path includes blob_read_ms; http omits it."""
    import io

    class _Store:
        def open(self, _uri: str):
            return io.BytesIO(b"fake-image-bytes")

    session = _FakeSession()
    service = ScanService(
        session=session,
        detector=_FixedDetector([_det()]),
        object_store_factory=lambda _tenant: _Store(),  # type: ignore[arg-type,return-value]
    )
    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await service.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=3,
            media_url="file://tenant/job/blob.jpg",
        )
        await session.commit()
        service.emit_pending_scan_media_reconciled()

    records = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled"]
    assert len(records) == 1
    assert isinstance(records[0].blob_read_ms, (int, float))
    assert records[0].blob_read_ms >= 0

    # Non-file path: field absent (scope-honest).
    session2 = _FakeSession()
    service2 = ScanService(session=session2, detector=_FixedDetector([_det()]))
    with caplog.at_level(logging.INFO, logger="recognition.application.scan.service"):
        await service2.process_media_item(
            tenant_id=str(uuid.uuid4()),
            media_id=4,
            media_url="http://example.test/4.jpg",
        )
        await session2.commit()
        service2.emit_pending_scan_media_reconciled()
    http_recs = [r for r in caplog.records if getattr(r, "event", None) == "scan_media_reconciled" and r.media_id == 4]
    assert len(http_recs) == 1
    assert not hasattr(http_recs[0], "blob_read_ms") or getattr(http_recs[0], "blob_read_ms", None) is None


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

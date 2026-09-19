"""I4: identity persist is serialized per (tenant, media) so one face is one row."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from types import SimpleNamespace

import numpy as np
import pytest

from db.settings import get_database_settings
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.scan.service import PersistIntegrityError, ReconcileResult, ScanService

_DB_SETTINGS = get_database_settings()
_DIM = int(_DB_SETTINGS.pgvector_dimension)

_BASE_BBOX = (10, 10, 50, 50)
_JITTER_BBOX = (12, 12, 52, 52)  # <= 2 px on each edge; IoU stays well above 0.5


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
    """In-memory session: live existing rows, no dialect (asyncio lock path)."""

    def __init__(self, existing: list[object] | None = None) -> None:
        self.existing = list(existing or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flush_calls = 0

    async def execute(self, _stmt: object, _params: object = None) -> _FakeResult:
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


class _SnapshotYieldSession(_FakeSession):
    """TOCTOU harness: snapshot existing, then yield so a sibling can also read."""

    async def execute(self, _stmt: object, _params: object = None) -> _FakeResult:
        snapshot = list(self.existing)
        await asyncio.sleep(0)
        return _FakeResult(snapshot)


class _PostgresFakeSession(_FakeSession):
    """Postgres-dialect session that records advisory-lock SQL before selects."""

    def __init__(self, existing: list[object] | None = None) -> None:
        super().__init__(existing)
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.lock_calls: list[tuple[str, dict[str, object]]] = []
        self.execute_kinds: list[str] = []

    def get_bind(self) -> object:
        return self.bind

    async def execute(self, stmt: object, params: object = None) -> _FakeResult:
        sql = str(stmt)
        param_dict = dict(params) if isinstance(params, dict) else {}
        if "pg_advisory_xact_lock" in sql:
            self.execute_kinds.append("lock")
            self.lock_calls.append((sql, param_dict))
            return _FakeResult([])
        self.execute_kinds.append("select")
        return _FakeResult(self.existing)


def _det(
    *,
    bbox: tuple[int, int, int, int] = _BASE_BBOX,
    emb_dim: int | None = None,
) -> FaceDetection:
    return FaceDetection(
        media_id="42",
        bbox=bbox,
        confidence=0.95,
        embedding=_unit_emb(emb_dim),
        model_id="stub-detector@test",
    )


async def _persist(
    session: _FakeSession,
    *,
    tenant_id: str,
    media_id: int = 42,
    bbox: tuple[int, int, int, int] = _BASE_BBOX,
    detector: _FixedDetector | None = None,
) -> ReconcileResult:
    service = ScanService(
        session=session,
        detector=detector or _FixedDetector([_det(bbox=bbox)]),
    )
    return await service.process_media_item(
        tenant_id=tenant_id,
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
    )


@pytest.mark.asyncio
async def test_rescan_with_two_px_bbox_jitter_keeps_row_count_stable() -> None:
    session = _FakeSession()
    tenant = str(uuid.uuid4())
    first = await _persist(session, tenant_id=tenant, bbox=_BASE_BBOX)
    second = await _persist(session, tenant_id=tenant, bbox=_JITTER_BBOX)
    assert first.new == 1
    assert second.matched == 1
    assert second.new == 0
    assert len(session.existing) == 1


@pytest.mark.asyncio
async def test_concurrent_same_media_persist_does_not_duplicate_rows() -> None:
    session = _SnapshotYieldSession()
    tenant = str(uuid.uuid4())
    first, second = await asyncio.wait_for(
        asyncio.gather(
            _persist(session, tenant_id=tenant, bbox=_BASE_BBOX),
            _persist(session, tenant_id=tenant, bbox=_JITTER_BBOX),
        ),
        timeout=2,
    )
    assert {first.total, second.total} == {1}
    assert len(session.existing) == 1
    assert (first.new + second.new) == 1
    assert (first.matched + second.matched) == 1


@pytest.mark.asyncio
async def test_postgres_session_takes_advisory_xact_lock_before_read() -> None:
    session = _PostgresFakeSession()
    tenant = str(uuid.uuid4())
    await _persist(session, tenant_id=tenant, media_id=42)
    assert session.lock_calls, "expected pg_advisory_xact_lock on postgres persist"
    assert session.execute_kinds[0] == "lock"
    assert "select" in session.execute_kinds
    sql, params = session.lock_calls[0]
    assert "pg_advisory_xact_lock" in sql
    assert params["k2"] == 42
    assert isinstance(params["k1"], int)
    assert -(2**31) <= int(params["k1"]) <= 2**31 - 1


@pytest.mark.asyncio
async def test_postgres_advisory_lock_keys_are_stable_per_tenant_media() -> None:
    session = _PostgresFakeSession()
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    await _persist(session, tenant_id=tenant_a, media_id=7)
    await _persist(session, tenant_id=tenant_a, media_id=7)
    await _persist(session, tenant_id=tenant_a, media_id=8)
    await _persist(session, tenant_id=tenant_b, media_id=7)
    keys = [params for _sql, params in session.lock_calls]
    assert keys[0] == keys[1]
    assert keys[0]["k2"] == 7
    assert keys[2]["k2"] == 8
    assert keys[0]["k1"] != keys[3]["k1"]
    assert keys[2]["k1"] == keys[0]["k1"]


@pytest.mark.asyncio
async def test_lock_is_per_tenant_media_not_global() -> None:
    entered_first = asyncio.Event()
    release_first = asyncio.Event()

    class _GateSession(_FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.selects = 0

        async def execute(self, _stmt: object, _params: object = None) -> _FakeResult:
            snapshot = list(self.existing)
            self.selects += 1
            if self.selects == 1:
                entered_first.set()
                await release_first.wait()
            return _FakeResult(snapshot)

    session = _GateSession()
    tenant = str(uuid.uuid4())
    first = asyncio.create_task(_persist(session, tenant_id=tenant, media_id=1))
    await asyncio.wait_for(entered_first.wait(), timeout=1)
    second = await asyncio.wait_for(
        _persist(session, tenant_id=tenant, media_id=2),
        timeout=1,
    )
    assert not first.done()
    assert second.new == 1
    release_first.set()
    first_result = await asyncio.wait_for(first, timeout=1)
    assert first_result.new == 1
    assert len(session.existing) == 2


@pytest.mark.asyncio
async def test_persist_integrity_error_releases_in_process_lock() -> None:
    session = _FakeSession()
    tenant = str(uuid.uuid4())
    with pytest.raises(PersistIntegrityError, match="embedding length"):
        await _persist(
            session,
            tenant_id=tenant,
            detector=_FixedDetector([_det(emb_dim=max(1, _DIM - 1))]),
        )
    result = await asyncio.wait_for(
        _persist(session, tenant_id=tenant, bbox=_BASE_BBOX),
        timeout=1,
    )
    assert result.new == 1
    assert len(session.existing) == 1

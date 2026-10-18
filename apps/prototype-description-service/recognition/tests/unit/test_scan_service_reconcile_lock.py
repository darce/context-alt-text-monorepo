"""I4: identity persist is serialized per (tenant, media) so one face is one row."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from types import SimpleNamespace

import numpy as np
import pytest

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from db.settings import get_database_settings
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.scan.service import (
    PersistIntegrityError,
    ReconcileResult,
    ScanService,
    _IN_PROCESS_PERSIST_LOCKS,
    _media_persist_lock,
)

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


class _SyncTxSession(_FakeSession):
    """Non-Postgres fake that exposes a real Session so lock hold lasts until commit."""

    def __init__(self, sync_session: Session) -> None:
        super().__init__()
        self.sync_session = sync_session
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))


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


def _open_sync_tx_session() -> tuple[_SyncTxSession, Session, object]:
    engine = create_engine("sqlite:///:memory:")
    sync_session = Session(engine)
    return _SyncTxSession(sync_session), sync_session, engine


async def _acquire_media_lock(session: _FakeSession | object, tenant: uuid.UUID, media_id: int) -> None:
    async with _media_persist_lock(session, tenant, media_id):  # type: ignore[arg-type]
        return None


async def _wait_waiters(key: tuple[str, int], expected: int) -> None:
    while True:
        entry = _IN_PROCESS_PERSIST_LOCKS.get(key)
        if entry is not None and entry.waiters == expected:
            return
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_in_process_lock_held_until_root_commit() -> None:
    tenant = uuid.uuid4()
    media_id = 11
    session_a, sync_a, engine_a = _open_sync_tx_session()
    session_b, sync_b, engine_b = _open_sync_tx_session()
    try:
        sync_a.begin()
        first = await _persist(session_a, tenant_id=str(tenant), media_id=media_id)
        assert first.new == 1
        assert sync_a.in_transaction()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_acquire_media_lock(session_b, tenant, media_id), 0.05)
        sync_a.commit()
        await asyncio.wait_for(_acquire_media_lock(session_b, tenant, media_id), 1)
    finally:
        sync_a.close()
        sync_b.close()
        engine_a.dispose()
        engine_b.dispose()


@pytest.mark.asyncio
async def test_in_process_lock_released_on_root_rollback() -> None:
    tenant = uuid.uuid4()
    media_id = 12
    session_a, sync_a, engine_a = _open_sync_tx_session()
    session_b, sync_b, engine_b = _open_sync_tx_session()
    try:
        sync_a.begin()
        await _persist(session_a, tenant_id=str(tenant), media_id=media_id)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_acquire_media_lock(session_b, tenant, media_id), 0.05)
        sync_a.rollback()
        await asyncio.wait_for(_acquire_media_lock(session_b, tenant, media_id), 1)
    finally:
        sync_a.close()
        sync_b.close()
        engine_a.dispose()
        engine_b.dispose()


@pytest.mark.asyncio
async def test_in_process_lock_held_until_async_session_commit() -> None:
    tenant = uuid.uuid4()
    media_id = 13
    engine_a = create_async_engine("sqlite+aiosqlite:///:memory:")
    engine_b = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory_a = async_sessionmaker(engine_a, expire_on_commit=False)
    factory_b = async_sessionmaker(engine_b, expire_on_commit=False)
    try:
        async with factory_a() as session_a, factory_b() as session_b:
            async with session_a.begin():
                async with _media_persist_lock(session_a, tenant, media_id):
                    pass
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(_acquire_media_lock(session_b, tenant, media_id), 0.05)
            await asyncio.wait_for(_acquire_media_lock(session_b, tenant, media_id), 1)
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_in_process_persist_lock_registry_empties_after_distinct_media() -> None:
    _IN_PROCESS_PERSIST_LOCKS.clear()
    session = _FakeSession()
    tenant = str(uuid.uuid4())
    for media_id in range(5):
        await _persist(session, tenant_id=tenant, media_id=media_id)
    assert _IN_PROCESS_PERSIST_LOCKS == {}


@pytest.mark.asyncio
async def test_in_process_persist_lock_entry_survives_until_last_waiter_releases() -> None:
    _IN_PROCESS_PERSIST_LOCKS.clear()
    session = _FakeSession()
    tenant = uuid.uuid4()
    media_id = 99
    key = (str(tenant), media_id)
    first_inside = asyncio.Event()
    release_first = asyncio.Event()
    second_inside = asyncio.Event()
    release_second = asyncio.Event()

    async def _first() -> None:
        async with _media_persist_lock(session, tenant, media_id):
            first_inside.set()
            await release_first.wait()

    async def _second() -> None:
        async with _media_persist_lock(session, tenant, media_id):
            second_inside.set()
            await release_second.wait()

    task_first = asyncio.create_task(_first())
    await asyncio.wait_for(first_inside.wait(), 1)
    task_second = asyncio.create_task(_second())
    await asyncio.sleep(0)
    await asyncio.wait_for(_wait_waiters(key, 2), 1)
    assert key in _IN_PROCESS_PERSIST_LOCKS
    assert _IN_PROCESS_PERSIST_LOCKS[key].waiters == 2
    release_first.set()
    await asyncio.wait_for(second_inside.wait(), 1)
    await asyncio.wait_for(task_first, 1)
    assert key in _IN_PROCESS_PERSIST_LOCKS
    assert _IN_PROCESS_PERSIST_LOCKS[key].waiters == 1
    release_second.set()
    await asyncio.wait_for(task_second, 1)
    assert key not in _IN_PROCESS_PERSIST_LOCKS
    assert _IN_PROCESS_PERSIST_LOCKS == {}

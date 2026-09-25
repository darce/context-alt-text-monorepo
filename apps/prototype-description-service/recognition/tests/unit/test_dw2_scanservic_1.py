from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable
from types import SimpleNamespace

import numpy as np
import pytest

from db.settings import get_database_settings
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.scan.service import ReconcileResult, ScanService

_DIM = int(get_database_settings().pgvector_dimension)
_BASE_BBOX = (10, 10, 50, 50)
_JITTER_BBOX = (12, 12, 52, 52)


def _unit_emb() -> np.ndarray:
    vec = np.zeros(_DIM, dtype=np.float32)
    vec[0] = 1.0
    return vec


class _FixedDetector(FaceDetectorProtocol):
    def __init__(self, bbox: tuple[int, int, int, int]) -> None:
        self._bbox = bbox

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        return [
            FaceDetection(
                media_id="42",
                bbox=self._bbox,
                confidence=0.95,
                embedding=_unit_emb(),
                model_id="stub-detector@test",
            )
        ]


class _Scalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class _PostgresDatabase:
    def __init__(self) -> None:
        self.rows: list[object] = []
        self.advisory_locks: dict[tuple[int, int], asyncio.Lock] = {}


class _PostgresTransactionSession:
    """Postgres-dialect transaction fake with xact locks and commit-visible rows."""

    def __init__(self, database: _PostgresDatabase) -> None:
        self.database = database
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.pending: list[object] = []
        self.flush_calls = 0
        self.lock_requested = asyncio.Event()
        self._held_locks: list[asyncio.Lock] = []

    async def execute(self, stmt: object, params: object = None) -> _Result:
        sql = str(stmt)
        if "pg_advisory_xact_lock" in sql:
            values = dict(params) if isinstance(params, dict) else {}
            key = (int(values["k1"]), int(values["k2"]))
            lock = self.database.advisory_locks.setdefault(key, asyncio.Lock())
            self.lock_requested.set()
            await lock.acquire()
            self._held_locks.append(lock)
            return _Result([])
        return _Result(self.database.rows)

    def add_all(self, rows: list[object]) -> None:
        self.pending.extend(rows)

    async def delete(self, row: object) -> None:
        if row in self.database.rows:
            self.database.rows.remove(row)

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.database.rows.extend(self.pending)
        self.pending.clear()
        self._release_locks()

    async def rollback(self) -> None:
        self.pending.clear()
        self._release_locks()

    def _release_locks(self) -> None:
        for lock in self._held_locks:
            lock.release()
        self._held_locks.clear()


async def _persist(
    session: _PostgresTransactionSession,
    *,
    tenant_id: str,
    bbox: tuple[int, int, int, int],
) -> ReconcileResult:
    service = ScanService(session=session, detector=_FixedDetector(bbox))  # type: ignore[arg-type]
    return await service.process_media_item(
        tenant_id=tenant_id,
        media_id=42,
        media_url="http://example.test/42.jpg",
    )


@pytest.mark.asyncio
async def test_postgres_duplicate_persist_holds_advisory_lock_until_commit() -> None:
    database = _PostgresDatabase()
    session_a = _PostgresTransactionSession(database)
    session_b = _PostgresTransactionSession(database)
    tenant_id = str(uuid.uuid4())
    second_task: asyncio.Task[ReconcileResult] | None = None
    try:
        first = await _persist(session_a, tenant_id=tenant_id, bbox=_BASE_BBOX)
        assert first.new == 1
        assert session_a.flush_calls == 1
        assert len(session_a.pending) == 1
        assert database.rows == []

        second_task = asyncio.create_task(
            _persist(session_b, tenant_id=tenant_id, bbox=_JITTER_BBOX)
        )
        await asyncio.wait_for(session_b.lock_requested.wait(), timeout=1)
        assert not second_task.done(), "second persist must wait for the uncommitted transaction lock"
        assert session_b.pending == []
        assert database.rows == []

        await session_a.commit()
        second = await asyncio.wait_for(second_task, timeout=1)
        assert second.matched == 1
        assert second.new == 0
        await session_b.commit()

        assert len(database.rows) == 1
        assert first.new + second.new == 1
        assert first.matched + second.matched == 1
    finally:
        if second_task is not None:
            if not second_task.done():
                second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        await session_a.rollback()
        await session_b.rollback()

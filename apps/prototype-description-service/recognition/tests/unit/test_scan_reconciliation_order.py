"""Exercise durable scan reconciliation under SQLite's reversed unordered reads.

Detection order is deliberately fixed: this contract concerns existing-row order.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, selectinload

from db.base import Base
from db.models import IdentityCluster, IdentityMember, MediaIdentity, Tenant
from db.models.identity import FaceObservation
from db.settings import get_database_settings
from recognition.application.embedding.detector import FaceDetection
from recognition.application.scan.service import ReconcileResult, ScanService
from recognition.domain.face_evidence import measure_input

_IDS = (uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3))
_MODEL = "reconciliation-order@test"
_DIM = int(get_database_settings().pgvector_dimension)


class _TestSession:
    """Async service seam over a real, thread-free in-memory SQLite session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def execute(self, statement):
        return self.session.execute(statement)

    async def flush(self):
        self.session.flush()

    async def delete(self, row):
        self.session.delete(row)

    async def commit(self):
        self.session.commit()

    async def refresh(self, row):
        self.session.refresh(row)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[model.__table__ for model in (Tenant, FaceObservation, MediaIdentity, IdentityCluster, IdentityMember)],
    )
    try:
        with Session(engine, expire_on_commit=False) as session:
            yield _TestSession(session)
    finally:
        engine.dispose()


def _embedding(index: int) -> np.ndarray:
    vector = np.zeros(_DIM, dtype=np.float32)
    vector[index] = 1.0
    return vector


def _row(tenant_id: uuid.UUID, index: int, x: int) -> MediaIdentity:
    return MediaIdentity(
        id=_IDS[index],
        tenant_id=tenant_id,
        media_id=42,
        media_url="http://example.test/42.jpg",
        bbox_x=x,
        bbox_y=10,
        bbox_width=100,
        bbox_height=100,
        confidence=0.9,
        embedding=_embedding(2).tolist(),
        embedding_model=_MODEL,
    )


def _detection(x: int, index: int, *, skipped: bool = False) -> FaceDetection:
    bbox = (x, 10, x + 100, 110)
    evidence = measure_input(b"fixed rescan input", np.zeros((120, 600, 3), dtype=np.uint8))
    return FaceDetection(
        media_id="42",
        bbox=bbox,
        confidence=0.95,
        embedding=None if skipped else _embedding(index),
        model_id=_MODEL,
        face_evidence=evidence.for_bbox(bbox),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_reads", [False, True], ids=["forward-db", "reverse-db"])
@pytest.mark.parametrize("competing", [True, False], ids=["competing", "unambiguous"])
async def test_existing_row_order_preserves_durable_uuid_detection_mapping(
    db_session, tenant, reverse_reads: bool, competing: bool
) -> None:
    # Both old rows prefer x=12 in the competing case. Whichever runs first
    # claims that detection; both remaining matches still exceed IoU 0.5.
    db_session.add_all([_row(tenant.id, 0, 10), _row(tenant.id, 1, 20 if competing else 300)])
    await db_session.commit()
    await db_session.execute(text(f"PRAGMA reverse_unordered_selects = {int(reverse_reads)}"))
    unordered = select(MediaIdentity.id).where(MediaIdentity.media_id == 42)
    forward_ids = list((await db_session.execute(unordered)).scalars())
    await db_session.execute(text(f"PRAGMA reverse_unordered_selects = {int(not reverse_reads)}"))
    reversed_ids = list((await db_session.execute(unordered)).scalars())
    assert forward_ids == list(reversed(reversed_ids)), "fixture must really permute unordered database results"
    await db_session.execute(text(f"PRAGMA reverse_unordered_selects = {int(reverse_reads)}"))

    detections = [_detection(12, 0), _detection(0 if competing else 302, 1)]
    service = ScanService(session=db_session)
    result = await service._persist_identities_unlocked(tenant_uuid=tenant.id, media_id=42, detections=detections)
    assert result == ReconcileResult(detected=2, matched=2, new=0)
    await db_session.commit()
    db_session.expire_all()
    rows = list(
        (
            await db_session.execute(
                select(MediaIdentity).order_by(MediaIdentity.id).options(selectinload(MediaIdentity.face_observation))
            )
        ).scalars()
    )
    actual = {row.id: (row.bbox_x, tuple(row.embedding)) for row in rows}
    expected = {_IDS[i]: (det.bbox[0], tuple(det.embedding)) for i, det in enumerate(detections)}
    assert actual == expected, "database result order changed the durable UUID/detection mapping"
    for row, detection in zip(rows, detections, strict=True):
        assert row.face_observation_id == row.face_observation.id
        expected_evidence = detection.face_evidence.to_dict()
        expected_evidence["region"] = list(expected_evidence["region"])
        assert row.face_observation.evidence == expected_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse_reads", [False, True], ids=["forward-db", "reverse-db"])
async def test_skipped_match_survives_and_unmatched_old_row_is_deleted(db_session, tenant, reverse_reads) -> None:
    db_session.add_all([_row(tenant.id, 0, 10), _row(tenant.id, 1, 300), _row(tenant.id, 2, 450)])
    await db_session.commit()
    await db_session.execute(text(f"PRAGMA reverse_unordered_selects = {int(reverse_reads)}"))
    service = ScanService(session=db_session)
    result = await service._persist_identities_unlocked(
        tenant_uuid=tenant.id,
        media_id=42,
        detections=[_detection(12, 0, skipped=True), _detection(302, 1), _detection(550, 0, skipped=True)],
    )
    assert result == ReconcileResult(detected=3, matched=1, new=0, skipped=2)
    await db_session.commit()
    db_session.expire_all()
    rows = list((await db_session.execute(select(MediaIdentity).order_by(MediaIdentity.id))).scalars())
    assert [row.id for row in rows] == list(_IDS[:2])
    assert rows[0].bbox_x == 10  # skipped IoU match is retained without a write
    np.testing.assert_array_equal(rows[0].embedding, _embedding(2))
    assert rows[1].bbox_x == 302
    np.testing.assert_array_equal(rows[1].embedding, _embedding(1))

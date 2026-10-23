"""Exact full-raster evidence at the real adapter boundary; no model loading."""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from recognition.infrastructure.embeddings import InsightFaceAdapter


@pytest.mark.asyncio
async def test_detection_measures_exact_input_and_full_inference_raster(monkeypatch):
    loop = asyncio.get_running_loop()

    def inline_executor(_executor, function, value):
        future = loop.create_future()
        future.set_result(function(value))
        return future

    monkeypatch.setattr(loop, "run_in_executor", inline_executor)
    adapter = InsightFaceAdapter()
    adapter.ensure_loaded = AsyncMock()
    raster = np.arange(120, dtype=np.uint8).reshape(5, 8, 3)
    adapter._bytes_to_cv2 = lambda data: raster
    faces = [
        SimpleNamespace(bbox=[1, 1, 3, 4], det_score=0.9, normed_embedding=np.ones(512)),
        SimpleNamespace(bbox=[4, 0, 7, 3], det_score=0.8, normed_embedding=np.ones(512)),
    ]
    seen = []
    adapter._app = SimpleNamespace(get=lambda image: (seen.append(image), faces)[1])
    results = await adapter.detect_faces(b"exact fetched bytes")
    assert seen[0] is raster
    assert results[0].face_evidence is not None
    assert results[0].face_evidence.source_sha256 == hashlib.sha256(b"exact fetched bytes").hexdigest()
    assert results[0].face_evidence.raster_sha256 == results[1].face_evidence.raster_sha256
    assert results[0].face_evidence.region != results[1].face_evidence.region
    header = json.dumps(
        {"version": 1, "width": 8, "height": 5, "channels": "BGR", "dtype": "uint8", "order": "C"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    expected = hashlib.sha256(header + b"\n" + raster.tobytes(order="C")).hexdigest()
    assert results[0].face_evidence.raster_sha256 == expected
    raster[4, 7, 0] ^= 1  # outside both face regions
    changed = await adapter.detect_faces(b"exact fetched bytes")
    assert changed[0].face_evidence.raster_sha256 != expected
    assert changed[0].face_evidence.source_sha256 == results[0].face_evidence.source_sha256


@pytest.mark.asyncio
async def test_scan_persists_registry_and_exports_without_retargeting_recycled_uuid():
    import uuid
    from unittest.mock import MagicMock

    from db.models.identity import FaceObservation, MediaIdentity
    from db.settings import get_database_settings
    from recognition.application.embedding.detector import FaceDetection
    from recognition.application.scan.service import ScanService
    from recognition.domain.face_evidence import measure_input
    from recognition.interface_adapters.http.routers.clusters_snapshot import _build_member_responses

    tenant = uuid.uuid4()
    rows = []
    registry = []
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=lambda _: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(rows)))
        ),
        flush=AsyncMock(),
        delete=AsyncMock(),
        add=lambda row: registry.append(row),
        add_all=lambda new: rows.extend(new),
    )
    service = ScanService(session=session, detector=MagicMock())
    raster = np.zeros((10, 12, 3), dtype=np.uint8)
    embedding = np.zeros(get_database_settings().pgvector_dimension, dtype=np.float32)
    embedding[0] = 1

    def detections(source=b"first"):
        evidence = measure_input(source, raster)
        return [
            FaceDetection(
                media_id="42",
                bbox=box,
                confidence=0.9,
                embedding=embedding,
                model_id="test",
                face_evidence=evidence.for_bbox(box),
            )
            for box in [(1, 1, 4, 4), (6, 1, 9, 4)]
        ]

    async def persist(values):
        return await service._persist_identities_unlocked(tenant_uuid=tenant, media_id=42, detections=values)

    await persist(detections())
    assert len(rows) == 2
    assert all(isinstance(row, MediaIdentity) for row in rows)
    for row in rows:
        row.id = uuid.uuid4()  # emulate server defaults during mocked flush
    original_ids = [row.id for row in rows]
    observations = [row.face_observation for row in rows]
    assert len({o.id for o in observations}) == 2
    assert all(isinstance(o, FaceObservation) for o in registry)
    await persist(detections())
    assert [row.face_observation for row in rows] == observations

    def member(row):
        return SimpleNamespace(cluster_id=uuid.uuid4(), similarity=0.9)

    exported = _build_member_responses([(member(row), row) for row in rows])
    assert all(item.face_evidence_v1 is not None for item in exported)
    assert all(item.correspondence_eligible is False for item in exported)
    assert all(item.face_evidence_status == "measured_lifecycle_unavailable" for item in exported)
    # Conflicting current pointers cannot establish a bijection either.
    rows[1].face_observation = observations[0]
    rows[1].face_observation_id = observations[0].id
    await persist(detections())
    assert rows[0].face_observation is None
    # Restore only the fixture's original current view for independent byte control.
    for row, observation in zip(rows, observations, strict=True):
        row.face_observation = observation
        row.face_observation_id = observation.id
    await persist(detections(b"changed bytes same raster"))
    assert [row.id for row in rows] == original_ids
    assert all(row.face_observation.id != old.id for row, old in zip(rows, observations, strict=True))
    assert all(old.evidence["source_sha256"] == hashlib.sha256(b"first").hexdigest() for old in observations)
    duplicated = detections(b"changed bytes same raster")
    duplicated.append(duplicated[0])
    await persist(duplicated)
    assert rows[0].face_observation is None
    assert _build_member_responses([(member(rows[0]), rows[0])])[0].face_evidence_status == "unavailable"
    # Tampered row region cannot export stale registry proof.
    rows[1].bbox_width += 1
    assert _build_member_responses([(member(rows[1]), rows[1])])[0].face_evidence_v1 is None
    rows[1].bbox_width -= 1
    observation = rows[1].face_observation
    observation.evidence = dict(observation.evidence, source_sha256="bad-digest")
    assert _build_member_responses([(member(rows[1]), rows[1])])[0].face_evidence_v1 is None


def test_face_pipeline_measures_before_detection_not_aligned_crop(monkeypatch):
    import threading
    from unittest.mock import MagicMock

    from recognition.domain.face_evidence import measure_input
    from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
    from recognition.infrastructure.face_pipeline._common import RawDetection

    full = np.arange(30 * 40 * 3, dtype=np.uint8).reshape(30, 40, 3)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    monkeypatch.setattr(fpa, "decode_image_bytes", lambda data: full)
    raw = RawDetection(
        bbox=np.array([2, 3, 20, 20]),
        score=0.99,
        landmarks=np.array([[5, 5], [15, 5], [10, 10], [5, 15], [15, 15]], dtype=np.float32),
    )
    runtime = SimpleNamespace(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=SimpleNamespace(model_id="mock-pipeline"),
    )
    runtime.detector.detect.return_value = [[raw]]
    runtime.aligner.align.return_value = SimpleNamespace(crop=crop)
    runtime.embedder.embed.return_value = SimpleNamespace(vectors=[np.ones(512)], norms=[1.0])
    detector = fpa.FacePipelineFaceDetector.__new__(fpa.FacePipelineFaceDetector)
    detector._runtime = runtime
    detector._metrics = None
    detector._call_records = threading.local()
    results = detector._detect_sync_impl(b"exact pipeline bytes", "42")
    assert runtime.detector.detect.call_args.args[0][0] is full
    assert len(results) == 1
    proof = results[0].face_evidence
    assert proof.source_sha256 == hashlib.sha256(b"exact pipeline bytes").hexdigest()
    assert proof.raster_sha256 == measure_input(b"exact pipeline bytes", full).raster_sha256
    assert proof.raster_sha256 != measure_input(b"exact pipeline bytes", crop).raster_sha256
    assert proof.region == (2, 3, 20, 20)


def test_registry_binding_is_append_only_on_orm_flush():
    import uuid

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from db.models.identity import FaceObservation
    from recognition.domain.face_evidence import measure_input

    engine = create_engine("sqlite://")
    FaceObservation.__table__.create(engine)
    with Session(engine) as session:
        observation = FaceObservation(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            identity_namespace_id=uuid.uuid4(),
            attachment_id=42,
            evidence=measure_input(b"input", np.zeros((5, 5, 3), dtype=np.uint8)).to_dict(),
        )
        session.add(observation)
        session.commit()
        observation.attachment_id = 99
        with pytest.raises(ValueError, match="face observations are immutable"):
            session.flush()
        session.rollback()
        session.delete(observation)
        with pytest.raises(ValueError, match="face observations are immutable"):
            session.flush()
        session.rollback()
    engine.dispose()


def test_greenfield_schema_protects_registry_and_orders_teardown():
    import importlib.util
    from pathlib import Path
    from unittest.mock import MagicMock

    path = Path(__file__).resolve().parents[3] / "db/migrations/versions/001_identity_schema.py"
    spec = importlib.util.spec_from_file_location("e1_identity_schema", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operation = MagicMock()
    migration.ensure_triggers(operation)
    statements = "\n".join(str(call.args[0]) for call in operation.execute.call_args_list)
    assert "BEFORE UPDATE OR DELETE ON face_observations" in statements
    assert "RAISE EXCEPTION 'face observations are immutable'" in statements
    assert "face_observations" in migration.TENANT_TABLES
    assert "face_observations" in migration.EXPECTED_SCHEMA_TABLES
    assert migration.DOWNGRADE_TABLE_ORDER.index("media_identities") < migration.DOWNGRADE_TABLE_ORDER.index(
        "face_observations"
    )


@pytest.mark.asyncio
async def test_sqlite_scan_duplicate_and_actual_domain_export_seam(request):
    from unittest.mock import MagicMock

    # Use a synchronous in-memory SQL engine under an async service facade.
    # The VM's aiosqlite worker wakeup failed in fixture setup; no SQL seam
    # is mocked here, and real FK/unique constraints and ORM flushes execute.
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session

    from db.base import Base
    from db.models import Tenant
    from db.models.identity import FaceObservation, MediaIdentity
    from db.settings import get_database_settings
    from recognition.application.embedding.detector import FaceDetection
    from recognition.application.scan.service import ScanService
    from recognition.domain.face_evidence import measure_input
    from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository
    from recognition.interface_adapters.http.routers.clusters_snapshot import (
        _build_member_responses,
        _load_snapshot_measurements,
    )

    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[Tenant.__table__, FaceObservation.__table__, MediaIdentity.__table__])
    sql_session = Session(engine)
    request.addfinalizer(engine.dispose)
    request.addfinalizer(sql_session.close)
    tenant = Tenant(site_url="http://example.test")
    sql_session.add(tenant)
    sql_session.commit()
    db_session = SimpleNamespace(
        execute=AsyncMock(side_effect=sql_session.execute),
        flush=AsyncMock(side_effect=sql_session.flush),
        delete=AsyncMock(side_effect=sql_session.delete),
        add=sql_session.add,
        add_all=sql_session.add_all,
    )
    raster = np.zeros((10, 12, 3), dtype=np.uint8)
    embedding = np.zeros(get_database_settings().pgvector_dimension, dtype=np.float32)
    embedding[0] = 1

    def detection(source=b"original"):
        return FaceDetection(
            media_id="42",
            bbox=(1, 1, 4, 4),
            confidence=0.9,
            embedding=embedding,
            model_id="fixture",
            face_evidence=measure_input(source, raster).for_bbox((1, 1, 4, 4)),
        )

    service = ScanService(session=db_session, detector=MagicMock())

    async def persist(values):
        await service._persist_identities_unlocked(tenant_uuid=tenant.id, media_id=42, detections=values)
        await db_session.flush()

    await persist([detection()])
    row = (await db_session.execute(select(MediaIdentity))).scalars().one()
    first_id = row.id
    first_observation = row.face_observation_id
    repository = SqlAlchemyClusterRepository(db_session)
    domain = repository._to_domain_identity(row)
    members = [(SimpleNamespace(cluster_id=str(tenant.id), similarity=0.9), domain)]
    proofs = await _load_snapshot_measurements(db_session, str(tenant.id), members)
    exported = _build_member_responses(members, proofs)
    assert exported[0].face_evidence_v1.observation_id == str(first_observation)
    assert exported[0].image_width == 12
    await persist([detection()])
    assert row.face_observation_id == first_observation
    await persist([detection(b"changed")])
    assert row.id == first_id and row.face_observation_id != first_observation
    await persist([detection(b"changed"), detection(b"changed")])
    assert len((await db_session.execute(select(MediaIdentity))).scalars().all()) == 1
    assert row.face_observation_id is None
    assert len((await db_session.execute(select(FaceObservation))).scalars().all()) == 2
    from dataclasses import replace

    different_size = replace(
        detection(b"changed"), bbox=(1, 1, 5, 5), face_evidence=measure_input(b"changed", raster).for_bbox((1, 1, 5, 5))
    )
    await persist([detection(b"changed"), different_size])
    assert len((await db_session.execute(select(MediaIdentity))).scalars().all()) == 1
    assert row.face_observation_id is None
    proofs = await _load_snapshot_measurements(db_session, str(tenant.id), members)
    assert not proofs
    assert _build_member_responses(members, proofs)[0].face_evidence_status == "unavailable"

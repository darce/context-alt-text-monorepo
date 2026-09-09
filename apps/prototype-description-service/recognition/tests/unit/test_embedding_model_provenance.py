"""FIR-2 S3: embedding_model provenance on media_identities."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import uuid4

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import MediaIdentity
from db.models.tenant import Tenant
from db.settings import get_database_settings
from recognition.application.embedding.detector import (
    FaceDetection,
    FaceDetectorProtocol,
    StubFaceDetector,
)
from recognition.application.embedding.manifest import (
    EmbeddingModelManifest,
    incumbent_embedding_model_manifest,
)
from recognition.application.scan.service import ScanService

_DB_SETTINGS = get_database_settings()


def _unit_embedding() -> list[float]:
    vec = np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32)
    vec[0] = 1.0
    return vec.tolist()


def _expected_incumbent_model_id() -> str:
    """Derive production model_id from the typed manifest (no hardcoding)."""
    return incumbent_embedding_model_manifest().model_id


@pytest.mark.asyncio
async def test_media_identity_insert_without_embedding_model_fails_not_null(db_session, tenant: Tenant) -> None:
    """NOT NULL without DEFAULT: omitting embedding_model must fail closed (RLSE-05)."""
    identity = MediaIdentity(
        id=uuid4(),
        tenant_id=tenant.id,
        media_id=9001,
        media_url="http://example.test/no-provenance.jpg",
        bbox_x=0,
        bbox_y=0,
        bbox_width=10,
        bbox_height=10,
        confidence=0.9,
        embedding=_unit_embedding(),
    )
    db_session.add(identity)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


class _ProvenanceDetector(FaceDetectorProtocol):
    """Detector that stamps FaceDetection.model_id from the embedding manifest."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        detections: list[FaceDetection] = []
        for source in sources:
            if not source:
                continue
            media_ref = source if isinstance(source, str) else "bytes-source"
            emb = np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32)
            emb[0] = 1.0
            detections.append(
                FaceDetection(
                    media_id=str(media_ref),
                    bbox=(10, 20, 40, 60),
                    confidence=0.95,
                    embedding=emb,
                    model_id=self._model_id,
                )
            )
        return detections


@pytest.mark.asyncio
async def test_scan_write_path_populates_embedding_model_from_manifest(db_session, tenant: Tenant) -> None:
    """Scan persist stamps media_identities.embedding_model from det.model_id (manifest)."""
    expected_model_id = _expected_incumbent_model_id()
    service = ScanService(
        session=db_session,
        detector=_ProvenanceDetector(expected_model_id),
    )
    media_id = 4242
    count = await service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
    )
    assert int(count) == 1

    result = await db_session.execute(
        select(MediaIdentity).where(
            MediaIdentity.tenant_id == tenant.id,
            MediaIdentity.media_id == media_id,
        )
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].embedding_model == expected_model_id


def test_incumbent_manifest_model_id_derives_from_fields() -> None:
    """model_id is derived: framework-name@Nd/normalization/metric (framework not in version slot)."""
    manifest = incumbent_embedding_model_manifest()
    assert manifest.model_id == (
        f"{manifest.framework}-{manifest.name}@{manifest.dimensions}d/{manifest.normalization}/{manifest.metric}"
    )
    # Pin the incumbent shape for buffalo_l @ 512 / l2 / cosine, with OpenCV
    # space_token so a warpAffine numeric bump cannot reuse the same model_id
    # (CVUP1-GR-03).
    import cv2

    from recognition.application.embedding.manifest import _opencv_major_minor

    assert manifest.model_id == (
        f"insightface-buffalo_l+cv{_opencv_major_minor(cv2.__version__)}@512d/l2/cosine"
    )
    # framework lives in the left segment, not after '@'
    assert not manifest.model_id.endswith("@insightface")


def test_embedding_model_manifest_model_id_not_hardcoded_string() -> None:
    """Constructed manifests render model_id from fields, not a fixed constant."""
    custom = EmbeddingModelManifest(
        framework="acme",
        name="face_v1",
        dimensions=256,
        normalization="l2",
        metric="cosine",
    )
    assert custom.model_id == "acme-face_v1@256d/l2/cosine"


@pytest.mark.asyncio
async def test_scan_rejects_empty_model_id_before_media_identity_write(db_session, tenant: Tenant) -> None:
    """Empty FaceDetection.model_id is rejected before media_identities insert."""
    service = ScanService(
        session=db_session,
        detector=_ProvenanceDetector(""),
    )
    with pytest.raises(ValueError, match="embedding_model provenance missing on FaceDetection"):
        await service.process_media_item(
            tenant_id=str(tenant.id),
            media_id=4243,
            media_url="http://example.test/4243.jpg",
        )


@pytest.mark.asyncio
async def test_stub_face_detector_stamps_stub_model_id() -> None:
    """StubFaceDetector stamps a stable non-empty model_id on every detection."""
    detector = StubFaceDetector()
    detections = await detector.detect([b"stub-source-bytes"])
    assert len(detections) == 1
    assert detections[0].model_id == "stub-detector@test"


@pytest.mark.asyncio
async def test_scan_write_path_persists_stub_model_id(db_session, tenant: Tenant) -> None:
    """Scan persist path stores stub-detector@test when StubFaceDetector is used.

    StubFaceDetector does not emit embeddings; inject a stub detection that
    carries both an embedding and the stub model_id to pin persistence.
    """
    emb = np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32)
    emb[0] = 1.0

    class _StubIdDetector(FaceDetectorProtocol):
        async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
            return [
                FaceDetection(
                    media_id="stub-media",
                    bbox=(1, 2, 11, 22),
                    confidence=0.99,
                    embedding=emb,
                    model_id="stub-detector@test",
                )
            ]

    service = ScanService(session=db_session, detector=_StubIdDetector())
    media_id = 5252
    count = await service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=media_id,
        media_url=f"http://example.test/{media_id}.jpg",
    )
    assert int(count) == 1

    result = await db_session.execute(
        select(MediaIdentity).where(
            MediaIdentity.tenant_id == tenant.id,
            MediaIdentity.media_id == media_id,
        )
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].embedding_model == "stub-detector@test"

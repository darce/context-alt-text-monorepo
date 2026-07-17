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
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.embedding.manifest import incumbent_embedding_model_manifest
from recognition.application.scan.service import ScanService

_DB_SETTINGS = get_database_settings()


def _unit_embedding() -> list[float]:
    vec = np.zeros(_DB_SETTINGS.pgvector_dimension, dtype=np.float32)
    vec[0] = 1.0
    return vec.tolist()


@pytest.mark.asyncio
async def test_media_identity_insert_without_embedding_model_fails_not_null(
    db_session, tenant: Tenant
) -> None:
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
async def test_scan_write_path_populates_embedding_model_from_manifest(
    db_session, tenant: Tenant
) -> None:
    """Scan persist stamps media_identities.embedding_model from det.model_id (manifest)."""
    expected_model_id = incumbent_embedding_model_manifest().model_id
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
    assert count == 1

    result = await db_session.execute(
        select(MediaIdentity).where(
            MediaIdentity.tenant_id == tenant.id,
            MediaIdentity.media_id == media_id,
        )
    )
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].embedding_model == expected_model_id

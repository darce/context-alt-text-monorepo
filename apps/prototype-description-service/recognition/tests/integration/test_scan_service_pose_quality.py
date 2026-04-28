"""Integration test for scan service pose/landmark persistence."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from sqlalchemy import select

from db.models import MediaIdentity
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.embedding.generator import StubEmbeddingGenerator
from recognition.application.scan.service import ScanService


class PoseDetector(FaceDetectorProtocol):
    """Detector stub that returns pose + landmark quality metadata."""

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        return [
            FaceDetection(
                media_id="media-1",
                bbox=(10, 10, 50, 50),
                confidence=0.95,
                pose_pitch=12.5,
                pose_yaw=-7.5,
                pose_roll=1.5,
                landmark_quality=0.42,
            )
        ]


@pytest.mark.asyncio
async def test_scan_service_persists_pose_and_landmark_quality(db_session, tenant) -> None:
    """ScanService should persist pose angles and landmark quality score."""
    scan_service = ScanService(
        session=db_session,
        detector=PoseDetector(),
        generator=StubEmbeddingGenerator(embedding_dim=512),
    )

    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=123,
        media_url="http://example.test/image.jpg",
    )

    stmt = select(MediaIdentity).where(
        MediaIdentity.tenant_id == tenant.id,
        MediaIdentity.media_id == 123,
    )
    row = (await db_session.execute(stmt)).scalar_one()

    assert row.pose_pitch == pytest.approx(12.5)
    assert row.pose_yaw == pytest.approx(-7.5)
    assert row.pose_roll == pytest.approx(1.5)
    assert row.quality_score == pytest.approx(0.42)


@pytest.mark.asyncio
async def test_scan_service_replay_reuses_existing_media_identity_row(db_session, tenant) -> None:
    """Reprocessing the same media should preserve the existing MediaIdentity row."""
    scan_service = ScanService(
        session=db_session,
        detector=PoseDetector(),
        generator=StubEmbeddingGenerator(embedding_dim=512),
    )

    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=123,
        media_url="http://example.test/image.jpg",
    )

    stmt = select(MediaIdentity).where(
        MediaIdentity.tenant_id == tenant.id,
        MediaIdentity.media_id == 123,
    )
    first_row = (await db_session.execute(stmt)).scalar_one()

    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=123,
        media_url="http://example.test/image.jpg",
    )

    rows = (await db_session.execute(stmt)).scalars().all()

    assert len(rows) == 1
    assert rows[0].id == first_row.id

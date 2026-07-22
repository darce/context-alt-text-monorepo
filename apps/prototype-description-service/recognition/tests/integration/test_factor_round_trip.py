"""FIR-6 S1 mandatory hydration round-trip for quality factors (LC3-04)."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pytest
from sqlalchemy import select

from db.models import MediaIdentity as MediaIdentityModel
from recognition.application.embedding.detector import FaceDetection, FaceDetectorProtocol
from recognition.application.embedding.generator import StubEmbeddingGenerator
from recognition.application.orchestration.clustering.orchestrator import IncrementalClusteringRunner
from recognition.application.scan.service import ScanService
from recognition.infrastructure.repositories.cluster_repository import SqlAlchemyClusterRepository


class FactorDetector(FaceDetectorProtocol):
    """face_pipeline-style detector that emits non-None quality factors."""

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        emb = np.zeros(512, dtype=np.float32)
        emb[0] = 1.0
        return [
            FaceDetection(
                media_id="media-1",
                bbox=(10, 10, 90, 90),
                confidence=0.95,
                embedding=emb,
                pose_pitch=None,
                pose_yaw=5.0,
                pose_roll=-2.0,
                landmark_quality=0.9,
                model_id="sface@face_pipeline",
                sharpness=42.5,
                embedding_norm=3.25,
                occlusion_severity=0.15,
            )
        ]


class InsightfaceStyleDetector(FaceDetectorProtocol):
    """Insightface path: factors remain None."""

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        emb = np.zeros(512, dtype=np.float32)
        emb[0] = 1.0
        return [
            FaceDetection(
                media_id="media-1",
                bbox=(10, 10, 90, 90),
                confidence=0.95,
                embedding=emb,
                model_id="buffalo_l@insightface",
            )
        ]


@pytest.mark.asyncio
async def test_factor_round_trip_via_scan_and_repository(db_session, tenant) -> None:
    """Persist face_pipeline FaceDetection → load via clustering repository hydration."""
    scan_service = ScanService(
        session=db_session,
        detector=FactorDetector(),
        generator=StubEmbeddingGenerator(embedding_dim=512),
    )
    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=4242,
        media_url="http://example.test/factors.jpg",
    )

    row = (
        await db_session.execute(
            select(MediaIdentityModel).where(
                MediaIdentityModel.tenant_id == tenant.id,
                MediaIdentityModel.media_id == 4242,
            )
        )
    ).scalar_one()
    assert row.sharpness == pytest.approx(42.5)
    assert row.embedding_norm == pytest.approx(3.25)
    assert row.occlusion_severity == pytest.approx(0.15)
    assert row.pose_yaw == pytest.approx(5.0)
    assert row.pose_roll == pytest.approx(-2.0)

    repo = SqlAlchemyClusterRepository(db_session)
    domain = repo._to_domain_identity(row)
    assert domain.sharpness == pytest.approx(42.5)
    assert domain.embedding_norm == pytest.approx(3.25)
    assert domain.occlusion_severity == pytest.approx(0.15)

    # Orchestrator hydration mapper must also copy factors (silent-gap killer).
    hydrated = IncrementalClusteringRunner._build_domain_identities([row])
    assert len(hydrated) == 1
    assert hydrated[0].sharpness == pytest.approx(42.5)
    assert hydrated[0].embedding_norm == pytest.approx(3.25)
    assert hydrated[0].occlusion_severity == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_insightface_path_factors_null(db_session, tenant) -> None:
    scan_service = ScanService(
        session=db_session,
        detector=InsightfaceStyleDetector(),
        generator=StubEmbeddingGenerator(embedding_dim=512),
    )
    await scan_service.process_media_item(
        tenant_id=str(tenant.id),
        media_id=4343,
        media_url="http://example.test/insight.jpg",
    )
    row = (
        await db_session.execute(
            select(MediaIdentityModel).where(
                MediaIdentityModel.tenant_id == tenant.id,
                MediaIdentityModel.media_id == 4343,
            )
        )
    ).scalar_one()
    assert row.sharpness is None
    assert row.embedding_norm is None
    assert row.occlusion_severity is None

    domain = SqlAlchemyClusterRepository(db_session)._to_domain_identity(row)
    assert domain.sharpness is None
    assert domain.embedding_norm is None
    assert domain.occlusion_severity is None

"""Tests for scanning media assets and persisting recognition data."""

from __future__ import annotations

import asyncio
from typing import List
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

from db.models import IdentityScanJob, MediaIdentity
from recognition.application.identity_scan_service import IdentityScanService
from recognition.domain.entities import FaceDetection, FaceEmbedding
from recognition.infrastructure.embedding_provider import FaceEmbeddingProvider
from recognition.tests.fakes import DummySession


class DeterministicProvider(FaceEmbeddingProvider):
    """Predictable provider that returns a configurable number of embeddings."""

    def __init__(self, faces_per_media: int = 1) -> None:
        super().__init__()
        self.faces_per_media = faces_per_media

    async def analyze(self, image: Image.Image) -> List[FaceEmbedding]:  # noqa: ARG002
        detections = []
        for idx in range(self.faces_per_media):
            bbox = (idx, idx, idx + 10, idx + 10)
            detection = FaceDetection(bbox=bbox, confidence=0.8)
            detections.append(
                FaceEmbedding(
                    embedding=np.ones(1024, dtype=np.float32),
                    detection=detection,
                )
            )
        return detections


class DummyIdentityScanService(IdentityScanService):
    def __init__(self, session, provider, tenant_id):
        super().__init__(session, provider, tenant_id)
        self._image = Image.new("RGB", (32, 32))

    async def _fetch_image(self, url: str) -> Image.Image:  # noqa: ARG002
        return self._image


class FailingIdentityScanService(DummyIdentityScanService):
    async def _fetch_image(self, url: str) -> Image.Image:  # noqa: ARG002
        raise RuntimeError("network-down")


def _make_job(tenant_id):
    return IdentityScanJob(
        tenant_id=tenant_id,
        status="pending",
        media_ids=[1],
        total_media=1,
    )


def test_scan_identities_persists_data():
    session = DummySession()
    provider = DeterministicProvider(faces_per_media=2)
    service = DummyIdentityScanService(session, provider, uuid4())
    job = _make_job(service.tenant_id)

    media_items = [{"media_id": 1, "media_url": "https://example.com/image.jpg"}]
    asyncio.run(service.scan_identities(job, media_items, user_id=42))

    assert job.status == "completed"
    assert job.identities_detected == 2
    assert job.processed_media == 1
    assert len([obj for obj in session.added if isinstance(obj, MediaIdentity)]) == 2
    assert session.commit_calls == 1


def test_scan_identities_marks_job_failed_on_exception():
    session = DummySession()
    provider = DeterministicProvider()
    service = FailingIdentityScanService(session, provider, uuid4())
    job = _make_job(service.tenant_id)

    media_items = [{"media_id": 1, "media_url": "https://example.com/bad.jpg"}]
    with pytest.raises(RuntimeError):
        asyncio.run(service.scan_identities(job, media_items))

    assert job.status == "failed"
    assert job.error_message == "network-down"
    assert job.completed_at is not None
    assert session.committed


def test_save_identities_normalizes_bbox_dimensions():
    session = DummySession()
    provider = DeterministicProvider()
    service = DummyIdentityScanService(session, provider, uuid4())

    detection = FaceDetection(bbox=(10, 20, 5, 15), confidence=0.6)
    embeddings = [
        FaceEmbedding(
            embedding=np.arange(1024, dtype=np.float32),
            detection=detection,
        )
    ]

    saved = asyncio.run(
        service._save_identities(
            media_id=99,
            media_url="https://example.com/99.jpg",
            embeddings=embeddings,
            created_by_user_id=None,
        )
    )

    assert len(saved) == 1
    assert saved[0].bbox_width == 0
    assert saved[0].bbox_height == 0
    assert saved[0].embedding == embeddings[0].embedding.tolist()


def test_save_identities_skips_existing_bboxes():
    session = DummySession(existing_identity_keys=[(0, 0)])
    provider = DeterministicProvider()
    service = DummyIdentityScanService(session, provider, uuid4())

    detection = FaceDetection(bbox=(0, 0, 10, 10), confidence=0.9)
    embeddings = [FaceEmbedding(embedding=np.arange(1024, dtype=np.float32), detection=detection)]

    saved = asyncio.run(
        service._save_identities(
            media_id=77,
            media_url="https://example.com/77.jpg",
            embeddings=embeddings,
            created_by_user_id=None,
        )
    )

    assert saved == []
    assert not any(isinstance(obj, MediaIdentity) for obj in session.added)


def test_save_identities_skips_duplicates_in_same_batch():
    session = DummySession()
    provider = DeterministicProvider()
    service = DummyIdentityScanService(session, provider, uuid4())

    detection = FaceDetection(bbox=(5, 5, 15, 15), confidence=0.9)
    duplicate_embedding = FaceEmbedding(embedding=np.ones(1024, dtype=np.float32), detection=detection)
    embeddings = [duplicate_embedding, duplicate_embedding]

    saved = asyncio.run(
        service._save_identities(
            media_id=101,
            media_url="https://example.com/101.jpg",
            embeddings=embeddings,
            created_by_user_id=None,
        )
    )

    assert len(saved) == 1
    assert len([obj for obj in session.added if isinstance(obj, MediaIdentity)]) == 1


@pytest.mark.xfail(reason="Pending enforcement of max_identities_per_image from settings")
def test_scan_identities_respects_max_identities_per_image():
    """Future safeguard to prevent runaway detections per asset."""

    session = DummySession()
    provider = DeterministicProvider(faces_per_media=5)
    service = DummyIdentityScanService(session, provider, uuid4())
    job = _make_job(service.tenant_id)

    media_items = [{"media_id": 1, "media_url": "https://example.com/image.jpg"}]
    asyncio.run(service.scan_identities(job, media_items))

    assert job.identities_detected == 2  # expected cap from RecognitionSettings.max_identities_per_image

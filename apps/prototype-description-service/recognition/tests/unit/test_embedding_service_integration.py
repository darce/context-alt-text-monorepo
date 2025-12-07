"""Integration tests for EmbeddingService (Phase 7 TDD item 46)."""

from __future__ import annotations

import uuid

import numpy as np

from recognition.application.embedding.service import EmbeddingService


def test_detect_faces_returns_detections() -> None:
    service = EmbeddingService()
    media_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    detections = service.detect_faces(media_ids)

    assert len(detections) == len(media_ids)
    for det, media_id in zip(detections, media_ids, strict=False):
        assert det.media_id == media_id
        assert det.confidence > 0
        assert det.bbox == (0, 0, 1, 1)


def test_generate_embeddings_returns_1024d_vectors() -> None:
    service = EmbeddingService(embedding_dim=1024)
    detections = service.detect_faces([str(uuid.uuid4())])

    results = service.generate_embeddings(detections)

    assert len(results) == 1
    vec = results[0].embedding
    assert isinstance(vec, np.ndarray)
    assert vec.shape[0] == 1024
    assert abs(np.linalg.norm(vec) - 1.0) < 1e-6


def test_end_to_end_detection_to_identity() -> None:
    service = EmbeddingService()
    detections = service.detect_faces([str(uuid.uuid4()), str(uuid.uuid4())])
    embeddings = service.generate_embeddings(detections)

    identities = service.to_media_identities("tenant-1", embeddings)

    assert len(identities) == len(detections)
    assert all(identity.embedding.shape[0] == 1024 for identity in identities)
    assert all(identity.tenant_id == "tenant-1" for identity in identities)

"""Tests for face-only similarity helpers."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.shared.similarity import (
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    compute_face_similarity,
    extract_face_embedding,
)


def test_extract_face_embedding_1024d() -> None:
    """Should return only the face portion from an extended embedding."""
    extended = np.arange(EXTENDED_EMBEDDING_DIM, dtype=np.float32)
    face = extract_face_embedding(extended)

    assert face.shape[0] == FACE_EMBEDDING_DIM
    assert np.array_equal(face, extended[:FACE_EMBEDDING_DIM])


def test_extract_face_embedding_512d() -> None:
    """Should return the embedding unchanged when already face-only."""
    face_only = np.arange(FACE_EMBEDDING_DIM, dtype=np.float32)
    face = extract_face_embedding(face_only)

    assert face.shape[0] == FACE_EMBEDDING_DIM
    assert np.array_equal(face, face_only)


def test_compute_face_similarity_uses_face_only() -> None:
    """Similarity should ignore metadata dimensions and use normalized face vectors."""
    face = np.ones(FACE_EMBEDDING_DIM, dtype=np.float32)
    embedding_a = np.concatenate([face, np.zeros(FACE_EMBEDDING_DIM, dtype=np.float32)])
    embedding_b = np.concatenate([face, np.ones(FACE_EMBEDDING_DIM, dtype=np.float32) * 10.0])

    similarity = compute_face_similarity(embedding_a, embedding_b)

    assert similarity == pytest.approx(1.0)

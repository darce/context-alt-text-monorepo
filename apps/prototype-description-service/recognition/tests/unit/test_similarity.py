"""Tests for face-only similarity helpers."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.shared.similarity import (
    compute_face_similarity,
    extract_face_embedding,
    face_embedding_dim,
    normalize_face_embedding,
    normalize_vector,
)


def test_extract_face_embedding_truncates_larger_vectors() -> None:
    """Should return only the face portion from a larger embedding vector."""
    larger_dim = face_embedding_dim() + 100
    extended = np.arange(larger_dim, dtype=np.float32)
    face = extract_face_embedding(extended)

    assert face.shape[0] == face_embedding_dim()
    assert np.array_equal(face, extended[: face_embedding_dim()])


def test_extract_face_embedding_512d() -> None:
    """Should return the embedding unchanged when already face-only."""
    face_only = np.arange(face_embedding_dim(), dtype=np.float32)
    face = extract_face_embedding(face_only)

    assert face.shape[0] == face_embedding_dim()
    assert np.array_equal(face, face_only)


def test_compute_face_similarity_uses_face_only() -> None:
    """Similarity should ignore metadata dimensions and use normalized face vectors."""
    face = np.ones(face_embedding_dim(), dtype=np.float32)
    embedding_a = np.concatenate([face, np.zeros(face_embedding_dim(), dtype=np.float32)])
    embedding_b = np.concatenate([face, np.ones(face_embedding_dim(), dtype=np.float32) * 10.0])

    similarity = compute_face_similarity(embedding_a, embedding_b)

    assert similarity == pytest.approx(1.0)


def test_normalize_vector_unit_length() -> None:
    """Should return a unit-length vector."""
    vec = np.array([3.0, 4.0], dtype=np.float32)
    normalized = normalize_vector(vec)

    assert float(np.linalg.norm(normalized)) == pytest.approx(1.0)
    assert np.allclose(normalized, np.array([0.6, 0.8], dtype=np.float32))


def test_normalize_vector_zero_vector() -> None:
    """Should handle zero vector gracefully without division by zero."""
    zero_vec = np.zeros(128, dtype=np.float32)
    normalized = normalize_vector(zero_vec)

    assert np.array_equal(normalized, zero_vec)
    assert float(np.linalg.norm(normalized)) == 0.0


def test_normalize_face_embedding_512d() -> None:
    """Should normalize a 512D face embedding."""
    vec = np.array([10.0] * face_embedding_dim(), dtype=np.float32)
    normalized = normalize_face_embedding(vec)

    assert float(np.linalg.norm(normalized)) == pytest.approx(1.0)
    assert normalized.shape == (face_embedding_dim(),)

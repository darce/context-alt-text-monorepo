"""Tests for MediaIdentity domain model."""

from __future__ import annotations

import numpy as np
import pytest

from recognition.domain.identity import MediaIdentity
from recognition.shared.similarity import face_embedding_dim


def _make_identity(embedding: np.ndarray) -> MediaIdentity:
    """Create a MediaIdentity with the given embedding for testing."""
    return MediaIdentity(
        id="test-id",
        tenant_id="test-tenant",
        media_id="test-media",
        embedding=embedding,
        confidence=0.95,
        bbox_width=100,
        bbox_height=100,
    )


def test_face_vector_returns_normalized_512d() -> None:
    """face_vector should return a unit-length 512D vector."""
    embedding = np.ones(face_embedding_dim(), dtype=np.float32) * 10.0
    identity = _make_identity(embedding)

    face_vec = identity.face_vector

    assert face_vec.shape == (face_embedding_dim(),)
    assert float(np.linalg.norm(face_vec)) == pytest.approx(1.0)


def test_face_vector_extracts_face_portion_from_larger_embedding() -> None:
    """face_vector should extract and normalize only the first 512 dimensions."""
    larger_dim = face_embedding_dim() + 100
    extended = np.arange(larger_dim, dtype=np.float32)
    identity = _make_identity(extended)

    face_vec = identity.face_vector

    # Should only use first 512 dimensions
    assert face_vec.shape == (face_embedding_dim(),)
    # Should be normalized
    assert float(np.linalg.norm(face_vec)) == pytest.approx(1.0)


def test_face_vector_handles_zero_embedding() -> None:
    """face_vector should handle zero embeddings without error."""
    zero_embedding = np.zeros(face_embedding_dim(), dtype=np.float32)
    identity = _make_identity(zero_embedding)

    face_vec = identity.face_vector

    assert face_vec.shape == (face_embedding_dim(),)
    assert np.allclose(face_vec, zero_embedding)


def test_extract_face_embedding_returns_512d() -> None:
    """extract_face_embedding should return only the face portion."""
    larger_dim = face_embedding_dim() + 50
    extended = np.arange(larger_dim, dtype=np.float32)
    identity = _make_identity(extended)

    face_emb = identity.extract_face_embedding()

    assert face_emb.shape == (face_embedding_dim(),)
    assert np.array_equal(face_emb, extended[:face_embedding_dim()])

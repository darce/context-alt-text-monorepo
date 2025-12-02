import numpy as np
import pytest

from recognition.application.clustering.centroid_utils import (
    _normalize_vector,
    compute_centroid,
    compute_similarity,
    update_centroid_incremental,
)


def test_compute_centroid_returns_normalized_centroid():
    embeddings = [
        np.array([10.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 20.0, 0.0], dtype=np.float32),
    ]

    centroid = compute_centroid(embeddings)
    expected = np.array([0.70710677, 0.70710677, 0.0], dtype=np.float32)
    norm = float(np.linalg.norm(centroid))

    assert norm == pytest.approx(1.0, abs=1e-6)
    np.testing.assert_array_almost_equal(centroid, expected, decimal=5)


def test_compute_centroid_raises_for_empty_list():
    with pytest.raises(ValueError):
        compute_centroid([])


def test_update_centroid_incremental_maintains_normalization():
    """Incremental updates should keep centroids normalized."""
    vectors = [
        np.array([5.0, 0.0, 0.0], dtype=np.float32),
        np.array([0.0, 5.0, 0.0], dtype=np.float32),
        np.array([0.0, 0.0, 5.0], dtype=np.float32),
    ]

    old_centroid = compute_centroid(vectors[:2])
    updated = update_centroid_incremental(old_centroid, 2, vectors[2])

    norm = float(np.linalg.norm(updated))
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_compute_similarity_clamps_negative_values():
    similarity = compute_similarity(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        np.array([-1.0, 0.0, 0.0], dtype=np.float32),
    )
    assert similarity == pytest.approx(0.0, abs=1e-6)


def test_compute_similarity_identical_vectors():
    vector = np.ones(4, dtype=np.float32)
    similarity = compute_similarity(vector, vector)
    assert similarity == pytest.approx(1.0, abs=1e-6)


def test_zero_vector_handling():
    zero_vec = np.zeros(512, dtype=np.float32)
    normalized = _normalize_vector(zero_vec)

    np.testing.assert_array_equal(normalized, zero_vec)


class TestMetadataDilutionFix:
    """Tests verifying the fix for the metadata dilution bug.

    The bug: 1024D extended embeddings have metadata (512-1024) that dominates
    the face embedding (0-512) after normalization. This caused false matches
    based on similar pose/age/detection scores rather than actual face identity.

    The fix: compute_similarity() now extracts only the face embedding portion.
    """

    def test_similarity_uses_face_embedding_only(self):
        """Two embeddings with different faces but same metadata should NOT match."""
        # Create two embeddings with DIFFERENT face portions
        emb_a = np.zeros(1024, dtype=np.float32)
        emb_b = np.zeros(1024, dtype=np.float32)

        # Different face embeddings (orthogonal vectors)
        emb_a[:512] = np.random.randn(512).astype(np.float32)
        emb_b[:512] = np.random.randn(512).astype(np.float32)

        # SAME metadata (this would have caused false match before the fix)
        emb_a[512:520] = [0.5, 0.5, 0.5, 0.25, 1.0, 0.95, 0.8, 0.5]
        emb_b[512:520] = [0.5, 0.5, 0.5, 0.25, 1.0, 0.95, 0.8, 0.5]

        similarity = compute_similarity(emb_a, emb_b)

        # Random vectors should have near-zero similarity
        # Before fix: would be high due to identical metadata
        assert similarity < 0.3, f"Expected low similarity for different faces, got {similarity}"

    def test_similarity_high_for_same_face_different_metadata(self):
        """Two embeddings with same face but different metadata SHOULD match."""
        # Create base face embedding
        face = np.random.randn(512).astype(np.float32)
        face = face / np.linalg.norm(face)

        emb_a = np.zeros(1024, dtype=np.float32)
        emb_b = np.zeros(1024, dtype=np.float32)

        # SAME face embedding
        emb_a[:512] = face
        emb_b[:512] = face

        # DIFFERENT metadata (pose, age, etc.)
        emb_a[512:520] = [0.1, 0.2, 0.3, 0.20, 0.5, 0.60, 0.3, 0.1]
        emb_b[512:520] = [0.9, 0.8, 0.7, 0.80, 1.0, 0.99, 0.9, 0.9]

        similarity = compute_similarity(emb_a, emb_b)

        # Same face should have ~1.0 similarity regardless of metadata
        assert similarity > 0.99, f"Expected high similarity for same face, got {similarity}"

    def test_512d_embeddings_still_work(self):
        """Pure 512D face embeddings should work unchanged."""
        face_a = np.random.randn(512).astype(np.float32)
        face_b = face_a.copy()  # Same face

        similarity = compute_similarity(face_a, face_b)
        assert similarity > 0.99, "Expected high similarity for identical 512D vectors"

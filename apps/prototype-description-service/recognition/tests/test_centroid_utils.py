import numpy as np
import pytest

from recognition.application.centroid_utils import (
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

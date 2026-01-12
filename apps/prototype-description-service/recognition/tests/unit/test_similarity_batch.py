import numpy as np
import pytest

from recognition.application.similarity.batch import batch_similarity_matrix


def test_batch_similarity_matrix_returns_expected_values() -> None:
    queries = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
        ],
        dtype=np.float32,
    )
    reps = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
        ],
        dtype=np.float32,
    )

    result = batch_similarity_matrix(queries, reps)

    assert result.shape == (2, 2)
    assert result[0, 0] == pytest.approx(1.0)
    assert result[1, 1] == pytest.approx(1.0)
    assert result[0, 1] == pytest.approx(0.0)

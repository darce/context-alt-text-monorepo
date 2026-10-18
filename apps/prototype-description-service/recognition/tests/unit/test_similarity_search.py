import numpy as np
import pytest

from recognition.application.settings import ClusteringSettings
from recognition.application.similarity import SimilaritySearch


def test_find_best_match_returns_none_for_empty_input() -> None:
    search = SimilaritySearch(ClusteringSettings())
    match = search.find_best_match(np.array([1.0, 0.0], dtype=np.float32), {})
    assert match is None


def test_find_best_match_selects_highest_similarity() -> None:
    search = SimilaritySearch(ClusteringSettings())
    reps = {
        "cluster-a": [np.array([1.0, 0.0], dtype=np.float32)],
        "cluster-b": [np.array([0.0, 1.0], dtype=np.float32)],
    }
    match = search.find_best_match(np.array([1.0, 0.0], dtype=np.float32), reps)
    assert match is not None
    assert match.cluster_id == "cluster-a"
    assert match.similarity == pytest.approx(1.0)


def test_find_all_matches_applies_min_similarity() -> None:
    search = SimilaritySearch(ClusteringSettings())
    reps = {
        "cluster-a": [np.array([1.0, 0.0], dtype=np.float32)],
        "cluster-b": [np.array([0.5, 0.5], dtype=np.float32)],
    }
    matches = search.find_all_matches(np.array([1.0, 0.0], dtype=np.float32), reps, min_similarity=0.9)
    assert [match.cluster_id for match in matches] == ["cluster-a"]


def test_find_all_matches_sorts_by_similarity() -> None:
    search = SimilaritySearch(ClusteringSettings())
    reps = {
        "cluster-a": [np.array([0.6, 0.8], dtype=np.float32)],
        "cluster-b": [np.array([1.0, 0.0], dtype=np.float32)],
    }
    matches = search.find_all_matches(np.array([1.0, 0.0], dtype=np.float32), reps)
    assert [match.cluster_id for match in matches] == ["cluster-b", "cluster-a"]


def test_find_best_matches_returns_match_per_query() -> None:
    class BatchSearch(SimilaritySearch):
        BATCH_THRESHOLD = 1

    search = BatchSearch(ClusteringSettings())
    reps = {
        "cluster-a": [np.array([1.0, 0.0], dtype=np.float32)],
        "cluster-b": [np.array([0.0, 1.0], dtype=np.float32)],
    }
    queries = [
        np.array([1.0, 0.0], dtype=np.float32),
        np.array([0.0, 1.0], dtype=np.float32),
    ]
    matches = search.find_best_matches(queries, reps)
    assert [match.cluster_id if match else None for match in matches] == ["cluster-a", "cluster-b"]


def test_find_best_matches_respects_min_similarity() -> None:
    class BatchSearch(SimilaritySearch):
        BATCH_THRESHOLD = 1

    search = BatchSearch(ClusteringSettings())
    reps = {"cluster-a": [np.array([1.0, 0.0], dtype=np.float32)]}
    queries = [np.array([0.2, 0.98], dtype=np.float32)]
    matches = search.find_best_matches(queries, reps, min_similarity=0.9)
    assert matches == [None]

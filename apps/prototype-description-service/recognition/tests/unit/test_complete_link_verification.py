import numpy as np

from recognition.application.discovery.graph.verification import verify_complete_link


def test_empty_cluster_always_passes() -> None:
    passed, min_sim, coverage = verify_complete_link(np.array([1.0, 0.0], dtype=np.float32), [], min_similarity=0.8)
    assert passed is True
    assert min_sim == 1.0
    assert coverage == 1.0


def test_must_link_all_members() -> None:
    candidate = np.array([1.0, 0.0], dtype=np.float32)
    members = [
        np.array([0.9, 0.1], dtype=np.float32),
        np.array([0.5, 0.5], dtype=np.float32),
    ]
    passed, min_sim, _ = verify_complete_link(candidate, members, min_similarity=0.8)
    assert passed is False
    assert min_sim < 0.8


def test_passes_when_similar_to_all_members() -> None:
    candidate = np.array([1.0, 0.0], dtype=np.float32)
    members = [
        np.array([0.95, 0.05], dtype=np.float32),
        np.array([0.9, 0.1], dtype=np.float32),
    ]
    passed, min_sim, coverage = verify_complete_link(candidate, members, min_similarity=0.7)
    assert passed is True
    assert min_sim >= 0.7
    assert coverage == 1.0

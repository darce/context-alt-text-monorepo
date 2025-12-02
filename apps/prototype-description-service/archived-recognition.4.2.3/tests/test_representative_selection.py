import numpy as np
import pytest

from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.representatives.representative_selection import decide_representative_acceptance


def test_accepts_first_representative():
    config = ClusteringSettings()
    accept, score, diversity = decide_representative_acceptance(
        existing_reps=[],
        candidate_embedding=np.ones(4, dtype=np.float32),
        quality_score=0.9,
        current_media_count=0,
        max_reps_per_media=2,
        min_diversity_similarity=0.85,
        quality_weight=config.quality_weight,
        diversity_weight=config.diversity_weight,
    )

    assert accept is True
    assert diversity == pytest.approx(1.0, rel=1e-6)
    assert score == pytest.approx(0.63, rel=1e-6)


def test_rejects_when_media_cap_reached():
    config = ClusteringSettings()
    accept, score, diversity = decide_representative_acceptance(
        existing_reps=[],
        candidate_embedding=np.ones(4, dtype=np.float32),
        quality_score=0.9,
        current_media_count=2,
        max_reps_per_media=2,
        min_diversity_similarity=0.85,
        quality_weight=config.quality_weight,
        diversity_weight=config.diversity_weight,
    )

    assert accept is False
    assert score == 0.0
    assert diversity == 0.0


def test_rejects_too_similar_to_existing():
    config = ClusteringSettings()
    existing = [np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)]
    candidate = np.array([0.99, 0.01, 0.0, 0.0], dtype=np.float32)

    accept, score, diversity = decide_representative_acceptance(
        existing_reps=existing,
        candidate_embedding=candidate,
        quality_score=0.8,
        current_media_count=0,
        max_reps_per_media=2,
        min_diversity_similarity=0.85,
        quality_weight=config.quality_weight,
        diversity_weight=config.diversity_weight,
    )

    assert accept is False
    assert score == 0.0
    assert diversity > 0.85


def test_accepts_diverse_candidate_and_computes_score():
    config = ClusteringSettings()
    existing = [np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)]
    candidate = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)

    accept, score, diversity = decide_representative_acceptance(
        existing_reps=existing,
        candidate_embedding=candidate,
        quality_score=0.5,
        current_media_count=0,
        max_reps_per_media=2,
        min_diversity_similarity=0.85,
        quality_weight=config.quality_weight,
        diversity_weight=config.diversity_weight,
    )

    assert accept is True
    assert diversity == pytest.approx(0.0, abs=1e-6)
    assert score == pytest.approx(0.65, rel=1e-6)

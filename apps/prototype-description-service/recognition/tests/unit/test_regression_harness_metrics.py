from __future__ import annotations

import pytest

from recognition.application.regression_harness.metrics import compute_curation_cost, compute_pairwise_metrics
from recognition.domain.locator import IdentityLocator


def _loc(n: int) -> IdentityLocator:
    return IdentityLocator(media_id=1, bbox_x=n, bbox_y=n, bbox_width=10, bbox_height=10, crop_hash=None)


def test_pairwise_metrics_basic_case() -> None:
    canonical = {
        _loc(1): "A",
        _loc(2): "A",
        _loc(3): "A",
        _loc(4): "B",
        _loc(5): "B",
        _loc(6): "B",
    }
    predicted = {
        _loc(1): "cluster-1",
        _loc(2): "cluster-1",
        _loc(4): "cluster-1",  # contamination (B in A-majority cluster)
        _loc(3): "cluster-2",  # singleton
        _loc(5): "cluster-3",
        _loc(6): "cluster-3",
        _loc(999): "cluster-extra",  # not in canonical; ignored
    }

    metrics = compute_pairwise_metrics(canonical_labels=canonical, predicted_clusters=predicted)
    assert metrics.evaluated_identities == 6
    assert metrics.ground_truth_pairs == 6  # C(3,2) + C(3,2)
    assert metrics.predicted_pairs == 4  # C(3,2) + C(2,2)
    assert metrics.true_positive_pairs == 2
    assert metrics.precision == pytest.approx(0.5)
    assert metrics.recall == pytest.approx(2 / 6)
    assert metrics.f1 == pytest.approx(0.4)


def test_pairwise_metrics_empty() -> None:
    metrics = compute_pairwise_metrics(canonical_labels={}, predicted_clusters={})
    assert metrics.evaluated_identities == 0
    assert metrics.ground_truth_pairs == 0
    assert metrics.predicted_pairs == 0
    assert metrics.true_positive_pairs == 0
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1 == 0.0


def test_curation_cost_basic_case() -> None:
    canonical = {
        _loc(1): "A",
        _loc(2): "A",
        _loc(3): "A",
        _loc(4): "B",
        _loc(5): "B",
        _loc(6): "B",
    }
    predicted = {
        _loc(1): "cluster-1",
        _loc(2): "cluster-1",
        _loc(4): "cluster-1",
        _loc(3): "cluster-2",
        _loc(5): "cluster-3",
        _loc(6): "cluster-3",
    }

    cost = compute_curation_cost(canonical_labels=canonical, predicted_clusters=predicted)
    assert cost.labels_evaluated == 2
    assert cost.fragmentation_by_label["A"] == 2
    assert cost.fragmentation_by_label["B"] == 2
    assert cost.estimated_merges == 2
    assert cost.estimated_removals == 1
    assert cost.removals_by_label["B"] == 1
    assert cost.removals_by_label["A"] == 0

"""
Regression harness utilities.

This package owns the canonical report builder and scoring functions used to detect clustering regressions over time.
"""

from recognition.application.regression_harness.metrics import compute_curation_cost, compute_pairwise_metrics
from recognition.application.regression_harness.types import CurationCostMetrics, PairwiseMetrics

__all__ = [
    "CurationCostMetrics",
    "PairwiseMetrics",
    "compute_curation_cost",
    "compute_pairwise_metrics",
]

"""
Scoring functions for the clustering regression harness.
"""

from __future__ import annotations

from recognition.application.regression_harness.types import CurationCostMetrics, PairwiseMetrics
from recognition.domain.locator import IdentityLocator


def compute_pairwise_metrics(
    *,
    canonical_labels: dict[IdentityLocator, str],
    predicted_clusters: dict[IdentityLocator, str],
) -> PairwiseMetrics:
    """Compute permutation-invariant pairwise precision/recall/F1.

    Args:
        canonical_labels: Mapping from stable identity locator to canonical label.
        predicted_clusters: Mapping from stable identity locator to predicted cluster identifier.

    Returns:
        PairwiseMetrics: Precision/recall/F1 and supporting counts.
    """
    raise NotImplementedError("TODO: implement compute_pairwise_metrics")


def compute_curation_cost(
    *,
    canonical_labels: dict[IdentityLocator, str],
    predicted_clusters: dict[IdentityLocator, str],
) -> CurationCostMetrics:
    """Estimate curation effort needed to turn predicted clusters into canonical labels.

    Args:
        canonical_labels: Mapping from stable identity locator to canonical label.
        predicted_clusters: Mapping from stable identity locator to predicted cluster identifier.

    Returns:
        CurationCostMetrics: Fragmentation and contamination proxies.
    """
    raise NotImplementedError("TODO: implement compute_curation_cost")

"""
Types used by the regression harness.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PairwiseMetrics:
    """Permutation-invariant pairwise clustering metrics.

    Args:
        evaluated_identities: Number of identities included in the metric computation.
        ground_truth_pairs: Count of same-label identity pairs.
        predicted_pairs: Count of same-cluster identity pairs.
        true_positive_pairs: Count of same-label pairs that were also co-clustered.
        precision: Pairwise precision (TP / predicted_pairs).
        recall: Pairwise recall (TP / ground_truth_pairs).
        f1: Pairwise F1 score.
    """

    evaluated_identities: int
    ground_truth_pairs: int
    predicted_pairs: int
    true_positive_pairs: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class CurationCostMetrics:
    """Estimated curation workload metrics derived from canonical vs predicted assignments.

    Args:
        labels_evaluated: Number of canonical labels included.
        estimated_merges: Sum over labels of (fragmentation - 1), lower-bounded at 0.
        estimated_removals: Count of identities not in the majority label of their predicted cluster.
        fragmentation_by_label: Distinct predicted cluster count per canonical label.
        removals_by_label: Misclustered identity count per canonical label.
    """

    labels_evaluated: int
    estimated_merges: int
    estimated_removals: int
    fragmentation_by_label: dict[str, int]
    removals_by_label: dict[str, int]

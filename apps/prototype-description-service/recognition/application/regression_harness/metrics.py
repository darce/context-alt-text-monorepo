"""
Scoring functions for the clustering regression harness.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from recognition.application.regression_harness.types import CurationCostMetrics, PairwiseMetrics
from recognition.domain.locator import IdentityLocator


def _pair_count(group_size: int) -> int:
    return (group_size * (group_size - 1)) // 2


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
    shared_locators = canonical_labels.keys() & predicted_clusters.keys()
    if not shared_locators:
        return PairwiseMetrics(
            evaluated_identities=0,
            ground_truth_pairs=0,
            predicted_pairs=0,
            true_positive_pairs=0,
            precision=0.0,
            recall=0.0,
            f1=0.0,
        )

    locators = list(shared_locators)

    canonical_by_label: dict[str, list[IdentityLocator]] = defaultdict(list)
    predicted_by_cluster: dict[str, list[IdentityLocator]] = defaultdict(list)
    for locator in locators:
        canonical_by_label[canonical_labels[locator]].append(locator)
        predicted_by_cluster[predicted_clusters[locator]].append(locator)

    ground_truth_pairs = sum(_pair_count(len(members)) for members in canonical_by_label.values())
    predicted_pairs = sum(_pair_count(len(members)) for members in predicted_by_cluster.values())

    true_positive_pairs = 0
    for members in predicted_by_cluster.values():
        label_counts = Counter(canonical_labels[locator] for locator in members)
        true_positive_pairs += sum(_pair_count(count) for count in label_counts.values())

    precision = (true_positive_pairs / predicted_pairs) if predicted_pairs else 0.0
    recall = (true_positive_pairs / ground_truth_pairs) if ground_truth_pairs else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return PairwiseMetrics(
        evaluated_identities=len(locators),
        ground_truth_pairs=ground_truth_pairs,
        predicted_pairs=predicted_pairs,
        true_positive_pairs=true_positive_pairs,
        precision=precision,
        recall=recall,
        f1=f1,
    )


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
    shared_locators = canonical_labels.keys() & predicted_clusters.keys()
    if not shared_locators:
        return CurationCostMetrics(
            labels_evaluated=0,
            estimated_merges=0,
            estimated_removals=0,
            fragmentation_by_label={},
            removals_by_label={},
        )

    locators = list(shared_locators)
    labels = sorted({canonical_labels[locator] for locator in locators})

    clusters_by_label: dict[str, set[str]] = defaultdict(set)
    members_by_cluster: dict[str, list[IdentityLocator]] = defaultdict(list)
    for locator in locators:
        label = canonical_labels[locator]
        cluster_id = predicted_clusters[locator]
        clusters_by_label[label].add(cluster_id)
        members_by_cluster[cluster_id].append(locator)

    fragmentation_by_label = {label: len(clusters_by_label.get(label, set())) for label in labels}
    estimated_merges = sum(max(0, count - 1) for count in fragmentation_by_label.values())

    removals_by_label = dict.fromkeys(labels, 0)
    estimated_removals = 0
    for members in members_by_cluster.values():
        label_counts = Counter(canonical_labels[locator] for locator in members)
        max_count = max(label_counts.values())
        majority_labels = [label for label, count in label_counts.items() if count == max_count]
        majority_label = sorted(majority_labels)[0]
        for label, count in label_counts.items():
            if label == majority_label:
                continue
            removals_by_label[label] += count
            estimated_removals += count

    return CurationCostMetrics(
        labels_evaluated=len(labels),
        estimated_merges=estimated_merges,
        estimated_removals=estimated_removals,
        fragmentation_by_label=fragmentation_by_label,
        removals_by_label=removals_by_label,
    )

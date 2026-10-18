"""Algorithm selection utilities for graph discovery."""

from __future__ import annotations

import importlib.util
from typing import cast

from recognition.application.discovery.graph.algorithm import GraphAlgorithm
from recognition.application.settings import ClusteringSettings


def describe_algorithm(algorithm: GraphAlgorithm) -> tuple[str, dict[str, object]]:
    class_name = algorithm.__class__.__name__
    label = {
        "HdbscanGraphAlgorithm": "hdbscan",
    }.get(class_name, class_name)
    params: dict[str, object] = {}
    for key, value in vars(algorithm).items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            params[key] = value
    return label, params


def hdbscan_available() -> bool:
    """Check if the optional hdbscan dependency is installed."""
    return importlib.util.find_spec("hdbscan") is not None


def select_algorithm(
    *,
    algorithm: GraphAlgorithm | None,
    settings: ClusteringSettings,
) -> GraphAlgorithm:
    """Choose clustering algorithm based on configuration."""
    if algorithm is not None:
        return algorithm

    if not hdbscan_available():
        raise RuntimeError("GraphDiscovery requires HDBSCAN. Install with: pip install hdbscan")

    import math

    from recognition.infrastructure.clustering import HdbscanGraphAlgorithm

    target_cosine = float(settings.similarity_threshold)
    epsilon = math.sqrt(2.0 * (1.0 - target_cosine))
    return cast(
        GraphAlgorithm,
        HdbscanGraphAlgorithm(
            settings=settings,
            cluster_selection_epsilon=epsilon,
        ),
    )

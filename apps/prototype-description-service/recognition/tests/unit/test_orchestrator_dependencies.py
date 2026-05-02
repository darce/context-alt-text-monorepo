from __future__ import annotations

import inspect
from dataclasses import is_dataclass

from recognition.application.orchestration.clustering.orchestrator import (
    IncrementalClusteringRunner,
    cluster_unclustered_identities,
)


def test_clustering_dependency_groups_are_frozen_dataclasses() -> None:
    from recognition.application.orchestration.clustering.dependencies import (
        ClusteringContext,
        ClusteringDependencies,
        ClusteringRuntimeConfig,
    )

    for cls in (ClusteringDependencies, ClusteringRuntimeConfig, ClusteringContext):
        assert is_dataclass(cls)
        assert cls.__dataclass_params__.frozen is True


def test_cluster_unclustered_identities_uses_grouped_inputs() -> None:
    parameter_names = tuple(inspect.signature(cluster_unclustered_identities).parameters)

    assert parameter_names[:4] == ("session", "dependencies", "runtime_config", "context")
    for removed_name in (
        "gate",
        "representative_discovery",
        "centroid_discovery",
        "graph_discovery",
        "assignment_writer",
        "suggestion_service",
        "merge_suggestion_service",
        "clustering_logger",
        "constrained_hac",
        "hac_settings",
        "progress_callback",
        "commit",
        "session_factory",
    ):
        assert removed_name not in parameter_names


def test_incremental_runner_initializer_uses_grouped_inputs() -> None:
    parameter_names = tuple(
        name for name in inspect.signature(IncrementalClusteringRunner).parameters if name != "self"
    )

    assert parameter_names == ("session", "dependencies", "runtime_config")

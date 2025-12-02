"""Clustering subdomain.

Provides identity clustering functionality including:
- IdentityClusteringService: Main orchestrator for clustering operations
- Batch processing, validation, and job management
- Cluster operations (merge, split, rename)
- Algorithm implementations (Chinese Whispers, HDBSCAN, Hierarchical)
"""

from recognition.application.clustering.chinese_whispers import ChineseWhispersClustering
from recognition.application.clustering.cluster_management import (
    ClusterLabelConflictError,
    ClusterNotFoundError,
)
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.clustering.hdbscan_clustering import HDBSCANClustering
from recognition.application.clustering.hierarchical_clustering import HierarchicalClustering
from recognition.application.clustering.identity_clustering_service import (
    IdentityClusteringService,
)

__all__ = [
    "IdentityClusteringService",
    "ClusteringSettings",
    "ClusterNotFoundError",
    "ClusterLabelConflictError",
    # Clustering algorithms
    "ChineseWhispersClustering",
    "HDBSCANClustering",
    "HierarchicalClustering",
]

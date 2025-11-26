"""Clustering subdomain.

Provides identity clustering functionality including:
- IdentityClusteringService: Main orchestrator for clustering operations
- Batch processing, validation, and job management
- Cluster operations (merge, split, rename)
"""

from recognition.application.clustering.cluster_management import (
    ClusterLabelConflictError,
    ClusterNotFoundError,
)
from recognition.application.clustering.clustering_settings import ClusteringSettings
from recognition.application.clustering.identity_clustering_service import (
    IdentityClusteringService,
)

__all__ = [
    "IdentityClusteringService",
    "ClusteringSettings",
    "ClusterNotFoundError",
    "ClusterLabelConflictError",
]

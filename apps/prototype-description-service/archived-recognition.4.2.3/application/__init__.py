"""Application layer use cases for the recognition service.

Organized into subdomains:
- clustering/: Identity clustering and cluster management
- representatives/: Representative embedding management
- scanning/: Media scanning and identity detection
"""

from recognition.application.clustering import (
    ClusteringSettings,
    ClusterLabelConflictError,
    ClusterNotFoundError,
    IdentityClusteringService,
)
from recognition.application.health import check_health
from recognition.application.scanning import IdentityScanService

__all__ = [
    "IdentityScanService",
    "IdentityClusteringService",
    "ClusteringSettings",
    "ClusterNotFoundError",
    "ClusterLabelConflictError",
    "check_health",
]

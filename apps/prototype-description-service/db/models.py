"""SQLAlchemy models for the prototype description service.

DEPRECATED: This module is maintained for backward compatibility.
Import directly from db.models package instead:

    from db.models import Tenant, MediaIdentity, IdentityCluster, ...

Or import from domain-specific modules:

    from db.models.tenant import Tenant, ApiKey
    from db.models.identity import MediaIdentity, IdentityCluster
    from db.models.jobs import IdentityScanJob, IdentityClusteringJob
    from db.models.observability import RecognitionRun, RecognitionEvent
    from db.models.constraints import IdentitySuggestion, IdentityClusterBlock
"""

# Re-export everything from the new package structure for backward compatibility
from db.models import (
    ApiKey,
    AssignmentDecision,
    ClusterCentroid,
    ClusteringFeedback,
    ClusteringJobReport,
    ClusterMergeSuggestion,
    IdentityCluster,
    IdentityClusterBlock,
    IdentityClusteringJob,
    IdentityClusterRepresentative,
    IdentityConstraint,
    IdentityMember,
    IdentityScanJob,
    IdentityScanJobItem,
    IdentitySuggestion,
    MediaIdentity,
    RecognitionEvent,
    RecognitionRun,
    Tenant,
)

__all__ = [
    "Tenant",
    "ApiKey",
    "MediaIdentity",
    "IdentityCluster",
    "ClusterCentroid",
    "IdentityClusterRepresentative",
    "IdentityMember",
    "IdentityScanJob",
    "IdentityScanJobItem",
    "IdentityClusteringJob",
    "RecognitionRun",
    "RecognitionEvent",
    "ClusteringJobReport",
    "AssignmentDecision",
    "ClusteringFeedback",
    "IdentitySuggestion",
    "ClusterMergeSuggestion",
    "IdentityClusterBlock",
    "IdentityConstraint",
]

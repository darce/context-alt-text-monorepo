"""SQLAlchemy models for the prototype description service.

This package provides domain-specific model modules:
- tenant: Tenant and ApiKey models
- identity: MediaIdentity, IdentityCluster, and related models
- jobs: IdentityScanJob, IdentityClusteringJob models
- observability: RecognitionRun, RecognitionEvent, and analytics models
- constraints: IdentitySuggestion, IdentityClusterBlock, IdentityConstraint models
"""

from db.models.constraints import (
    ClusterMergeSuggestion,
    IdentityClusterBlock,
    IdentityConstraint,
    IdentitySuggestion,
)
from db.models.identity import (
    ClusterCentroid,
    CurationReplayRecord,
    IdentityCluster,
    IdentityClusterRepresentative,
    IdentityMember,
    MediaIdentity,
)
from db.models.jobs import (
    IdentityClusteringJob,
    IdentityScanJob,
    IdentityScanJobItem,
)
from db.models.observability import (
    AssignmentDecision,
    ClusteringFeedback,
    ClusteringJobReport,
    RecognitionEvent,
    RecognitionRun,
)
from db.models.tenant import ApiKey, Tenant

__all__ = [
    # Tenant
    "Tenant",
    "ApiKey",
    # Identity
    "MediaIdentity",
    "IdentityCluster",
    "CurationReplayRecord",
    "ClusterCentroid",
    "IdentityClusterRepresentative",
    "IdentityMember",
    # Jobs
    "IdentityScanJob",
    "IdentityScanJobItem",
    "IdentityClusteringJob",
    # Observability
    "RecognitionRun",
    "RecognitionEvent",
    "ClusteringJobReport",
    "AssignmentDecision",
    "ClusteringFeedback",
    # Constraints
    "IdentitySuggestion",
    "ClusterMergeSuggestion",
    "IdentityClusterBlock",
    "IdentityConstraint",
]

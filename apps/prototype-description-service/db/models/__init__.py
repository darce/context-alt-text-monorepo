"""SQLAlchemy models for the prototype description service.

This package provides domain-specific model modules:
- tenant: Tenant and ApiKey models
- identity: MediaIdentity, IdentityCluster, and related models
- jobs: IdentityScanJob, IdentityClusteringJob models
- observability: RecognitionRun, RecognitionEvent, and analytics models
- constraints: IdentitySuggestion, IdentityClusterBlock, IdentityConstraint models
"""

from db.models.atlas import (
    AtlasDispositionAction,
    AtlasRunStatus,
    IdentityAtlasPoint,
    IdentityAtlasQueueDisposition,
    IdentityAtlasRun,
)
from db.models.constraints import (
    ClusterMergeSuggestion,
    IdentityClusterBlock,
    IdentityConstraint,
    IdentitySuggestion,
    NameSuggestion,
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
    ExportJob,
    IdentityClusteringJob,
    IdentityScanJob,
    IdentityScanJobItem,
)
from db.models.observability import (
    AssignmentDecision,
    AuditEvent,
    ClusteringFeedback,
    ClusteringJobReport,
    RecognitionEvent,
    RecognitionRun,
)
from db.models.scene import DescribeRun, DescribeRunItem, ImageDescription
from db.models.tenant import ApiKey, DemoInstance, Tenant
from db.models.worker_capability import WorkerCapability

__all__ = [
    # Tenant
    "Tenant",
    "ApiKey",
    "DemoInstance",
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
    "ExportJob",
    # Observability
    "RecognitionRun",
    "RecognitionEvent",
    "AuditEvent",
    "ClusteringJobReport",
    "AssignmentDecision",
    "ClusteringFeedback",
    # Constraints
    "IdentitySuggestion",
    "ClusterMergeSuggestion",
    "NameSuggestion",
    "IdentityClusterBlock",
    "IdentityConstraint",
    # Atlas
    "AtlasRunStatus",
    "AtlasDispositionAction",
    "IdentityAtlasRun",
    "IdentityAtlasPoint",
    "IdentityAtlasQueueDisposition",
    # Scene (image description)
    "ImageDescription",
    "DescribeRun",
    "DescribeRunItem",
    # Worker capability
    "WorkerCapability",
]

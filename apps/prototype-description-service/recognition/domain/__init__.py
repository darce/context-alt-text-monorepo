"""
Domain models for the recognition service rewrite.

NOMENCLATURE: *Identity
=======================
This layer uses *Identity nomenclature (MediaIdentity, IdentityCluster,
ClusterRepresentative) to remain technology-agnostic.

The domain layer has NO knowledge of:
    - InsightFace or any specific detection library
    - How embeddings were generated
    - Face detection algorithms

This allows us to swap the embedding provider (InsightFace → ArcFace,
MediaPipe, YOLO, etc.) without changing any domain logic.

The transformation from infrastructure (Face*) to domain (*Identity) is
performed by the application layer over the embedding adapters in
recognition/application/embedding/ (detector.py, generator.py).

Domain Models:
    - MediaIdentity: A clusterable entity with embedding vector
    - IdentityCluster: A group of related identities
    - ClusterRepresentative: Exemplar identity for cluster matching
    - AssignmentSuggestion: Pending human-review assignment

See Also:
    - recognition/application/embedding/ (detector.py, generator.py — the seam)
"""

from recognition.domain.cluster import IdentityCluster
from recognition.domain.identity import MediaIdentity
from recognition.domain.representative import ClusterRepresentative
from recognition.domain.suggestion import (
    AssignmentSuggestion,
    BulkAcceptResult,
    MergeSuggestion,
    NameSuggestion,
    SuggestionStatus,
)

__all__ = [
    "AssignmentSuggestion",
    "BulkAcceptResult",
    "ClusterRepresentative",
    "IdentityCluster",
    "MergeSuggestion",
    "MediaIdentity",
    "NameSuggestion",
    "SuggestionStatus",
]

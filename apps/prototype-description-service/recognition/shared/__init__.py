"""
Shared utilities for the recognition service.
"""

from recognition.shared.ids import generate_id
from recognition.shared.similarity import (
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    compute_face_similarity,
    extract_face_embedding,
)

__all__ = [
    "EXTENDED_EMBEDDING_DIM",
    "FACE_EMBEDDING_DIM",
    "compute_face_similarity",
    "extract_face_embedding",
    "generate_id",
]

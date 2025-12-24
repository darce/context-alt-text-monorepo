"""
Shared utilities for the recognition service.
"""

from recognition.shared.ids import generate_id, parse_optional_uuid
from recognition.shared.similarity import (
    FACE_EMBEDDING_DIM,
    compute_face_similarity,
    extract_face_embedding,
    normalize_face_embedding,
    normalize_vector,
)

__all__ = [
    "FACE_EMBEDDING_DIM",
    "compute_face_similarity",
    "extract_face_embedding",
    "generate_id",
    "normalize_face_embedding",
    "normalize_vector",
    "parse_optional_uuid",
]

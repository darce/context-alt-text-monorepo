"""
Shared utilities for the recognition service.
"""

from recognition.shared.ids import generate_id, parse_optional_uuid
from recognition.shared.similarity import (
    compute_face_similarity,
    extract_face_embedding,
    face_embedding_dim,
    normalize_face_embedding,
    normalize_vector,
)

__all__ = [
    "compute_face_similarity",
    "extract_face_embedding",
    "face_embedding_dim",
    "generate_id",
    "normalize_face_embedding",
    "normalize_vector",
    "parse_optional_uuid",
]

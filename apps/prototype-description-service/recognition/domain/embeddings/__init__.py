"""Embedding domain utilities.

Pure functions and constants for working with face embeddings.
This module has no external dependencies and can be imported anywhere.
"""

from recognition.domain.embeddings.builder import (
    build_extended_embedding,
    extract_face_embedding,
    prepare_embedding,
)
from recognition.domain.embeddings.layout import (
    AGE_IDX,
    AGE_SCALE,
    BBOX_AREA_IDX,
    BBOX_AREA_SCALE,
    CLOTHING_HIST_DIM,
    CLOTHING_HIST_END,
    CLOTHING_HIST_START,
    DET_SCORE_IDX,
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_DIM,
    FACE_EMBEDDING_END,
    FACE_EMBEDDING_START,
    GENDER_IDX,
    LANDMARK_QUALITY_IDX,
    LANDMARK_STD_SCALE,
    POSE_DIM,
    POSE_END,
    POSE_SCALE,
    POSE_START,
    RESERVED_END,
    RESERVED_START,
    get_face_embedding_slice,
    get_metadata_slice,
    get_pose_slice,
)

__all__ = [
    # Builder functions
    "build_extended_embedding",
    "extract_face_embedding",
    "prepare_embedding",
    # Layout constants
    "EXTENDED_EMBEDDING_DIM",
    "FACE_EMBEDDING_DIM",
    "FACE_EMBEDDING_START",
    "FACE_EMBEDDING_END",
    "POSE_START",
    "POSE_END",
    "POSE_DIM",
    "AGE_IDX",
    "GENDER_IDX",
    "DET_SCORE_IDX",
    "BBOX_AREA_IDX",
    "LANDMARK_QUALITY_IDX",
    "CLOTHING_HIST_START",
    "CLOTHING_HIST_END",
    "CLOTHING_HIST_DIM",
    "RESERVED_START",
    "RESERVED_END",
    "POSE_SCALE",
    "AGE_SCALE",
    "BBOX_AREA_SCALE",
    "LANDMARK_STD_SCALE",
    # Layout helpers
    "get_face_embedding_slice",
    "get_pose_slice",
    "get_metadata_slice",
]

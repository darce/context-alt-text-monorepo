"""Extended embedding domain module.

This module provides the 1024D extended embedding layout and builder utilities
for face recognition. The layout combines the 512D face identity vector from
InsightFace with additional metadata for improved clustering.

See: docs/tasks/4.0/4.2.4/RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

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
    decode_debug_metrics,
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
    "POSE_SCALE",
    "AGE_IDX",
    "AGE_SCALE",
    "GENDER_IDX",
    "DET_SCORE_IDX",
    "BBOX_AREA_IDX",
    "BBOX_AREA_SCALE",
    "LANDMARK_QUALITY_IDX",
    "LANDMARK_STD_SCALE",
    # Layout functions
    "get_face_embedding_slice",
    "get_pose_slice",
    "get_metadata_slice",
    "decode_debug_metrics",
]

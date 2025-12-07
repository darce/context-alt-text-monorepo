"""Extended 1024D Embedding Layout for Face Recognition.

This module defines the layout for extended face embeddings that include
both the face identity vector and metadata attributes.

See: docs/tasks/4.0/4.2.4/RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md

Layout
======

The 1024D embedding is structured as follows:

| Bytes     | Description                              | Normalization      |
|-----------|------------------------------------------|-------------------|
| 0-511     | Face identity embedding (L2 normalized)  | Unit vector       |
| 512-514   | Head pose [pitch, yaw, roll]            | degrees / 90.0    |
| 515       | Age                                      | age / 100.0       |
| 516       | Gender (0=female, 1=male)               | Binary            |
| 517       | Detection score                          | [0.0, 1.0]        |
| 518       | Bbox area                                | area / 50000      |
| 519       | Landmark quality (std of landmarks)      | std / 100.0       |
| 520-615   | Clothing color histogram (96D)           | [RESERVED]        |
| 616-1023  | Reserved for future use                  | Zero-padded       |

Usage
=====

The face identity embedding (bytes 0-511) is the primary vector used for
similarity computation. The metadata fields (512+) are used for:

1. **Confidence Weighting**: det_score and bbox_area inform the adaptive
   threshold calculation.

2. **Filtering**: Pose angles can be used to exclude extreme profile views.

3. **Session Detection**: Color histogram can group photos from the same
   session/event (future).

4. **Debugging**: All metadata is available for inspection during development.
"""

from __future__ import annotations

from typing import TypedDict


class PoseMetrics(TypedDict):
    """Pose angles in degrees."""

    pitch: float
    yaw: float
    roll: float


class DecodedDebugMetrics(TypedDict):
    """Decoded debug metrics from extended embedding."""

    pose: PoseMetrics
    age: float
    gender: str
    det_score: float
    bbox_area: int
    landmark_quality: float


# Slice indices - primary face embedding
FACE_EMBEDDING_START = 0
FACE_EMBEDDING_END = 512
FACE_EMBEDDING_DIM = FACE_EMBEDDING_END - FACE_EMBEDDING_START

# Pose (3 values: pitch, yaw, roll)
POSE_START = 512
POSE_END = 515
POSE_DIM = POSE_END - POSE_START

# Demographics
AGE_IDX = 515
GENDER_IDX = 516

# Detection quality
DET_SCORE_IDX = 517
BBOX_AREA_IDX = 518

# Landmark quality (std deviation of landmark positions)
LANDMARK_QUALITY_IDX = 519

# Clothing color histogram (reserved for future use)
CLOTHING_HIST_START = 520
CLOTHING_HIST_END = 616
CLOTHING_HIST_DIM = CLOTHING_HIST_END - CLOTHING_HIST_START

# Reserved space
RESERVED_START = 616
RESERVED_END = 1024

# Total embedding dimension
EXTENDED_EMBEDDING_DIM = 1024

# Normalization constants
POSE_SCALE = 90.0  # degrees
AGE_SCALE = 100.0
BBOX_AREA_SCALE = 50000.0  # pixels^2
LANDMARK_STD_SCALE = 100.0


def get_face_embedding_slice() -> slice:
    """Return slice for extracting 512D face embedding."""
    return slice(FACE_EMBEDDING_START, FACE_EMBEDDING_END)


def get_pose_slice() -> slice:
    """Return slice for extracting pose [pitch, yaw, roll]."""
    return slice(POSE_START, POSE_END)


def get_metadata_slice() -> slice:
    """Return slice for all metadata (512-1023)."""
    return slice(FACE_EMBEDDING_END, EXTENDED_EMBEDDING_DIM)


def decode_debug_metrics(embedding: list[float]) -> DecodedDebugMetrics | None:
    """Extract debug metrics from a 1024D extended embedding.

    Returns a dictionary with denormalized InsightFace attributes:
    - pose: {pitch, yaw, roll} in degrees
    - age: estimated age (0-100)
    - gender: 'female' or 'male'
    - det_score: detection confidence [0.0, 1.0]
    - bbox_area: bounding box area in pixels²
    - landmark_quality: landmark position std deviation

    If the embedding is only 512D (legacy), returns None.
    """
    if len(embedding) < EXTENDED_EMBEDDING_DIM:
        return None

    # Denormalize values
    pitch = embedding[POSE_START] * POSE_SCALE
    yaw = embedding[POSE_START + 1] * POSE_SCALE
    roll = embedding[POSE_START + 2] * POSE_SCALE

    age = embedding[AGE_IDX] * AGE_SCALE
    gender_val = embedding[GENDER_IDX]
    det_score = embedding[DET_SCORE_IDX]
    bbox_area = embedding[BBOX_AREA_IDX] * BBOX_AREA_SCALE
    landmark_quality = embedding[LANDMARK_QUALITY_IDX] * LANDMARK_STD_SCALE

    return {
        "pose": {
            "pitch": round(pitch, 1),
            "yaw": round(yaw, 1),
            "roll": round(roll, 1),
        },
        "age": round(age, 1),
        "gender": "female" if gender_val < 0.5 else "male",
        "det_score": round(det_score, 3),
        "bbox_area": round(bbox_area),
        "landmark_quality": round(landmark_quality, 2),
    }


__all__ = [
    # Constants
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
    # Types
    "PoseMetrics",
    "DecodedDebugMetrics",
    # Functions
    "get_face_embedding_slice",
    "get_pose_slice",
    "get_metadata_slice",
    "decode_debug_metrics",
]

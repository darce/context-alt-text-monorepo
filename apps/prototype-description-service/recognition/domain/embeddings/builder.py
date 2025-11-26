"""Extended embedding builder utilities.

This module provides functions to build 1024D extended embeddings
from face detection results and metadata.

See: docs/tasks/4.0/4.2.3/clustering-improvements-dev-plan.md (Slice B)
"""

from __future__ import annotations

import numpy as np

from recognition.domain.embeddings.layout import (
    AGE_IDX,
    AGE_SCALE,
    BBOX_AREA_IDX,
    BBOX_AREA_SCALE,
    DET_SCORE_IDX,
    EXTENDED_EMBEDDING_DIM,
    FACE_EMBEDDING_END,
    FACE_EMBEDDING_START,
    GENDER_IDX,
    LANDMARK_QUALITY_IDX,
    LANDMARK_STD_SCALE,
    POSE_SCALE,
    POSE_START,
)


def _normalize(vector: np.ndarray) -> np.ndarray:
    """L2 normalize a vector."""
    norm = float(np.linalg.norm(vector))
    if norm < 1e-10:
        return vector
    result: np.ndarray = vector / norm
    return result


def build_extended_embedding(
    face_embedding: np.ndarray,
    det_score: float,
    bbox: tuple[int, int, int, int],
    pose: tuple[float, float, float] | None = None,
    age: int | None = None,
    gender: int | None = None,
    landmarks: np.ndarray | None = None,
) -> np.ndarray:
    """
    Build 1024D extended embedding with face identity + metadata.

    Args:
        face_embedding: 512D face identity embedding from InsightFace
        det_score: Detection confidence [0, 1]
        bbox: Bounding box [x1, y1, x2, y2]
        pose: Head pose [pitch, yaw, roll] in degrees (optional)
        age: Estimated age (optional)
        gender: Gender prediction 0=female, 1=male (optional)
        landmarks: Facial landmarks array (optional)

    Returns:
        1024D extended embedding as float32 array

    Example:
        >>> face_emb = detector.get_embedding(image, face)
        >>> extended = build_extended_embedding(
        ...     face_embedding=face_emb,
        ...     det_score=0.95,
        ...     bbox=(100, 100, 300, 400),
        ...     pose=(10.0, -5.0, 2.0),
        ...     age=35,
        ... )
        >>> extended.shape
        (1024,)
    """
    embedding = np.zeros(EXTENDED_EMBEDDING_DIM, dtype=np.float32)

    # Face embedding (normalized)
    normalized_face = _normalize(face_embedding.astype(np.float32))
    embedding[FACE_EMBEDDING_START:FACE_EMBEDDING_END] = normalized_face

    # Head pose (normalized by 90 degrees)
    if pose is not None:
        embedding[POSE_START] = pose[0] / POSE_SCALE  # pitch
        embedding[POSE_START + 1] = pose[1] / POSE_SCALE  # yaw
        embedding[POSE_START + 2] = pose[2] / POSE_SCALE  # roll

    # Demographics
    if age is not None:
        embedding[AGE_IDX] = age / AGE_SCALE

    if gender is not None:
        embedding[GENDER_IDX] = float(gender)

    # Detection quality
    embedding[DET_SCORE_IDX] = det_score

    # Bbox area (clamped to 1.0)
    x1, y1, x2, y2 = bbox
    bbox_area = (x2 - x1) * (y2 - y1)
    embedding[BBOX_AREA_IDX] = min(1.0, bbox_area / BBOX_AREA_SCALE)

    # Landmark quality (std of flattened landmarks)
    if landmarks is not None:
        landmark_std = np.std(landmarks.flatten())
        embedding[LANDMARK_QUALITY_IDX] = landmark_std / LANDMARK_STD_SCALE

    return embedding


def extract_face_embedding(embedding: np.ndarray) -> np.ndarray:
    """
    Extract 512D face identity embedding from extended embedding.

    Args:
        embedding: Extended 1024D embedding

    Returns:
        512D face identity embedding

    Example:
        >>> extended = load_extended_embedding()  # 1024D
        >>> face_only = extract_face_embedding(extended)
        >>> face_only.shape
        (512,)
    """
    return embedding[FACE_EMBEDDING_START:FACE_EMBEDDING_END].copy()


def prepare_embedding(
    embedding: list[float] | np.ndarray,
    normalize: bool = True,
) -> np.ndarray:
    """
    Prepare an embedding for clustering operations.

    Converts to numpy float32 and optionally normalizes.
    This is the standard way to prepare embeddings loaded from database.

    Args:
        embedding: Input embedding (1024D, list or array)
        normalize: Whether to L2 normalize the result (default True)

    Returns:
        1024D float32 numpy array, optionally normalized

    Example:
        >>> db_embedding = identity.embedding  # from database
        >>> vec = prepare_embedding(db_embedding)
        >>> vec.shape
        (1024,)
    """
    vec = np.array(embedding, dtype=np.float32)
    if normalize:
        vec = _normalize(vec)
    return vec

"""Five-point affine face alignment matching OpenCV FaceRecognizerSF.alignCrop.

FIR-3 S2 reference preprocessing. Pure function of (image, 5 landmarks) →
112×112 BGR crop + 2×3 affine matrix. Landmark order bugs silently poison
every embedding (rg-015).

Landmark ORDER contract (YuNet / FaceDetectorYN face_box indices 4..13):
  0: right eye   (anatomical right = left side of a frontal image)
  1: left eye
  2: nose tip
  3: right mouth corner
  4: left mouth corner

These map 1:1 onto OpenCV SFace canonical targets (same order as
``getSimilarityTransformMatrix`` in opencv ``face_recognize.cpp``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import cv2
import numpy as np

# OpenCV FaceRecognizerSF canonical targets for 112×112 SFace crops.
# Source: opencv modules/objdetect/src/face_recognize.cpp (4.x).
SFACE_CANONICAL_LANDMARKS_112: Final[np.ndarray] = np.array(
    [
        [38.2946, 51.6963],  # right eye
        [73.5318, 51.5014],  # left eye
        [56.0252, 71.7366],  # nose tip
        [41.5493, 92.3655],  # right mouth corner
        [70.7299, 92.2041],  # left mouth corner
    ],
    dtype=np.float64,
)

# Precomputed mean of SFACE_CANONICAL_LANDMARKS_112 (opencv hard-codes this).
_SFACE_DST_MEAN: Final[tuple[float, float]] = (56.0262, 71.9008)

ALIGNED_SIZE: Final[int] = 112

YUNET_LANDMARK_NAMES: Final[tuple[str, ...]] = (
    "right_eye",
    "left_eye",
    "nose_tip",
    "right_mouth_corner",
    "left_mouth_corner",
)


class AlignmentError(Exception):
    """Raised when five-point alignment cannot produce a valid transform."""


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """112×112 BGR crop plus the 2×3 affine matrix that produced it."""

    crop: np.ndarray  # (112, 112, 3) uint8 BGR
    affine: np.ndarray  # (2, 3) float64


def _as_landmarks5(landmarks: np.ndarray) -> np.ndarray:
    """Validate and return landmarks as float64 (5, 2)."""
    arr = np.asarray(landmarks, dtype=np.float64)
    if arr.shape == (10,):
        arr = arr.reshape(5, 2)
    if arr.shape != (5, 2):
        raise AlignmentError(
            f"expected 5 landmarks as (5, 2) or (10,), got shape {tuple(arr.shape)}; "
            f"order must be {YUNET_LANDMARK_NAMES}"
        )
    if not np.isfinite(arr).all():
        raise AlignmentError("landmarks contain non-finite values")
    return arr


def similarity_transform_matrix(
    src_landmarks: np.ndarray,
    *,
    dst_landmarks: np.ndarray | None = None,
) -> np.ndarray:
    """Umeyama-style similarity transform matching OpenCV FaceRecognizerSF.

    Port of ``FaceRecognizerSFImpl::getSimilarityTransformMatrix`` so ORT
    adapters (S3) can reproduce the same affine without linking cv2.FaceRecognizerSF.
    """
    src = _as_landmarks5(src_landmarks)
    if dst_landmarks is None:
        dst = SFACE_CANONICAL_LANDMARKS_112
        dst_mean = np.array(_SFACE_DST_MEAN, dtype=np.float64)
    else:
        dst = _as_landmarks5(dst_landmarks)
        dst_mean = dst.mean(axis=0)

    src_mean = src.mean(axis=0)
    src_demean = src - src_mean
    dst_demean = dst - dst_mean

    # A = dst_demean.T @ src_demean / 5  (2×2)
    a00 = float(np.dot(dst_demean[:, 0], src_demean[:, 0]) / 5.0)
    a01 = float(np.dot(dst_demean[:, 0], src_demean[:, 1]) / 5.0)
    a10 = float(np.dot(dst_demean[:, 1], src_demean[:, 0]) / 5.0)
    a11 = float(np.dot(dst_demean[:, 1], src_demean[:, 1]) / 5.0)
    a = np.array([[a00, a01], [a10, a11]], dtype=np.float64)

    d = np.array([1.0, 1.0], dtype=np.float64)
    det_a = a00 * a11 - a01 * a10
    if det_a < 0:
        d[1] = -1.0

    u, s, vt = np.linalg.svd(a)
    smax = max(float(s[0]), float(s[1]))
    tol = smax * 2.0 * np.finfo(np.float32).tiny
    rank = int(s[0] > tol) + int(s[1] > tol)

    det_u = float(np.linalg.det(u))
    det_vt = float(np.linalg.det(vt))
    if rank == 1:
        if det_u * det_vt > 0:
            r = u @ vt
        else:
            d1 = d[1]
            d[1] = -1.0
            r = u @ np.diag(d) @ vt
            d[1] = d1
    else:
        r = u @ np.diag(d) @ vt

    var = float(np.sum(src_demean * src_demean) / 5.0)
    if var <= 0.0:
        raise AlignmentError("degenerate landmarks (zero variance); cannot align")
    scale = (s[0] * d[0] + s[1] * d[1]) / var

    t = np.zeros((2, 3), dtype=np.float64)
    t[0, 0] = r[0, 0] * scale
    t[0, 1] = r[0, 1] * scale
    t[1, 0] = r[1, 0] * scale
    t[1, 1] = r[1, 1] * scale
    ts0 = r[0, 0] * src_mean[0] + r[0, 1] * src_mean[1]
    ts1 = r[1, 0] * src_mean[0] + r[1, 1] * src_mean[1]
    t[0, 2] = dst_mean[0] - scale * ts0
    t[1, 2] = dst_mean[1] - scale * ts1
    return t


class FivePointAligner:
    """OpenCV-SFace-compatible five-point affine aligner (112×112 BGR).

    Clarity-first reference implementation. Does not call FaceRecognizerSF;
    uses the same similarity transform + INTER_LINEAR warp as alignCrop.
    """

    def __init__(self, *, output_size: int = ALIGNED_SIZE) -> None:
        if output_size != ALIGNED_SIZE:
            # SFace canonical landmarks are defined for 112 only.
            raise ValueError(
                f"FivePointAligner only supports output_size={ALIGNED_SIZE} (SFace canonical), got {output_size}"
            )
        self.output_size = output_size

    def align(
        self,
        image: np.ndarray,
        landmarks: np.ndarray,
    ) -> AlignmentResult:
        """Align ``image`` using five YuNet-order landmarks.

        Args:
            image: H×W×3 BGR uint8 (or convertible).
            landmarks: (5, 2) or (10,) in YuNet order (see module docstring).

        Returns:
            AlignmentResult with 112×112 BGR crop and 2×3 affine matrix.
        """
        # FIR23-04: single coercion path shared with detect/embed (REF-19).
        from recognition.infrastructure.face_pipeline._common import (
            FacePipelineInputError,
            ensure_bgr_u8,
        )

        try:
            img = ensure_bgr_u8(image, label="align_image")
        except FacePipelineInputError as exc:
            raise AlignmentError(str(exc)) from exc

        affine = similarity_transform_matrix(landmarks)
        crop = cv2.warpAffine(
            img,
            affine,
            (self.output_size, self.output_size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )
        return AlignmentResult(crop=crop, affine=affine)


__all__ = [
    "ALIGNED_SIZE",
    "AlignmentError",
    "AlignmentResult",
    "FivePointAligner",
    "SFACE_CANONICAL_LANDMARKS_112",
    "YUNET_LANDMARK_NAMES",
    "similarity_transform_matrix",
]

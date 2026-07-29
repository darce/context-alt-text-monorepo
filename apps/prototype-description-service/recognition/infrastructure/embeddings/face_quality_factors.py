"""Per-factor face quality signals for the face_pipeline profile (FIR-6 S1).

Computes multi-dimensional factors (CAL-09) from the aligned 112×112 crop and
5-point landmarks. Pure numpy (no cv2 import) so unit tests stay lightweight
and infrastructure adapters stay free of extra heavy deps at import time.

Heuristics: EMB-03 (pre-norm magnitude), CAL-09 (per-factor, no opaque scalar).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# OpenCV SFace canonical eye positions on the aligned 112×112 crop.
_CANONICAL_RIGHT_EYE: tuple[float, float] = (38.2946, 51.6963)
_CANONICAL_LEFT_EYE: tuple[float, float] = (73.5318, 51.5014)
_EYE_PATCH_HALF: int = 8


@dataclass(frozen=True, slots=True)
class FaceQualityFactors:
    """Per-factor quality breakdown for one face detection."""

    sharpness: float
    embedding_norm: float
    occlusion_severity: float  # [0, 1]
    pose_yaw: float | None
    pose_roll: float | None


def _as_gray_u8(crop_bgr: np.ndarray) -> np.ndarray:
    arr = np.asarray(crop_bgr)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"expected HxWx3 BGR crop, got shape {getattr(arr, 'shape', None)}")
    # ITU-R BT.601 luma approximation (no cv2 dependency).
    b = arr[..., 0].astype(np.float64)
    g = arr[..., 1].astype(np.float64)
    r = arr[..., 2].astype(np.float64)
    gray = 0.114 * b + 0.587 * g + 0.299 * r
    return np.clip(gray, 0, 255).astype(np.float64)


def compute_sharpness(crop_bgr: np.ndarray) -> float:
    """Variance of Laplacian on the aligned crop (higher = sharper)."""
    gray = _as_gray_u8(crop_bgr)
    # 3×3 Laplacian kernel (same topology as cv2.Laplacian default).
    kernel = np.array([[0.0, 1.0, 0.0], [1.0, -4.0, 1.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    # Manual convolution via pad + sliding window (scipy optional elsewhere).
    padded = np.pad(gray, 1, mode="edge")
    acc = (
        kernel[0, 1] * padded[:-2, 1:-1]
        + kernel[1, 0] * padded[1:-1, :-2]
        + kernel[1, 1] * padded[1:-1, 1:-1]
        + kernel[1, 2] * padded[1:-1, 2:]
        + kernel[2, 1] * padded[2:, 1:-1]
    )
    return float(np.var(acc))


def _patch_stats(gray: np.ndarray, cx: float, cy: float, half: int = _EYE_PATCH_HALF) -> tuple[float, float]:
    h, w = gray.shape
    x0 = max(0, int(round(cx)) - half)
    x1 = min(w, int(round(cx)) + half)
    y0 = max(0, int(round(cy)) - half)
    y1 = min(h, int(round(cy)) + half)
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0.0
    patch = gray[y0:y1, x0:x1]
    variance = float(np.var(patch))
    # Simple edge energy: mean absolute horizontal+vertical first differences.
    if patch.shape[0] < 2 or patch.shape[1] < 2:
        edge = 0.0
    else:
        edge = float(np.mean(np.abs(np.diff(patch, axis=0)))) + float(np.mean(np.abs(np.diff(patch, axis=1))))
    return variance, edge


def compute_occlusion_severity(crop_bgr: np.ndarray) -> float:
    """Occlusion proxy ∈ [0,1] from per-eye patch stats vs whole-crop baseline.

    YuNet has no per-landmark confidence; low patch variance + edge energy
    relative to the crop baseline signals occlusion / cover.
    """
    gray = _as_gray_u8(crop_bgr)
    base_var = float(np.var(gray)) + 1e-6
    if gray.shape[0] >= 2 and gray.shape[1] >= 2:
        base_edge = float(np.mean(np.abs(np.diff(gray, axis=0)))) + float(
            np.mean(np.abs(np.diff(gray, axis=1)))
        )
    else:
        base_edge = 0.0
    base_edge = base_edge + 1e-6

    scores: list[float] = []
    for cx, cy in (_CANONICAL_RIGHT_EYE, _CANONICAL_LEFT_EYE):
        var, edge = _patch_stats(gray, cx, cy)
        # Relative activity: low → more occluded.
        activity = 0.5 * (var / base_var) + 0.5 * (edge / base_edge)
        # Map activity to occlusion: activity>=1 → 0; activity→0 → 1.
        scores.append(float(max(0.0, min(1.0, 1.0 - activity))))
    return float(max(0.0, min(1.0, sum(scores) / len(scores))))


def compute_pose_proxies(
    landmarks: Sequence[Sequence[float]] | np.ndarray,
) -> tuple[float | None, float | None]:
    """Yaw/roll proxies from 5-point landmarks (YuNet order).

    roll: inter-ocular angle (degrees).
    yaw: eye-midpoint↔nose lateral offset / inter-ocular distance (degrees-scaled).
    Returns (pose_yaw, pose_roll); None when landmarks are unusable.
    """
    arr = np.asarray(landmarks, dtype=np.float64)
    if arr.shape == (10,):
        arr = arr.reshape(5, 2)
    if arr.shape != (5, 2) or not np.isfinite(arr).all():
        return None, None

    right_eye = arr[0]
    left_eye = arr[1]
    nose = arr[2]
    eye_vec = left_eye - right_eye
    inter_ocular = float(np.linalg.norm(eye_vec))
    if inter_ocular < 1e-6:
        return None, None

    roll = float(math.degrees(math.atan2(float(eye_vec[1]), float(eye_vec[0]))))
    eye_mid = 0.5 * (right_eye + left_eye)
    # Positive yaw when nose is shifted toward the anatomical left (image-right).
    lateral = float((nose[0] - eye_mid[0]) / inter_ocular)
    yaw = float(math.degrees(math.atan(lateral)))
    return yaw, roll


def compute_face_quality_factors(
    *,
    crop_bgr: np.ndarray,
    embedding_norm: float,
    landmarks: Sequence[Sequence[float]] | np.ndarray | None = None,
) -> FaceQualityFactors:
    """Compute the full per-factor breakdown for one aligned face."""
    sharpness = compute_sharpness(crop_bgr)
    occlusion = compute_occlusion_severity(crop_bgr)
    yaw: float | None = None
    roll: float | None = None
    if landmarks is not None:
        yaw, roll = compute_pose_proxies(landmarks)
    return FaceQualityFactors(
        sharpness=float(sharpness),
        embedding_norm=float(embedding_norm),
        occlusion_severity=float(occlusion),
        pose_yaw=yaw,
        pose_roll=roll,
    )


def passes_factor_floors(
    *,
    sharpness: float | None,
    embedding_norm: float | None,
    occlusion_severity: float | None,
    floor_sharpness: float = 0.0,
    floor_embedding_norm: float = 0.0,
    ceiling_occlusion: float = 1.0,
) -> bool:
    """Enrollment floor check; no-op defaults (0/0/1) accept everything (EMB-03)."""
    if sharpness is not None and sharpness < floor_sharpness:
        return False
    if embedding_norm is not None and embedding_norm < floor_embedding_norm:
        return False
    if occlusion_severity is not None and occlusion_severity > ceiling_occlusion:
        return False
    return True


__all__ = [
    "FaceQualityFactors",
    "compute_face_quality_factors",
    "compute_occlusion_severity",
    "compute_pose_proxies",
    "compute_sharpness",
    "passes_factor_floors",
]

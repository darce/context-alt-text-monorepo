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

from recognition.infrastructure.face_pipeline.model_space import ModelSpace
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

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

# InsightFace arcface_dst for 112×112 (python-package/insightface/utils/face_align.py)
# pinned commit 1480e705287bc5d59f923b46c260ec6e3e4150f6. Same decimal literals as
# SFace, but float32 as in that file (not a view/import of the SFace float64 array).
ARCFACE_CANONICAL_LANDMARKS_112: Final[np.ndarray] = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)

# Precomputed mean of SFACE_CANONICAL_LANDMARKS_112 (opencv hard-codes this).
_SFACE_DST_MEAN: Final[tuple[float, float]] = (56.0262, 71.9008)

ALIGNED_SIZE: Final[int] = 112

_SPACE_ARTIFACT: Final[dict[ModelSpace, str]] = {
    ModelSpace.FACE_PIPELINE: "sface",
    ModelSpace.AURAFACE: "auraface",
}
_SFACE_TEMPLATE_ID: Final[str] = "sface-5pt-112"
_ARCFACE_TEMPLATE_ID: Final[str] = "arcface-112"
_DEFAULT_CHANNEL_ORDER: Final[str] = "BGR"
_TEMPLATE_LANDMARKS: Final[dict[str, np.ndarray]] = {
    _SFACE_TEMPLATE_ID: SFACE_CANONICAL_LANDMARKS_112,
    _ARCFACE_TEMPLATE_ID: ARCFACE_CANONICAL_LANDMARKS_112,
}

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


def _as_landmarks5_native(landmarks: np.ndarray) -> np.ndarray:
    """Validate five landmarks without promoting dtype (InsightFace estimate_norm)."""
    arr = np.asarray(landmarks)
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


def _umeyama_similarity_homogeneous(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Faithful port of scikit-image ``transform._geometric._umeyama``.

    Do not pre-cast src/dst; float32 ``arcface_dst`` must keep float32 means.
    Scale uses ``S @ d`` so a reflection sign on the last singular value is
    included (Umeyama 1991 eq. 41–42). Not the OpenCV SFace port.
    """
    src = np.asarray(src)
    dst = np.asarray(dst)
    if src.shape != dst.shape or src.ndim != 2:
        raise AlignmentError(
            f"src/dst must be (M, N) with matching shape, got {src.shape} vs {dst.shape}"
        )
    num = src.shape[0]
    dim = src.shape[1]
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_demean = src - src_mean
    dst_demean = dst - dst_mean
    covariance = dst_demean.T @ src_demean / num
    d = np.ones((dim,), dtype=np.float64)
    if np.linalg.det(covariance) < 0:
        d[dim - 1] = -1
    transform = np.eye(dim + 1, dtype=np.float64)
    u, singular, vt = np.linalg.svd(covariance)
    rank = np.linalg.matrix_rank(covariance)
    if rank == 0:
        return np.nan * transform
    if rank == dim - 1:
        if np.linalg.det(u) * np.linalg.det(vt) > 0:
            transform[:dim, :dim] = u @ vt
        else:
            saved = d[dim - 1]
            d[dim - 1] = -1
            transform[:dim, :dim] = u @ np.diag(d) @ vt
            d[dim - 1] = saved
    else:
        transform[:dim, :dim] = u @ np.diag(d) @ vt
    scale = 1.0 / src_demean.var(axis=0).sum() * (singular @ d)
    transform[:dim, dim] = dst_mean - scale * (transform[:dim, :dim] @ src_mean.T)
    transform[:dim, :dim] *= scale
    return transform


def arcface_similarity_transform_matrix(src_landmarks: np.ndarray) -> np.ndarray:
    """Umeyama similarity matching InsightFace ``estimate_norm`` (ArcFace 112).

    Preserves input landmark dtype and the float32 ArcFace dest means. Returns
    a float64 2×3 affine. Production copy — does not import test goldens.
    """
    src = _as_landmarks5_native(src_landmarks)
    homogeneous = _umeyama_similarity_homogeneous(src, ARCFACE_CANONICAL_LANDMARKS_112)
    if not np.isfinite(homogeneous).all():
        raise AlignmentError("degenerate landmarks; Umeyama is ill-conditioned")
    return np.asarray(homogeneous[0:2, :], dtype=np.float64)


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

    def __init__(
        self,
        *,
        output_size: int = ALIGNED_SIZE,
        space: ModelSpace = ModelSpace.FACE_PIPELINE,
    ) -> None:
        if output_size != ALIGNED_SIZE:
            # SFace canonical landmarks are defined for 112 only.
            raise ValueError(
                f"FivePointAligner only supports output_size={ALIGNED_SIZE} (SFace canonical), got {output_size}"
            )
        self.output_size = output_size
        self.space = ModelSpace(space)
        entry = MODEL_MANIFEST.get(_SPACE_ARTIFACT.get(self.space, "sface"))
        preprocessing = entry.preprocessing if entry is not None else None
        self.template_id = preprocessing.alignment_template_id if preprocessing else _SFACE_TEMPLATE_ID
        self.channel_order = preprocessing.channel_order if preprocessing else _DEFAULT_CHANNEL_ORDER
        if self.template_id not in _TEMPLATE_LANDMARKS:
            supported = ", ".join(sorted(_TEMPLATE_LANDMARKS))
            raise AlignmentError(
                f"unknown alignment template {self.template_id!r}; supported templates: {supported}"
            )
        self.dst_landmarks = _TEMPLATE_LANDMARKS[self.template_id]

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

        # SFace keeps OpenCV's hardcoded dst mean. ArcFace 112 uses the
        # dtype-preserving skimage/InsightFace Umeyama, not the SFace port.
        if self.template_id == _SFACE_TEMPLATE_ID:
            affine = similarity_transform_matrix(landmarks)
        else:
            affine = arcface_similarity_transform_matrix(landmarks)
        crop = cv2.warpAffine(
            img,
            affine,
            (self.output_size, self.output_size),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        )
        # Crops stay BGR. Channel order is blob metadata (InsightFace swapRB).
        return AlignmentResult(crop=crop, affine=affine)


__all__ = [
    "ALIGNED_SIZE",
    "ARCFACE_CANONICAL_LANDMARKS_112",
    "AlignmentError",
    "AlignmentResult",
    "FivePointAligner",
    "SFACE_CANONICAL_LANDMARKS_112",
    "YUNET_LANDMARK_NAMES",
    "arcface_similarity_transform_matrix",
    "similarity_transform_matrix",
]

"""Shared cv2/onnxruntime-free face pipeline validation + embed batch (FIR-3 S3).

Import purity (mandatory): stdlib + numpy + provenance only.
Must not import ``cv2`` or ``onnxruntime`` — both OpenCV and ORT adapters
delegate here so validation gates cannot drift (REF-19 / BR-02).

Heuristics: rg-015 (manifest dim), AGT-06 (fail closed), REF-19.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

# OpenCV FaceDetectorYN defaults (guide / OpenCV 4.x).
DEFAULT_SCORE_THRESHOLD: Final[float] = 0.9
DEFAULT_NMS_THRESHOLD: Final[float] = 0.3
DEFAULT_TOP_K: Final[int] = 5000
DEFAULT_INPUT_SIZE: Final[tuple[int, int]] = (320, 320)

# Manifest is the single source for SFace dim (rg-015) — never invent a default.
SFACE_CROP_SIZE: Final[int] = 112
_FLOAT01_TRAP_MAX: Final[float] = 1.5


def resolve_sface_embedding_dim() -> int:
    """Return SFace embedding dim from the provenance manifest (fail-closed)."""
    dim = MODEL_MANIFEST["sface"].embedding_dim
    if dim is None:
        raise ValueError(
            "MODEL_MANIFEST['sface'].embedding_dim is None; refusing to invent a default embedding dimension (rg-015)"
        )
    return int(dim)


SFACE_EMBEDDING_DIM: Final[int] = resolve_sface_embedding_dim()


class ZeroNormEmbeddingError(Exception):
    """Raised when an SFace embedding has zero L2 norm (never silent zero-fill)."""


class FacePipelineInputError(Exception):
    """Raised when detector/embedder input violates the numpy BGR contract."""


@dataclass(frozen=True, slots=True)
class RawDetection:
    """One YuNet face detection before alignment/embedding.

    ``bbox`` is xywh in image pixels (OpenCV FaceDetectorYN convention).
    ``landmarks`` are 5×2 in YuNet order (see aligner.YUNET_LANDMARK_NAMES).
    """

    bbox: np.ndarray  # (4,) float32 xywh
    landmarks: np.ndarray  # (5, 2) float32
    score: float


def ensure_bgr_u8(image: np.ndarray, *, label: str = "image") -> np.ndarray:
    """Coerce to contiguous H×W×3 uint8 BGR; raise on impossible shapes.

    Floating inputs with max <= 1.5 are rejected as the common [0,1] float trap
    (would otherwise clip to near-black uint8 and silently poison embeddings).
    Floating inputs in ~[0,255] are clip-cast to uint8.
    """
    if image is None:
        raise FacePipelineInputError(f"{label} is None")
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise FacePipelineInputError(f"{label}: expected H×W×3 BGR, got shape {getattr(arr, 'shape', None)}")
    if arr.dtype != np.uint8:
        if np.issubdtype(arr.dtype, np.floating):
            finite = arr[np.isfinite(arr)]
            peak = float(np.max(finite)) if finite.size else 0.0
            if peak <= _FLOAT01_TRAP_MAX:
                raise FacePipelineInputError(
                    f"{label}: floating image max={peak} looks like a [0,1]-float "
                    f"trap (threshold max>{_FLOAT01_TRAP_MAX}); convert to uint8 "
                    "BGR in [0,255] before detect/embed/align"
                )
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        else:
            arr = arr.astype(np.uint8)
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr


# Private alias kept for call sites / tests that already use the underscore name.
_ensure_bgr_u8 = ensure_bgr_u8


def embed_batch(
    crops: Sequence[np.ndarray],
    *,
    feature_fn: Callable[[np.ndarray], np.ndarray],
    embedding_dim: int,
) -> np.ndarray:
    """Shared SFace embed path: 112 gate, dim gate, zero/non-finite-norm, L2 stack.

    Both ``OpenCVSFaceEmbedder`` and ``OrtSFaceEmbedder`` must delegate here so
    the hardened gates live once (BR-02 / REF-19).
    """
    if not crops:
        return np.zeros((0, embedding_dim), dtype=np.float32)

    expected_shape = (SFACE_CROP_SIZE, SFACE_CROP_SIZE, 3)
    vectors: list[np.ndarray] = []
    for i, crop in enumerate(crops):
        img = ensure_bgr_u8(crop, label=f"crops[{i}]")
        if img.shape != expected_shape:
            raise FacePipelineInputError(
                f"crops[{i}]: expected shape {expected_shape} (SFace crop), "
                f"got {img.shape}; align via FivePointAligner before embed"
            )
        raw = np.asarray(feature_fn(img), dtype=np.float32).reshape(-1)
        if raw.size != embedding_dim:
            raise FacePipelineInputError(f"crops[{i}]: expected embedding dim {embedding_dim}, got {raw.size}")
        norm = float(np.linalg.norm(raw))
        if norm == 0.0 or not np.isfinite(norm):
            raise ZeroNormEmbeddingError(
                f"crops[{i}]: SFace embedding has zero/non-finite L2 norm (norm={norm}); refusing silent zero-fill"
            )
        vectors.append(raw / norm)
    return np.stack(vectors, axis=0).astype(np.float32, copy=False)


__all__ = [
    "DEFAULT_INPUT_SIZE",
    "DEFAULT_NMS_THRESHOLD",
    "DEFAULT_SCORE_THRESHOLD",
    "DEFAULT_TOP_K",
    "FacePipelineInputError",
    "RawDetection",
    "SFACE_CROP_SIZE",
    "SFACE_EMBEDDING_DIM",
    "ZeroNormEmbeddingError",
    "embed_batch",
    "ensure_bgr_u8",
    "resolve_sface_embedding_dim",
]

"""OpenCV reference YuNet detector + SFace embedder (FIR-3 S2).

Semantic source-of-truth for the face pipeline. Clarity over speed.
Models load ONLY via ``load_verified_model``. Sync + numpy only — no FIR-2
async FaceDetectorProtocol wiring (that is FIR-4).

Heuristics: rg-015 (no invented contract metadata), rg-013-style purity
(this module may import cv2/numpy/provenance only — not worker/HTTP).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

import cv2
import numpy as np

from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    load_verified_model,
)

# OpenCV FaceDetectorYN defaults (guide / OpenCV 4.x).
DEFAULT_SCORE_THRESHOLD: Final[float] = 0.9
DEFAULT_NMS_THRESHOLD: Final[float] = 0.3
DEFAULT_TOP_K: Final[int] = 5000
DEFAULT_INPUT_SIZE: Final[tuple[int, int]] = (320, 320)

# Manifest is the single source for dim when available (rg-015).
_SFACE_DIM_FROM_MANIFEST = MODEL_MANIFEST["sface"].embedding_dim
SFACE_EMBEDDING_DIM: Final[int] = (
    int(_SFACE_DIM_FROM_MANIFEST) if _SFACE_DIM_FROM_MANIFEST is not None else 128
)


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


def _ensure_bgr_u8(image: np.ndarray, *, label: str = "image") -> np.ndarray:
    """Coerce to contiguous H×W×3 uint8 BGR; raise on impossible shapes."""
    if image is None:
        raise FacePipelineInputError(f"{label} is None")
    arr = np.asarray(image)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise FacePipelineInputError(
            f"{label}: expected H×W×3 BGR, got shape {getattr(arr, 'shape', None)}"
        )
    if arr.dtype != np.uint8:
        if np.issubdtype(arr.dtype, np.floating):
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        else:
            arr = arr.astype(np.uint8)
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return arr


def _parse_faces(faces: np.ndarray | None) -> list[RawDetection]:
    """Parse FaceDetectorYN output matrix into RawDetection list."""
    if faces is None:
        return []
    mat = np.asarray(faces)
    if mat.size == 0:
        return []
    if mat.ndim == 1:
        mat = mat.reshape(1, -1)
    out: list[RawDetection] = []
    for row in mat:
        row = np.asarray(row, dtype=np.float32).reshape(-1)
        if row.size < 15:
            raise FacePipelineInputError(
                f"FaceDetectorYN row has {row.size} fields, expected ≥15 "
                "(x,y,w,h + 5×2 landmarks + score)"
            )
        bbox = row[0:4].copy()
        landmarks = row[4:14].reshape(5, 2).copy()
        score = float(row[14])
        out.append(RawDetection(bbox=bbox, landmarks=landmarks, score=score))
    return out


class OpenCVYuNetDetector:
    """Reference YuNet detector wrapping ``cv2.FaceDetectorYN``.

    Batch API: ``detect(images) -> list[list[RawDetection]]``.
    Input size is set per image to the image's (width, height).
    """

    def __init__(
        self,
        *,
        model_name: str = "yunet",
        models_dir: Path | None = None,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        nms_threshold: float = DEFAULT_NMS_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
        initial_input_size: tuple[int, int] = DEFAULT_INPUT_SIZE,
    ) -> None:
        model_path = load_verified_model(model_name, models_dir=models_dir)
        self._model_name = model_name
        self._model_path = model_path
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.top_k = int(top_k)
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path),
            "",
            initial_input_size,
            score_threshold=self.score_threshold,
            nms_threshold=self.nms_threshold,
            top_k=self.top_k,
        )

    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]:
        """Detect faces in a batch of BGR images."""
        results: list[list[RawDetection]] = []
        for i, image in enumerate(images):
            img = _ensure_bgr_u8(image, label=f"images[{i}]")
            h, w = img.shape[:2]
            self._detector.setInputSize((w, h))
            _retval, faces = self._detector.detect(img)
            results.append(_parse_faces(faces))
        return results


class OpenCVSFaceEmbedder:
    """Reference SFace embedder wrapping ``cv2.FaceRecognizerSF``.

    Batch API: ``embed(crops) -> (N, 128)`` L2-normalized float32.
    Zero-norm model output raises ``ZeroNormEmbeddingError`` (never silent fill).
    """

    def __init__(
        self,
        *,
        model_name: str = "sface",
        models_dir: Path | None = None,
    ) -> None:
        model_path = load_verified_model(model_name, models_dir=models_dir)
        self._model_name = model_name
        self._model_path = model_path
        self._recognizer = cv2.FaceRecognizerSF.create(str(model_path), "")
        self.embedding_dim = SFACE_EMBEDDING_DIM

    def _feature(self, crop: np.ndarray) -> np.ndarray:
        """Raw model feature for one crop (hookable in tests)."""
        return self._recognizer.feature(crop)

    def embed(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        """Embed a batch of 112×112 (or any) BGR crops → L2-normalized (N, 128)."""
        if not crops:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)

        vectors: list[np.ndarray] = []
        for i, crop in enumerate(crops):
            img = _ensure_bgr_u8(crop, label=f"crops[{i}]")
            raw = np.asarray(self._feature(img), dtype=np.float32).reshape(-1)
            if raw.size != self.embedding_dim:
                raise FacePipelineInputError(
                    f"crops[{i}]: expected embedding dim {self.embedding_dim}, got {raw.size}"
                )
            norm = float(np.linalg.norm(raw))
            if norm == 0.0 or not np.isfinite(norm):
                raise ZeroNormEmbeddingError(
                    f"crops[{i}]: SFace embedding has zero/non-finite L2 norm "
                    f"(norm={norm}); refusing silent zero-fill"
                )
            vectors.append(raw / norm)
        return np.stack(vectors, axis=0).astype(np.float32, copy=False)


__all__ = [
    "DEFAULT_INPUT_SIZE",
    "DEFAULT_NMS_THRESHOLD",
    "DEFAULT_SCORE_THRESHOLD",
    "DEFAULT_TOP_K",
    "FacePipelineInputError",
    "OpenCVSFaceEmbedder",
    "OpenCVYuNetDetector",
    "RawDetection",
    "SFACE_EMBEDDING_DIM",
    "ZeroNormEmbeddingError",
]

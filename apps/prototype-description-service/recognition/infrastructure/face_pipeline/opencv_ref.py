"""OpenCV reference YuNet detector + SFace embedder (FIR-3 S2).

Semantic source-of-truth for the face pipeline. Clarity over speed.
Models load ONLY via ``load_verified_model``. Sync + numpy only — no FIR-2
async FaceDetectorProtocol wiring (that is FIR-4).

Shared validation + embed batch live in ``_common`` (cv2-free) so ORT and
OpenCV paths cannot drift (BR-02 / REF-19).

Heuristics: rg-015 (no invented contract metadata), rg-013-style purity
(this module may import cv2/numpy/provenance/_common only — not worker/HTTP).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import cv2
import numpy as np

from recognition.infrastructure.face_pipeline._common import (
    DEFAULT_INPUT_SIZE,
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
    SFACE_CROP_SIZE,
    SFACE_EMBEDDING_DIM,
    EmbedBatchResult,
    FacePipelineInputError,
    RawDetection,
    ZeroNormEmbeddingError,
    _ensure_bgr_u8,
    embed_batch,
    resolve_sface_embedding_dim,
)
from recognition.infrastructure.face_pipeline.provenance import (
    load_verified_model,
)


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
                f"FaceDetectorYN row has {row.size} fields, expected ≥15 (x,y,w,h + 5×2 landmarks + score)"
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

    ``score_threshold`` / ``nms_threshold`` / ``top_k`` are constructor-only
    (read-only properties). Native FaceDetectorYN is configured at create time;
    post-construction assignment raises AttributeError (no silent no-op).
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
        self._score_threshold = float(score_threshold)
        self._nms_threshold = float(nms_threshold)
        self._top_k = int(top_k)
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path),
            "",
            initial_input_size,
            score_threshold=self._score_threshold,
            nms_threshold=self._nms_threshold,
            top_k=self._top_k,
        )

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @property
    def nms_threshold(self) -> float:
        return self._nms_threshold

    @property
    def top_k(self) -> int:
        return self._top_k

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

    Batch API: ``embed(crops) -> (N, dim)`` L2-normalized float32.
    Crops must be exactly 112×112×3 BGR (alignment owns sizing; fail-closed).
    Zero-norm model output raises ``ZeroNormEmbeddingError`` (never silent fill).
    Validation/normalization lives in ``_common.embed_batch`` (shared with ORT).
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

    def embed(self, crops: Sequence[np.ndarray]) -> EmbedBatchResult:
        """Embed a batch of 112×112×3 BGR crops → EmbedBatchResult (vectors + pre-norm norms).

        Non-(112, 112, 3) crops raise ``FacePipelineInputError`` (no silent resize).
        """
        return embed_batch(
            crops,
            feature_fn=self._feature,
            embedding_dim=self.embedding_dim,
        )


__all__ = [
    "DEFAULT_INPUT_SIZE",
    "DEFAULT_NMS_THRESHOLD",
    "DEFAULT_SCORE_THRESHOLD",
    "DEFAULT_TOP_K",
    "FacePipelineInputError",
    "OpenCVSFaceEmbedder",
    "OpenCVYuNetDetector",
    "RawDetection",
    "SFACE_CROP_SIZE",
    "SFACE_EMBEDDING_DIM",
    "ZeroNormEmbeddingError",
    "resolve_sface_embedding_dim",
]

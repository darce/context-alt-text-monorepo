"""InsightFace embedding provider focusing on identity + context features."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import cv2
import numpy as np
from PIL import Image

from recognition.config import get_settings
from recognition.domain.entities import FaceDetection, FaceEmbedding

logger = logging.getLogger(__name__)


class FaceEmbeddingProvider:
    """Wraps InsightFace and derives 1024-dimensional embeddings (identity + context)."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._app = None
        self._model_loaded = False
        self._model_lock = asyncio.Lock()

    async def _ensure_model_loaded(self) -> None:
        if self._model_loaded:
            return

        async with self._model_lock:
            if self._model_loaded:
                return

            try:
                from insightface.app import FaceAnalysis
            except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional dependency
                raise RuntimeError(
                    "InsightFace is not installed. Install `insightface` to enable face embeddings."
                ) from exc

            logger.info("Loading InsightFace model %s", self.settings.insightface.model_name)
            self._app = FaceAnalysis(
                name=self.settings.insightface.model_name,
                root=str(self.settings.insightface.cache_dir),
                providers=list(self._get_providers()),
            )
            self._app.prepare(
                ctx_id=0 if self.settings.insightface.device == "cuda" else -1,
                det_size=tuple(self.settings.insightface.det_size),
                det_thresh=self.settings.insightface.det_thresh,
            )
            self._model_loaded = True
            logger.info("InsightFace model loaded")

    def _get_providers(self) -> List[str]:
        providers = list(self.settings.insightface.providers)
        if providers:
            return providers

        device = self.settings.insightface.device
        if device == "cuda":
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if device == "mps":
            return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        rgb_array = np.array(pil_image)
        return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

    async def analyze(self, image: Image.Image) -> List[FaceEmbedding]:
        await self._ensure_model_loaded()

        cv2_image = self._pil_to_cv2(image)
        assert self._app is not None

        faces = self._app.get(cv2_image)
        results: List[FaceEmbedding] = []

        for face in faces:
            bbox = face.bbox.astype(int)
            x_min, y_min, x_max, y_max = bbox

            detection = FaceDetection(
                bbox=(x_min, y_min, x_max, y_max),
                confidence=float(face.det_score),
                landmarks=getattr(face, "kps", None),
            )

            identity_vec = face.normed_embedding
            context_vec = self._context_vector(face, image)
            composite = np.concatenate([identity_vec, context_vec])

            results.append(FaceEmbedding(embedding=composite, detection=detection))

        logger.info("Detected %d faces", len(results))
        return results

    def _context_vector(self, face, image: Image.Image) -> np.ndarray:
        bbox = face.bbox.astype(int)
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        area = width * height
        stats = np.array([
            width,
            height,
            area,
            face.det_score,
            float(getattr(face, "age", 0.0)),
            float(getattr(face, "gender", 0.5)),
        ], dtype=np.float32)

        norm = np.linalg.norm(stats)
        if norm:
            stats = stats / norm

        padded = np.pad(
            stats,
            (0, self.settings.identity_detection.embedding_dimension // 2 - stats.shape[0]),
        )
        return padded[: self.settings.identity_detection.embedding_dimension // 2]

    def model_info(self) -> dict[str, object]:
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "embedding_dimension": self.settings.identity_detection.embedding_dimension,
            "detection_threshold": self.settings.insightface.det_thresh,
        }

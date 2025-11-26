"""InsightFace embedding provider focusing on identity + context features."""

from __future__ import annotations

import asyncio
import logging

import cv2
import numpy as np
from PIL import Image

from recognition.config import get_settings
from recognition.domain.embeddings import build_extended_embedding
from recognition.domain.entities import IdentityDetection, IdentityEmbedding

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
            if self._model_loaded:  # Double-check after acquiring lock
                return  # type: ignore[unreachable]

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
            if self._app is not None:  # Type narrowing for mypy
                self._app.prepare(  # type: ignore[unreachable]
                    ctx_id=0 if self.settings.insightface.device == "cuda" else -1,
                    det_size=tuple(self.settings.insightface.det_size),
                    det_thresh=self.settings.insightface.det_thresh,
                )
            self._model_loaded = True
            logger.info("InsightFace model loaded")

    def _get_providers(self) -> list[str]:
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

    async def analyze(self, image: Image.Image) -> list[IdentityEmbedding]:
        await self._ensure_model_loaded()

        cv2_image = self._pil_to_cv2(image)
        assert self._app is not None

        faces = self._app.get(cv2_image)  # type: ignore[unreachable]
        results: list[IdentityEmbedding] = []

        for face in faces:
            bbox = face.bbox.astype(int)
            x_min, y_min, x_max, y_max = bbox

            detection = IdentityDetection(
                bbox=(x_min, y_min, x_max, y_max),
                confidence=float(face.det_score),
                landmarks=getattr(face, "kps", None),
            )

            # Build extended 1024D embedding using structured layout
            identity_vec = face.normed_embedding

            # Extract optional attributes from InsightFace
            pose = None
            if hasattr(face, "pose") and face.pose is not None:
                pose = tuple(face.pose)  # (pitch, yaw, roll)

            age = int(face.age) if hasattr(face, "age") and face.age is not None else None
            gender = int(face.gender) if hasattr(face, "gender") and face.gender is not None else None
            landmarks = face.kps if hasattr(face, "kps") else None

            composite = build_extended_embedding(
                face_embedding=identity_vec,
                det_score=float(face.det_score),
                bbox=(x_min, y_min, x_max, y_max),
                pose=pose,
                age=age,
                gender=gender,
                landmarks=landmarks,
            )

            results.append(IdentityEmbedding(embedding=composite, detection=detection))

        logger.info("Detected %d faces", len(results))
        return results

    def model_info(self) -> dict[str, object]:
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "embedding_dimension": self.settings.identity_detection.embedding_dimension,
            "detection_threshold": self.settings.insightface.det_thresh,
        }

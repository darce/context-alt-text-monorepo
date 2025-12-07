"""InsightFace adapter for face detection and embedding generation.

This module provides the infrastructure adapter that wraps InsightFace for
face detection and embedding generation. It implements the port interfaces
expected by the application layer.

See: docs/tasks/4.0/4.2.4/RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

import asyncio
import io
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image

from recognition.config import get_settings
from recognition.domain.embeddings import build_extended_embedding

if TYPE_CHECKING:
    from insightface.app import FaceAnalysis

logger = logging.getLogger(__name__)


@dataclass
class DetectedFace:
    """Face detection result from InsightFace."""

    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float
    embedding_512: np.ndarray  # 512D face identity vector
    pose: tuple[float, float, float] | None  # pitch, yaw, roll
    age: int | None
    gender: int | None  # 0=female, 1=male
    landmarks: np.ndarray | None  # 5-point or 106-point landmarks


class InsightFaceAdapter:
    """Adapter for InsightFace detection and embedding generation.

    Wraps InsightFace's FaceAnalysis for face detection and generates
    1024D extended embeddings (512D face + 512D metadata).

    Usage:
        adapter = InsightFaceAdapter()
        await adapter.ensure_loaded()
        faces = await adapter.detect_faces(image_bytes)
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._app: FaceAnalysis | None = None
        self._model_loaded = False
        self._model_lock = asyncio.Lock()

    async def ensure_loaded(self) -> None:
        """Lazily load the InsightFace model on first use."""
        async with self._model_lock:
            if self._model_loaded:
                return

            try:
                from insightface.app import FaceAnalysis
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "InsightFace is not installed. Install with: pip install 'prototype-description-service[local]'"
                ) from exc

            model_name = self.settings.insightface.model_name
            cache_dir = str(self.settings.insightface.cache_dir)
            providers = self._get_providers()

            logger.info("Loading InsightFace model %s with providers %s", model_name, providers)

            self._app = FaceAnalysis(
                name=model_name,
                root=cache_dir,
                providers=providers,
            )

            ctx_id = self._get_ctx_id()
            det_size = self.settings.insightface.det_size
            det_thresh = self.settings.insightface.det_thresh

            self._app.prepare(
                ctx_id=ctx_id,
                det_size=det_size,
                det_thresh=det_thresh,
            )

            self._model_loaded = True
            logger.info("InsightFace model %s loaded successfully", model_name)

    def _get_providers(self) -> list[str]:
        """Determine ONNX Runtime execution providers based on settings."""
        providers = list(self.settings.insightface.providers)
        if providers:
            return providers

        device = self.settings.insightface.device
        if device == "auto":
            # Auto-detect: prefer GPU, fallback to CPU
            return ["CUDAExecutionProvider", "CoreMLExecutionProvider", "CPUExecutionProvider"]
        if device == "cuda":
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if device == "mps":
            return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _get_ctx_id(self) -> int:
        """Get context ID for InsightFace (GPU index or -1 for CPU)."""
        device = self.settings.insightface.device
        if device in ("cuda", "auto"):
            return 0  # GPU device 0
        return -1  # CPU

    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        """Convert PIL Image to OpenCV BGR format."""
        # Ensure RGB mode
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        rgb_array = np.array(pil_image)
        return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)

    def _bytes_to_cv2(self, image_bytes: bytes) -> np.ndarray:
        """Convert image bytes to OpenCV BGR format."""
        pil_image = Image.open(io.BytesIO(image_bytes))
        return self._pil_to_cv2(pil_image)

    async def detect_faces(self, image_bytes: bytes) -> list[DetectedFace]:
        """Detect all faces in an image.

        Args:
            image_bytes: Image data as bytes (JPEG, PNG, etc.)

        Returns:
            List of DetectedFace with bounding boxes, embeddings, and metadata
        """
        await self.ensure_loaded()

        if self._app is None:
            raise RuntimeError("InsightFace model not loaded")

        cv2_image = self._bytes_to_cv2(image_bytes)

        # Run detection in thread pool (InsightFace is sync)
        loop = asyncio.get_running_loop()
        faces = await loop.run_in_executor(None, self._app.get, cv2_image)

        results: list[DetectedFace] = []
        for face in faces:
            bbox = tuple(int(x) for x in face.bbox)

            # Extract optional attributes
            pose = None
            if hasattr(face, "pose") and face.pose is not None:
                pose = tuple(float(x) for x in face.pose)

            age = int(face.age) if hasattr(face, "age") and face.age is not None else None
            gender = int(face.gender) if hasattr(face, "gender") and face.gender is not None else None
            landmarks = face.kps if hasattr(face, "kps") else None

            results.append(
                DetectedFace(
                    bbox=bbox,  # type: ignore[arg-type]
                    confidence=float(face.det_score),
                    embedding_512=face.normed_embedding,
                    pose=pose,  # type: ignore[arg-type]
                    age=age,
                    gender=gender,
                    landmarks=landmarks,
                )
            )

        logger.debug("Detected %d faces in image", len(results))
        return results

    async def generate_extended_embedding(self, face: DetectedFace) -> np.ndarray:
        """Generate 1024D extended embedding from a detected face.

        Combines the 512D face identity vector with metadata (pose, age, gender,
        detection confidence, bounding box area, landmark quality).

        Args:
            face: DetectedFace from detect_faces()

        Returns:
            1024D numpy array (float32)
        """
        return build_extended_embedding(
            face_embedding=face.embedding_512,
            det_score=face.confidence,
            bbox=face.bbox,
            pose=face.pose,
            age=face.age,
            gender=face.gender,
            landmarks=face.landmarks,
        )

    async def analyze(self, image_bytes: bytes) -> list[tuple[DetectedFace, np.ndarray]]:
        """Detect faces and generate extended embeddings in one call.

        Args:
            image_bytes: Image data as bytes

        Returns:
            List of (DetectedFace, embedding_1024d) tuples
        """
        faces = await self.detect_faces(image_bytes)
        results = []
        for face in faces:
            embedding = await self.generate_extended_embedding(face)
            results.append((face, embedding))
        return results

    def model_info(self) -> dict[str, object]:
        """Return information about the loaded model."""
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "det_thresh": self.settings.insightface.det_thresh,
            "det_size": self.settings.insightface.det_size,
            "model_loaded": self._model_loaded,
        }


__all__ = ["InsightFaceAdapter", "DetectedFace"]

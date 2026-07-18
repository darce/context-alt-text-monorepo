"""InsightFace adapter for face detection and embedding generation.

This module provides the infrastructure adapter that wraps InsightFace for
face detection and embedding generation. It implements the port interfaces
expected by the application layer.

Maps InsightFace output directly into the neutral application-layer
``FaceDetection`` seam type (FIR-2 S2b).

See: docs/tasks/4.0/4.2.4/RECOGNITION_SERVICE_V4.2.4_IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image

from recognition.application.embedding.detector import FaceDetection, normalize_landmarks
from recognition.application.embedding.manifest import incumbent_embedding_model_manifest
from recognition.config import get_settings

if TYPE_CHECKING:
    from insightface.app import FaceAnalysis

logger = logging.getLogger(__name__)

_SHARED_ADAPTER: InsightFaceAdapter | None = None
_SHARED_ADAPTER_LOCK = asyncio.Lock()


class InsightFaceAdapter:
    """Adapter for InsightFace detection and embedding generation.

    Wraps InsightFace's FaceAnalysis for face detection and generates
    face embeddings at the configured dimension, returning FaceDetection.

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
        self._manifest = incumbent_embedding_model_manifest()

    async def ensure_loaded(self) -> None:
        """Lazily load the InsightFace model on first use."""
        async with self._model_lock:
            if self._model_loaded:
                return

            try:
                from insightface.app import FaceAnalysis
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "InsightFace is not installed. Install with: pip install 'prototype-description-service[bench]' "
                    "(or: uv sync --extra bench). Required for the incumbent dark-default profile; "
                    "face_pipeline uses core deps + scripts/fetch_face_pipeline_models.py."
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

    async def detect_faces(self, image_bytes: bytes) -> list[FaceDetection]:
        """Detect all faces in an image.

        Args:
            image_bytes: Image data as bytes (JPEG, PNG, etc.)

        Returns:
            List of FaceDetection with bounding boxes, embeddings, and metadata
        """
        await self.ensure_loaded()

        if self._app is None:
            raise RuntimeError("InsightFace model not loaded")

        cv2_image = self._bytes_to_cv2(image_bytes)

        # Run detection in thread pool (InsightFace is sync)
        loop = asyncio.get_running_loop()
        faces = await loop.run_in_executor(None, self._app.get, cv2_image)

        model_id = self._manifest.model_id
        results: list[FaceDetection] = []
        for face in faces:
            bbox = tuple(int(x) for x in face.bbox)

            # Pose remains for pose-bucket / diversity (not threshold quality).
            pose_pitch: float | None = None
            pose_yaw: float | None = None
            pose_roll: float | None = None
            if hasattr(face, "pose") and face.pose is not None:
                pose_pitch = float(face.pose[0])
                pose_yaw = float(face.pose[1])
                pose_roll = float(face.pose[2])

            landmarks = None
            if hasattr(face, "kps") and face.kps is not None:
                landmarks = normalize_landmarks(face.kps)

            results.append(
                FaceDetection(
                    media_id="",  # filled by InsightFaceFaceDetector with source id
                    bbox=bbox,  # type: ignore[arg-type]
                    confidence=float(face.det_score),
                    embedding=face.normed_embedding,
                    pose_pitch=pose_pitch,
                    pose_yaw=pose_yaw,
                    pose_roll=pose_roll,
                    model_id=model_id,
                    landmarks=landmarks,
                )
            )

        logger.debug("Detected %d faces in image", len(results))
        return results

    async def analyze(self, image_bytes: bytes) -> list[FaceDetection]:
        """Detect faces and generate embeddings in one call.

        Args:
            image_bytes: Image data as bytes

        Returns:
            List of FaceDetection objects
        """
        return await self.detect_faces(image_bytes)

    def model_info(self) -> dict[str, object]:
        """Return information about the loaded model."""
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "det_thresh": self.settings.insightface.det_thresh,
            "det_size": self.settings.insightface.det_size,
            "model_loaded": self._model_loaded,
            "model_id": self._manifest.model_id,
            "embedding_dimensions": self._manifest.dimensions,
        }


async def get_shared_insightface_adapter() -> InsightFaceAdapter:
    """Return the process-wide InsightFace adapter singleton."""
    global _SHARED_ADAPTER
    if _SHARED_ADAPTER is None:
        async with _SHARED_ADAPTER_LOCK:
            if _SHARED_ADAPTER is None:
                adapter = InsightFaceAdapter()
                await adapter.ensure_loaded()
                _SHARED_ADAPTER = adapter
    return _SHARED_ADAPTER


def reset_shared_insightface_adapter_for_tests() -> None:
    """Clear the shared adapter singleton for isolated tests."""
    global _SHARED_ADAPTER
    _SHARED_ADAPTER = None


__all__ = [
    "InsightFaceAdapter",
    "get_shared_insightface_adapter",
    "reset_shared_insightface_adapter_for_tests",
]

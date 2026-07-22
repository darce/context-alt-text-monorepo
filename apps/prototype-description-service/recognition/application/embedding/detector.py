"""
Face detection adapter interface.

This module provides the FaceDetector interface and implementations:
- StubFaceDetector: Deterministic stub for tests (hash-based)
- InsightFaceFaceDetector: Real detection using InsightFace

The ScanService depends on this interface for face detection.
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

import httpx
import imagehash
import numpy as np
from PIL import Image

from recognition.application.integrations import (
    AdapterBreakerOpenError,
    AdapterCircuitBreaker,
    AdapterTimeoutError,
    create_adapter_circuit_breaker,
    wait_for_adapter,
)

if TYPE_CHECKING:
    from recognition.infrastructure.embeddings import InsightFaceAdapter

logger = logging.getLogger(__name__)

LandmarkPoint = tuple[float, float]
LandmarkSet = tuple[LandmarkPoint, LandmarkPoint, LandmarkPoint, LandmarkPoint, LandmarkPoint]


def normalize_landmarks(raw: Any) -> LandmarkSet | None:
    """Normalize boundary landmark input to five finite (x, y) float points.

    Accepts None (passthrough) or exactly five numeric point pairs. Rejects
    wrong arity, non-numeric coords, and non-finite values explicitly.
    """
    if raw is None:
        return None
    if isinstance(raw, (str, bytes)):
        raise TypeError(f"landmarks must be a sequence of 5 (x, y) points, got {type(raw).__name__}")
    try:
        points = list(raw)
    except TypeError as exc:
        raise TypeError(
            f"landmarks must be a sequence of 5 (x, y) points, got {type(raw).__name__}"
        ) from exc
    if len(points) != 5:
        raise ValueError(f"landmarks must contain exactly 5 points, got {len(points)}")

    normalized: list[LandmarkPoint] = []
    for i, point in enumerate(points):
        if isinstance(point, (str, bytes)):
            raise TypeError(f"landmark[{i}] must be an (x, y) pair, got {type(point).__name__}")
        try:
            coords = list(point)
        except TypeError as exc:
            raise TypeError(
                f"landmark[{i}] must be an (x, y) pair, got {type(point).__name__}"
            ) from exc
        if len(coords) != 2:
            raise ValueError(f"landmark[{i}] must have exactly 2 coordinates, got {len(coords)}")
        try:
            x = float(coords[0])
            y = float(coords[1])
        except (TypeError, ValueError) as exc:
            raise TypeError(f"landmark[{i}] coordinates must be numeric") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"landmark[{i}] coordinates must be finite, got ({x}, {y})")
        normalized.append((x, y))

    return (
        normalized[0],
        normalized[1],
        normalized[2],
        normalized[3],
        normalized[4],
    )


def _compute_detection_quality(
    confidence: float,
    bbox: tuple[int, int, int, int],
) -> float:
    """Compute quality score from detection metrics.

    Delegates to the canonical compute_identity_quality() to ensure consistency
    between detection-time quality and clustering-time quality. Pose is not part
    of threshold quality (FIR2-BR-03).

    Args:
        confidence: Detection confidence from the model (0-1).
        bbox: Bounding box (x1, y1, x2, y2) corner.

    Returns:
        Quality score in [0.0, 1.0] from confidence and bbox size only.
    """
    # Import here to avoid circular dependency
    from recognition.application.assignment.quality import compute_identity_quality

    # FaceDetection.bbox is corner format (x1,y1,x2,y2) for both face_pipeline and
    # InsightFace callers — derive width/height; do not treat x2/y2 as size [SERVE-08].
    bbox_width = int(bbox[2] - bbox[0])
    bbox_height = int(bbox[3] - bbox[1])
    info = compute_identity_quality(
        confidence=confidence,
        bbox_width=bbox_width,
        bbox_height=bbox_height,
    )
    return info.score


@dataclass
class FaceDetection:
    """Neutral detection/embedding seam type (model-agnostic).

    Age/gender removed (FIR-2 S4). Pose angles remain for pose-bucket /
    diversity logic (not threshold quality). Optional five-point landmarks
    surface when the producer has them (FIR2-BR-02). ``model_id`` is stamped
    by the producing adapter.
    """

    media_id: str
    bbox: tuple[int, int, int, int]
    confidence: float
    embedding: np.ndarray | None = None  # unit-normalized face embedding
    # Detection metadata
    pose_pitch: float | None = None
    pose_yaw: float | None = None
    pose_roll: float | None = None
    image_phash: str | None = None
    landmark_quality: float | None = None
    model_id: str = ""
    landmarks: LandmarkSet | None = None


class DetectionTimeoutError(TimeoutError):
    """Raised when the face detector adapter exceeds the configured deadline."""

    def __init__(self, media_id: str, timeout_s: float) -> None:
        super().__init__(f"Face detection timed out for {media_id[:20]} after {timeout_s:.2f}s")
        self.media_id = media_id
        self.timeout_s = timeout_s


class DetectionAdapterError(RuntimeError):
    """Raised when the face detector adapter fails for a non-timeout reason."""

    def __init__(self, media_id: str, error_message: str) -> None:
        super().__init__(f"Face detection failed for {media_id[:20]}: {error_message}")
        self.media_id = media_id
        self.error_message = error_message


class FaceDetectorProtocol(ABC):
    """Protocol for face detection adapters."""

    @abstractmethod
    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        """Detect faces in the provided media sources.

        Args:
            sources: Iterable of media byte payloads or URLs to fetch.

        Returns:
            List of detected faces with bounding boxes and confidence.
        """
        ...


class StubFaceDetector(FaceDetectorProtocol):
    """Deterministic stub detector for tests - generates fake detections from hashes."""

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        """Return deterministic fake detections based on input hashes."""
        detections: list[FaceDetection] = []
        for source in sources:
            if not source:
                continue
            media_ref = source if isinstance(source, str) else hashlib.sha256(source).hexdigest()
            # Use hash-derived bytes to build a deterministic bbox and confidence
            digest = hashlib.sha256(str(media_ref).encode()).digest()
            x1 = digest[0] % 100
            y1 = digest[1] % 100
            width = max(1, digest[2] % 100)
            height = max(1, digest[3] % 100)
            confidence = (digest[4] / 255.0) if digest[4] else 0.99
            image_phash = digest.hex()[:16]  # Fake phash for stubs
            detections.append(
                FaceDetection(
                    media_id=str(media_ref),
                    bbox=(x1, y1, x1 + width, y1 + height),
                    confidence=float(confidence),
                    image_phash=image_phash,
                    model_id="stub-detector@test",
                )
            )
        return detections


class UnavailableFaceDetector(FaceDetectorProtocol):
    """Fail-closed detector for production runtime initialization failures."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        media_id = "recognition-runtime"
        for source in sources:
            if source:
                media_id = source if isinstance(source, str) else hashlib.sha256(source).hexdigest()
                break
        raise DetectionAdapterError(media_id=str(media_id), error_message=self.reason)


class InsightFaceFaceDetector(FaceDetectorProtocol):
    """Real face detector using InsightFace."""

    def __init__(
        self,
        adapter: InsightFaceAdapter,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        breaker: AdapterCircuitBreaker | None = None,
    ) -> None:
        self._adapter = adapter
        self._timeout = timeout
        self._client = client
        self._breaker = breaker or create_adapter_circuit_breaker("insightface.detect_faces")

    async def _fetch_image(self, url: str) -> bytes | None:
        """Fetch image bytes from a URL."""
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response.content
            response = await self._client.get(url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as e:
            logger.error("Failed to fetch image from %s: %s", url[:100], e)
            return None

    @staticmethod
    def _compute_phash(image_bytes: bytes) -> str | None:
        """Compute perceptual hash for duplicate detection."""
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                return str(imagehash.phash(img, hash_size=16))
        except Exception as e:
            logger.error("Failed to compute phash: %s", e)
            return None

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        """Detect real faces using InsightFace."""
        detections: list[FaceDetection] = []

        for source in sources:
            if not source:
                continue

            # Determine media_id and get image bytes
            if isinstance(source, str):
                media_id = source
                # Check if it looks like a URL
                if source.startswith(("http://", "https://")):
                    image_bytes = await self._fetch_image(source)
                    if image_bytes is None:
                        continue
                else:
                    # Not a URL and not bytes - skip with warning
                    logger.warning("Non-URL string source not supported: %s", source[:50])
                    continue
            else:
                media_id = hashlib.sha256(source).hexdigest()
                image_bytes = source

            current_source_bytes: bytes = image_bytes

            # Compute image phash once per image
            image_phash = self._compute_phash(current_source_bytes)

            # Detect faces and get embeddings in one pass
            try:

                async def detect_current_image(
                    current_image_bytes: bytes = current_source_bytes,
                ) -> list[FaceDetection]:
                    return await wait_for_adapter(
                        self._adapter.detect_faces(current_image_bytes),
                        timeout_s=self._timeout,
                        adapter_name="insightface.detect_faces",
                    )

                faces: list[FaceDetection] = await self._breaker.call(detect_current_image)
                from recognition.config.settings import resolve_effective_detection_settings

                detection_settings = resolve_effective_detection_settings()
                min_confidence = float(detection_settings.default_threshold)
                max_faces = int(detection_settings.max_identities_per_image)
                accepted_for_image = 0
                for face in faces:
                    if float(face.confidence) < min_confidence:
                        continue
                    if accepted_for_image >= max_faces:
                        break
                    # Canonical quality: confidence + bbox size only (FIR2-BR-03)
                    detection_quality = _compute_detection_quality(
                        confidence=face.confidence,
                        bbox=face.bbox,
                    )

                    detections.append(
                        replace(
                            face,
                            media_id=media_id,
                            image_phash=image_phash,
                            landmark_quality=detection_quality,
                        )
                    )
                    accepted_for_image += 1
            except AdapterTimeoutError as exc:
                logger.error("Face detection timed out for %s after %.2fs", media_id[:20], self._timeout)
                raise DetectionTimeoutError(media_id=media_id, timeout_s=self._timeout) from exc
            except AdapterBreakerOpenError:
                logger.warning("Detection breaker open for %s", media_id[:20])
                raise
            except Exception as e:
                logger.error("Face detection failed for %s: %s", media_id[:20], e)
                raise DetectionAdapterError(media_id=media_id, error_message=str(e)) from e

        return detections


# Backwards compatibility alias - defaults to stub
FaceDetector = StubFaceDetector


__all__ = [
    "DetectionAdapterError",
    "DetectionTimeoutError",
    "FaceDetection",
    "FaceDetectorProtocol",
    "StubFaceDetector",
    "UnavailableFaceDetector",
    "InsightFaceFaceDetector",
    "FaceDetector",
    "normalize_landmarks",
    "LandmarkPoint",
    "LandmarkSet",
]

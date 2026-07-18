"""FIR-4 S2 bridge: face_pipeline (YuNet+SFace) → FIR-2 FaceDetectorProtocol.

One-pass detect→align→embed with populated FaceDetection.embedding. Decode
matches InsightFaceAdapter PIL→RGB→BGR (no EXIF transpose). Process-wide
runtime singleton, dedicated executor, wait_for_adapter + named breakers.

Heuristics: [SERVE-01][SERVE-08][EMB-01][PROV-06][RES-02][RES-04][RLSE-05][PROV-08]
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import threading
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np
from PIL import Image

from db.settings import get_database_settings
from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    FaceDetection,
    FaceDetectorProtocol,
)
from recognition.application.embedding.generator import UnavailableEmbeddingGenerator
from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.application.integrations import (
    AdapterBreakerOpenError,
    AdapterCircuitBreaker,
    AdapterTimeoutError,
    create_adapter_circuit_breaker,
    wait_for_adapter,
)
from recognition.config import get_settings
from recognition.infrastructure.face_pipeline._common import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
    RawDetection,
)
from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder, OrtYuNetDetector
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
)

logger = logging.getLogger(__name__)

# Dedicated bounded pool for sync ORT/CPU work — not the default asyncio pool.
_FACE_PIPELINE_MAX_WORKERS = 2
_FACE_PIPELINE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_FACE_PIPELINE_MAX_WORKERS,
    thread_name_prefix="face_pipeline",
)

_SHARED_LOCK = threading.Lock()
_SHARED_RUNTIME: FacePipelineRuntime | FacePipelineRuntimeUnavailableError | None = None
_SHARED_KEY: tuple[Any, ...] | None = None

FACE_PIPELINE_GENERATOR_REASON = "face_pipeline embeds in detect()"


class FacePipelineRuntimeUnavailableError(RuntimeError):
    """Cached whole-profile activation failure (atomic YuNet+SFace load)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Assignment wording alias (Unavailable outcome).
FacePipelineRuntimeUnavailable = FacePipelineRuntimeUnavailableError


@dataclass(frozen=True, slots=True)
class FacePipelineRuntime:
    """Verified YuNet + aligner + SFace unit for one process."""

    detector: OrtYuNetDetector
    aligner: FivePointAligner
    embedder: OrtSFaceEmbedder
    manifest: EmbeddingModelManifest
    models_dir: Path
    score_threshold: float
    nms_threshold: float
    top_k: int


def sface_embedding_model_manifest() -> EmbeddingModelManifest:
    """Map MODEL_MANIFEST['sface'] provenance → EmbeddingModelManifest (rg-015)."""
    entry = MODEL_MANIFEST["sface"]
    if entry.embedding_dim is None or entry.normalization is None or entry.metric is None:
        raise ValueError("MODEL_MANIFEST['sface'] missing embedding contract fields")
    return EmbeddingModelManifest(
        framework=entry.framework,
        name="sface",
        dimensions=int(entry.embedding_dim),
        normalization=entry.normalization,
        metric=entry.metric,
    )


def xywh_to_corner_bbox(bbox: Sequence[float] | np.ndarray) -> tuple[int, int, int, int]:
    """Convert OpenCV xywh bbox to corner (x1, y1, x2, y2) ints."""
    x, y, w, h = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    x1, y1 = int(x), int(y)
    x2, y2 = int(x + w), int(y + h)
    return (x1, y1, x2, y2)


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes to OpenCV BGR — InsightFaceAdapter._bytes_to_cv2 semantics.

    PIL open → convert('RGB') if mode != RGB → np.array → cv2.cvtColor RGB2BGR.
    No EXIF transpose (incumbent performs none).
    """
    pil_image = Image.open(io.BytesIO(image_bytes))
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    rgb_array = np.array(pil_image)
    return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)


def assert_three_way_embedding_dimensions(manifest: EmbeddingModelManifest) -> None:
    """Fail closed unless manifest == pgvector_dimension == identity_detection.embedding_dimension."""
    pg_dim = int(get_database_settings().pgvector_dimension)
    id_dim = int(get_settings().identity_detection.embedding_dimension)
    if not (manifest.dimensions == pg_dim == id_dim):
        raise ValueError(
            "embedding dimension mismatch (three-way guard): "
            f"manifest.dimensions={manifest.dimensions} "
            f"pgvector_dimension={pg_dim} "
            f"identity_detection.embedding_dimension={id_dim}"
        )


def face_pipeline_unavailable_generator() -> UnavailableEmbeddingGenerator:
    """Generator-protocol slot for face_pipeline profile (embeds happen in detect)."""
    return UnavailableEmbeddingGenerator(FACE_PIPELINE_GENERATOR_REASON)


def _runtime_cache_key(
    *,
    profile: str,
    models_dir: Path,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> tuple[Any, ...]:
    return (profile, str(models_dir.resolve()), float(score_threshold), float(nms_threshold), int(top_k))


def _load_face_pipeline_runtime(
    *,
    models_dir: Path,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> FacePipelineRuntime:
    """Load YuNet+SFace as one atomic unit; any failure raises (caller caches Unavailable)."""
    manifest = sface_embedding_model_manifest()
    assert_three_way_embedding_dimensions(manifest)
    detector = OrtYuNetDetector(
        models_dir=models_dir,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
    )
    aligner = FivePointAligner()
    embedder = OrtSFaceEmbedder(models_dir=models_dir)
    return FacePipelineRuntime(
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        manifest=manifest,
        models_dir=models_dir,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
    )


def get_shared_face_pipeline_runtime(
    *,
    profile: str = "face_pipeline",
    models_dir: Path | None = None,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> FacePipelineRuntime:
    """Process-wide face_pipeline runtime singleton (memo on profile+dir+thresholds).

    Double-checked lock. Failed loads cache ``FacePipelineRuntimeUnavailableError`` so a
    half-activated profile is never retried into a mixed YuNet-only state.
    """
    global _SHARED_RUNTIME, _SHARED_KEY

    root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
    key = _runtime_cache_key(
        profile=profile,
        models_dir=root,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
    )

    cached = _SHARED_RUNTIME
    if cached is not None and key == _SHARED_KEY:
        if isinstance(cached, FacePipelineRuntimeUnavailableError):
            raise cached
        return cached

    with _SHARED_LOCK:
        cached = _SHARED_RUNTIME
        if cached is not None and key == _SHARED_KEY:
            if isinstance(cached, FacePipelineRuntimeUnavailableError):
                raise cached
            return cached
        try:
            runtime = _load_face_pipeline_runtime(
                models_dir=root,
                score_threshold=score_threshold,
                nms_threshold=nms_threshold,
                top_k=top_k,
            )
        except FacePipelineRuntimeUnavailableError:
            raise
        except Exception as exc:
            reason = f"face_pipeline runtime unavailable: {exc}"
            unavailable = FacePipelineRuntimeUnavailableError(reason)
            _SHARED_RUNTIME = unavailable
            _SHARED_KEY = key
            raise unavailable from exc
        _SHARED_RUNTIME = runtime
        _SHARED_KEY = key
        return runtime


def reset_shared_face_pipeline_runtime_for_tests() -> None:
    """Clear the process singleton for isolated tests."""
    global _SHARED_RUNTIME, _SHARED_KEY
    with _SHARED_LOCK:
        _SHARED_RUNTIME = None
        _SHARED_KEY = None


class FacePipelineFaceDetector(FaceDetectorProtocol):
    """One-pass YuNet→align→SFace detector implementing FaceDetectorProtocol."""

    def __init__(
        self,
        runtime: FacePipelineRuntime,
        *,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
        breaker: AdapterCircuitBreaker | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        assert_three_way_embedding_dimensions(runtime.manifest)
        self._runtime = runtime
        if timeout is not None:
            self._timeout = float(timeout)
        else:
            self._timeout = float(get_settings().face_pipeline.timeout_s)
        self._client = client
        self._breaker = breaker or create_adapter_circuit_breaker("face_pipeline.detect")
        self._executor = executor if executor is not None else _FACE_PIPELINE_EXECUTOR

    async def _fetch_image(self, url: str) -> bytes | None:
        """Fetch image bytes from a URL (mirrors InsightFaceFaceDetector)."""
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

    def _detect_sync(self, image_bytes: bytes, media_id: str) -> list[FaceDetection]:
        """Sync one-pass path: decode → detect → align → embed."""
        try:
            bgr = decode_image_bytes(image_bytes)
        except Exception as exc:
            raise DetectionAdapterError(media_id=media_id, error_message=f"decode failed: {exc}") from exc

        raw_batches = self._runtime.detector.detect([bgr])
        raw_faces: list[RawDetection] = raw_batches[0] if raw_batches else []
        if not raw_faces:
            return []

        h, w = bgr.shape[:2]
        crops: list[np.ndarray] = []
        for face in raw_faces:
            aligned = self._runtime.aligner.align(bgr, face.landmarks)
            crops.append(aligned.crop)

        embeddings = self._runtime.embedder.embed(crops)
        model_id = self._runtime.manifest.model_id
        results: list[FaceDetection] = []
        for face, embedding in zip(raw_faces, embeddings, strict=True):
            x1, y1, x2, y2 = xywh_to_corner_bbox(face.bbox)
            # Clamp corners into image bounds for safety (still corner format).
            x1 = max(0, min(x1, w))
            y1 = max(0, min(y1, h))
            x2 = max(0, min(x2, w))
            y2 = max(0, min(y2, h))
            results.append(
                FaceDetection(
                    media_id=media_id,
                    bbox=(x1, y1, x2, y2),
                    confidence=float(face.score),
                    embedding=np.asarray(embedding, dtype=np.float32),
                    pose_pitch=None,
                    pose_yaw=None,
                    pose_roll=None,
                    model_id=model_id,
                )
            )
        return results

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        """Detect faces and return embeddings in one pass per image."""
        detections: list[FaceDetection] = []
        loop = asyncio.get_running_loop()

        for source in sources:
            if not source:
                continue

            if isinstance(source, str):
                media_id = source
                if source.startswith(("http://", "https://")):
                    image_bytes = await self._fetch_image(source)
                    if image_bytes is None:
                        continue
                else:
                    logger.warning("Non-URL string source not supported: %s", source[:50])
                    continue
            else:
                media_id = hashlib.sha256(source).hexdigest()
                image_bytes = source

            current_bytes: bytes = image_bytes
            current_media_id: str = str(media_id)

            try:

                async def detect_current(
                    payload: bytes = current_bytes,
                    mid: str = current_media_id,
                ) -> list[FaceDetection]:
                    fut = loop.run_in_executor(self._executor, self._detect_sync, payload, mid)
                    return await wait_for_adapter(
                        fut,
                        timeout_s=self._timeout,
                        adapter_name="face_pipeline.detect",
                    )

                faces = await self._breaker.call(detect_current)
                detections.extend(faces)
            except AdapterTimeoutError as exc:
                logger.error(
                    "Face detection timed out for %s after %.2fs",
                    current_media_id[:20],
                    self._timeout,
                )
                raise DetectionTimeoutError(media_id=current_media_id, timeout_s=self._timeout) from exc
            except AdapterBreakerOpenError:
                logger.warning("Detection breaker open for %s", current_media_id[:20])
                raise
            except DetectionAdapterError:
                raise
            except Exception as e:
                logger.error("Face detection failed for %s: %s", current_media_id[:20], e)
                raise DetectionAdapterError(media_id=current_media_id, error_message=str(e)) from e

        return detections


__all__ = [
    "FACE_PIPELINE_GENERATOR_REASON",
    "FacePipelineFaceDetector",
    "FacePipelineRuntime",
    "FacePipelineRuntimeUnavailable",
    "FacePipelineRuntimeUnavailableError",
    "assert_three_way_embedding_dimensions",
    "decode_image_bytes",
    "face_pipeline_unavailable_generator",
    "get_shared_face_pipeline_runtime",
    "reset_shared_face_pipeline_runtime_for_tests",
    "sface_embedding_model_manifest",
    "xywh_to_corner_bbox",
]

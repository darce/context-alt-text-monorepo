"""FIR-4 S2 bridge: face_pipeline (YuNet+SFace) → FIR-2 FaceDetectorProtocol.

One-pass detect→align→embed with populated FaceDetection.embedding. Decode
matches InsightFaceAdapter PIL→RGB→BGR (no EXIF transpose). Process-wide
runtime singleton, dedicated executor, wait_for_adapter + named breakers.

Heuristics: [SERVE-01][SERVE-08][EMB-01][PROV-06][RES-02][RES-04][RLSE-05][PROV-08]
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from db.settings import get_database_settings
from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    FaceDetection,
    FaceDetectorProtocol,
    InsightFaceFaceDetector,
    _compute_detection_quality,
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
    ZeroNormEmbeddingError,
)
from recognition.infrastructure.face_pipeline.aligner import AlignmentError, FivePointAligner
from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder, OrtYuNetDetector
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    ModelIntegrityError,
)

logger = logging.getLogger(__name__)

# Dedicated bounded pool for sync ORT/CPU work — not the default asyncio pool.
# Process-lifetime by design: reset_shared_face_pipeline_runtime_for_tests does
# not shut it down (see that hook's docstring).
_FACE_PIPELINE_MAX_WORKERS = 2
_FACE_PIPELINE_EXECUTOR = ThreadPoolExecutor(
    max_workers=_FACE_PIPELINE_MAX_WORKERS,
    thread_name_prefix="face_pipeline",
)
# Gates run_in_executor submission. Value matches executor max_workers.
# Timeouts do NOT reclaim a running worker: the slot stays held until the
# executor future completes (head-of-line residual under load) — [RES-02].
_FACE_PIPELINE_SUBMIT_SEMAPHORE = asyncio.Semaphore(_FACE_PIPELINE_MAX_WORKERS)

_SHARED_LOCK = threading.Lock()
# Single atomic snapshot: (cache_key, runtime_or_sticky_error).
_SHARED: tuple[tuple[Any, ...], FacePipelineRuntime | FacePipelineRuntimeUnavailableError] | None = None

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
    No EXIF transpose (incumbent performs none). Delegates to the real
    InsightFaceAdapter method so math cannot fork.
    """
    # Lazy import: keeps modelless unit import path free of optional cycles.
    from recognition.infrastructure.embeddings import InsightFaceAdapter

    return InsightFaceAdapter._bytes_to_cv2(InsightFaceAdapter.__new__(InsightFaceAdapter), image_bytes)


def assert_embedding_pgvector_pair() -> None:
    """Fail closed when identity_detection.embedding_dimension != pgvector_dimension.

    Profile-independent pairing guard (CR-09). Prefer settings-level check at
    RecognitionSettings load; this path covers late/env-cache drift and
    adapter construction without going through a full settings reload.
    """
    pg_dim = int(get_database_settings().pgvector_dimension)
    id_dim = int(get_settings().identity_detection.embedding_dimension)
    if id_dim != pg_dim:
        raise ValueError(
            "embedding/pgvector dimension mismatch: "
            f"identity_detection.embedding_dimension={id_dim} "
            f"pgvector_dimension={pg_dim}"
        )


def assert_three_way_embedding_dimensions(manifest: EmbeddingModelManifest) -> None:
    """Fail closed unless manifest == pgvector_dimension == identity_detection.embedding_dimension."""
    assert_embedding_pgvector_pair()
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
    pgvector_dimension: int,
    embedding_dimension: int,
) -> tuple[Any, ...]:
    return (
        profile,
        str(models_dir.resolve()),
        float(score_threshold),
        float(nms_threshold),
        int(top_k),
        int(pgvector_dimension),
        int(embedding_dimension),
    )


def _load_face_pipeline_runtime(
    *,
    models_dir: Path,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
) -> FacePipelineRuntime:
    """Load YuNet+SFace as one atomic unit; any failure raises (caller decides cache)."""
    assert_embedding_pgvector_pair()
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
    """Process-wide face_pipeline runtime singleton (memo on profile+dir+thresholds+dims).

    Double-checked lock with a single ``_SHARED`` tuple read for the fast path.
    Only ``ModelIntegrityError`` (size/hash mismatch / tamper) is sticky-cached
    as ``FacePipelineRuntimeUnavailableError``. ``ModelMissingError`` and other
    config-class failures (dim-guard ``ValueError``, missing provisioned files)
    fall through the non-sticky ``except Exception`` branch so a corrected
    env/models_dir recovers without process restart.
    """
    global _SHARED

    root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
    pg_dim = int(get_database_settings().pgvector_dimension)
    id_dim = int(get_settings().identity_detection.embedding_dimension)
    key = _runtime_cache_key(
        profile=profile,
        models_dir=root,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
        pgvector_dimension=pg_dim,
        embedding_dimension=id_dim,
    )

    # Atomic single-tuple fast-path read (CR-08).
    shared = _SHARED
    if shared is not None:
        cached_key, cached_val = shared
        if cached_key == key:
            if isinstance(cached_val, FacePipelineRuntimeUnavailableError):
                raise cached_val
            return cached_val

    with _SHARED_LOCK:
        shared = _SHARED
        if shared is not None:
            cached_key, cached_val = shared
            if cached_key == key:
                if isinstance(cached_val, FacePipelineRuntimeUnavailableError):
                    raise cached_val
                return cached_val
        try:
            runtime = _load_face_pipeline_runtime(
                models_dir=root,
                score_threshold=score_threshold,
                nms_threshold=nms_threshold,
                top_k=top_k,
            )
        except FacePipelineRuntimeUnavailableError:
            raise
        except ModelIntegrityError as exc:
            # Sticky: size/hash mismatch only (CR-03). ModelMissingError is NOT
            # a subclass and falls through to the non-sticky branch below.
            reason = f"face_pipeline runtime unavailable: {exc}"
            unavailable = FacePipelineRuntimeUnavailableError(reason)
            _SHARED = (key, unavailable)
            raise unavailable from exc
        except Exception as exc:
            # Non-sticky: dim-guard, ModelMissingError, etc. — no cache (CR-03).
            reason = f"face_pipeline runtime unavailable: {exc}"
            raise FacePipelineRuntimeUnavailableError(reason) from exc
        _SHARED = (key, runtime)
        return runtime


def reset_shared_face_pipeline_runtime_for_tests() -> None:
    """Clear the process singleton for isolated tests.

    The dedicated ``_FACE_PIPELINE_EXECUTOR`` is intentionally process-lifetime
    and is **not** shut down or replaced here. Workers may still be running when
    the runtime snapshot is cleared; tests that need a clean executor must not
    assume reset reclaims in-flight work (CR-10).
    """
    global _SHARED
    with _SHARED_LOCK:
        _SHARED = None


class FacePipelineFaceDetector(FaceDetectorProtocol):
    """One-pass YuNet→align→SFace detector implementing FaceDetectorProtocol.

    ``detect()`` submits sync ORT work via a dedicated ThreadPoolExecutor gated
    by an asyncio.Semaphore sized to ``max_workers``. A wait_for_adapter timeout
    raises ``DetectionTimeoutError`` without cancelling the worker; the semaphore
    slot is released only when the executor future completes (head-of-line
    residual under sustained timeouts — [RES-02]).
    """

    def __init__(
        self,
        runtime: FacePipelineRuntime,
        *,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
        breaker: AdapterCircuitBreaker | None = None,
        executor: ThreadPoolExecutor | None = None,
        submit_semaphore: asyncio.Semaphore | None = None,
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
        self._submit_semaphore = submit_semaphore if submit_semaphore is not None else _FACE_PIPELINE_SUBMIT_SEMAPHORE

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
        """Sync one-pass path: decode → detect → clamp/drop → align → embed."""
        try:
            bgr = decode_image_bytes(image_bytes)
        except Exception as exc:
            raise DetectionAdapterError(media_id=media_id, error_message=f"decode failed: {exc}") from exc

        # Same phash helper as InsightFaceFaceDetector (no forked math) — CR-01.
        image_phash = InsightFaceFaceDetector._compute_phash(  # type: ignore[arg-type]
            None,  # method does not use self
            image_bytes,
        )

        raw_batches = self._runtime.detector.detect([bgr])
        raw_faces: list[RawDetection] = raw_batches[0] if raw_batches else []
        if not raw_faces:
            return []

        h, w = bgr.shape[:2]
        kept: list[tuple[RawDetection, tuple[int, int, int, int]]] = []
        dropped = 0
        for face in raw_faces:
            x1, y1, x2, y2 = xywh_to_corner_bbox(face.bbox)
            # Clamp corners into image bounds for safety (still corner format).
            x1 = max(0, min(x1, w))
            y1 = max(0, min(y1, h))
            x2 = max(0, min(x2, w))
            y2 = max(0, min(y2, h))
            if x2 <= x1 or y2 <= y1:
                dropped += 1
                continue
            kept.append((face, (x1, y1, x2, y2)))

        if dropped:
            logger.debug(
                "Dropped %d degenerate bbox detection(s) for %s before align/embed",
                dropped,
                media_id[:20],
            )
        if not kept:
            return []

        # Per-face align+embed: one bad face must not fail the whole media (E2E-04).
        model_id = self._runtime.manifest.model_id
        results: list[FaceDetection] = []
        for face, bbox in kept:
            try:
                aligned = self._runtime.aligner.align(bgr, face.landmarks)
                embeddings = self._runtime.embedder.embed([aligned.crop])
                embedding = embeddings[0]
            except (AlignmentError, ZeroNormEmbeddingError) as exc:
                dropped += 1
                logger.debug(
                    "Dropped face for %s during align/embed: %s",
                    media_id[:20],
                    type(exc).__name__,
                )
                continue
            landmark_quality = _compute_detection_quality(
                confidence=float(face.score),
                pose_pitch=None,
                pose_yaw=None,
                pose_roll=None,
                bbox=bbox,
            )
            results.append(
                FaceDetection(
                    media_id=media_id,
                    bbox=bbox,
                    confidence=float(face.score),
                    embedding=np.asarray(embedding, dtype=np.float32),
                    pose_pitch=None,
                    pose_yaw=None,
                    pose_roll=None,
                    image_phash=image_phash,
                    landmark_quality=landmark_quality,
                    model_id=model_id,
                )
            )

        if dropped:
            logger.debug(
                "Dropped %d face(s) for %s (bbox clamp / align / embed)",
                dropped,
                media_id[:20],
            )
        return results

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        """Detect faces and return embeddings in one pass per image.

        Submission is gated by ``_submit_semaphore`` (== executor max_workers).
        Timeouts raise without reclaiming a still-running worker; the semaphore
        slot is released only when the executor future completes ([RES-02]).
        """
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
                    # Saturation signal: log when submit-queue wait exceeds ~50ms (E2E-07).
                    wait_started = time.perf_counter()
                    await self._submit_semaphore.acquire()
                    wait_ms = (time.perf_counter() - wait_started) * 1000.0
                    if wait_ms > 50.0:
                        logger.info(
                            "face_pipeline submit queue wait %.0fms",
                            wait_ms,
                        )
                    # Submit via concurrent.futures so the release callback tracks the
                    # real worker, not the asyncio Future that wait_for may cancel on
                    # timeout (which would free the slot while the thread still runs).
                    cfut = self._executor.submit(self._detect_sync, payload, mid)

                    def _release_on_worker_done(_f: object) -> None:
                        loop.call_soon_threadsafe(self._submit_semaphore.release)

                    cfut.add_done_callback(_release_on_worker_done)
                    afut = asyncio.wrap_future(cfut, loop=loop)
                    return await wait_for_adapter(
                        afut,
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
    "assert_embedding_pgvector_pair",
    "assert_three_way_embedding_dimensions",
    "decode_image_bytes",
    "face_pipeline_unavailable_generator",
    "get_shared_face_pipeline_runtime",
    "reset_shared_face_pipeline_runtime_for_tests",
    "sface_embedding_model_manifest",
    "xywh_to_corner_bbox",
]

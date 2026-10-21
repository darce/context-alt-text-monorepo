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
import os
import threading
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from collections import deque
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4
import json
import weakref
from typing import Any

import httpx

from recognition.shared.safe_fetch import SafeFetchError, fetch_public_image
import numpy as np

from db.settings import get_database_settings
from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    FaceDetection,
    FaceDetectorProtocol,
    InsightFaceFaceDetector,
    _compute_detection_quality,
    normalize_landmarks,
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
from recognition.infrastructure.embeddings.face_quality_factors import compute_face_quality_factors
from recognition.infrastructure.face_pipeline._common import (
    DEFAULT_NMS_THRESHOLD,
    DEFAULT_SCORE_THRESHOLD,
    DEFAULT_TOP_K,
    RawDetection,
    ZeroNormEmbeddingError,
)
from recognition.infrastructure.face_pipeline.activation import assert_space_activatable
from recognition.infrastructure.face_pipeline.aligner import (
    AlignmentError, FivePointAligner, YUNET_LANDMARK_NAMES,
)
from recognition.infrastructure.face_pipeline.model_space import ModelSpace
from recognition.infrastructure.face_pipeline.ort_adapters import (
    RETRY_MAX_SIDE_ENV, OrtSFaceEmbedder, OrtYuNetDetector, recording_tensors,
    resolve_retry_max_side, tensor_record,
)
from recognition.infrastructure.face_pipeline.loaded_session import (
    VerifiedModelBytes, SessionReceiptV1, ExecutionReceiptV1, LoadedRuntimeRecordV1,
    FrozenFaceRuntimeConfig, AdapterObservationV1, FrozenPreprocessingSpecV1,
)
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    ModelIntegrityError,
    ModelMissingError,
    numeric_runtime_fingerprint,
)
from recognition.observability.face_pipeline_metrics import FacePipelineMetricsObserver

logger = logging.getLogger(__name__)

# Dedicated bounded pool for sync ORT/CPU work — not the default asyncio pool.
# Lazy process-wide construction from RecognitionSettings.face_pipeline.max_workers
# (RECOGNITION_FACE_PIPELINE_MAX_WORKERS). reset_shared_face_pipeline_runtime_for_tests
# does not shut the pool down (see that hook's docstring). [FIR-4 finding BR-05]
_POOL_LOCK = threading.Lock()
_FACE_PIPELINE_EXECUTOR: ThreadPoolExecutor | None = None
_FACE_PIPELINE_ADMISSION: FacePipelineAdmissionGate | None = None
_FACE_PIPELINE_POOL_CAPACITY: int | None = None
# Legacy name retained only so attribute probes never see an import-time
# asyncio.Semaphore. Process admission is FacePipelineAdmissionGate.
_FACE_PIPELINE_SUBMIT_SEMAPHORE: FacePipelineAdmissionGate | None = None

_SHARED_LOCK = threading.Lock()
# Single atomic snapshot: (cache_key, runtime_or_sticky_error).
_SHARED: tuple[tuple[Any, ...], FacePipelineRuntime | FacePipelineRuntimeUnavailableError] | None = None
# Process-wide detect breaker — shared across HTTP/inline/worker build sites [RES-03].
_SHARED_DETECT_BREAKER: AdapterCircuitBreaker | None = None

FACE_PIPELINE_GENERATOR_REASON = "face_pipeline embeds in detect()"


class FacePipelineAdmissionGate:
    """Loop-agnostic process-wide admission using ``threading.BoundedSemaphore``.

    Unlike ``asyncio.Semaphore``, release does not require a live event loop, so
    residual workers completing after the caller's loop closes still free slots
    ([RES-02][RES-04][RES-15] / FIR-4 finding BR-05).
    """

    __slots__ = ("_capacity", "_sem")

    def __init__(self, capacity: int) -> None:
        n = int(capacity)
        if n < 1:
            raise ValueError(f"face pipeline admission capacity must be positive, got {capacity}")
        self._capacity = n
        self._sem = threading.BoundedSemaphore(n)

    @property
    def capacity(self) -> int:
        return self._capacity

    async def acquire(self, *, timeout_s: float) -> None:
        """Acquire one slot within ``timeout_s`` seconds; raise ``TimeoutError`` on expiry.

        Rechecks the monotonic deadline after every sleep/yield and never takes a
        permit that became free only after the caller's budget expired ([RES-02]).
        """
        if timeout_s <= 0:
            if self._sem.acquire(blocking=False):
                return
            raise TimeoutError("face pipeline admission timed out")
        deadline = time.perf_counter() + timeout_s
        if self._sem.acquire(blocking=False):
            return
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError("face pipeline admission timed out")
            # Short sleep keeps the event loop free; never call_soon_threadsafe.
            await asyncio.sleep(min(0.005, remaining))
            # Recheck after await: delayed wake must not steal a post-deadline permit.
            if deadline - time.perf_counter() <= 0:
                raise TimeoutError("face pipeline admission timed out")
            if self._sem.acquire(blocking=False):
                return

    def release(self) -> None:
        """Release one slot (thread-safe; safe after caller loop close)."""
        self._sem.release()


def _resolve_pool_capacity_from_settings() -> int:
    """Load-time validated max_workers from settings (positive integer)."""
    return int(get_settings().face_pipeline.max_workers)


def _install_process_pool(capacity: int) -> tuple[ThreadPoolExecutor, FacePipelineAdmissionGate]:
    """Replace process executor + admission under ``_POOL_LOCK`` (caller holds lock).

    Prior executors are not shut down here so residual workers are not stranded;
    callers rebind only after in-flight work completes (tests).
    """
    global _FACE_PIPELINE_EXECUTOR, _FACE_PIPELINE_ADMISSION, _FACE_PIPELINE_POOL_CAPACITY
    global _FACE_PIPELINE_SUBMIT_SEMAPHORE

    n = int(capacity)
    if n < 1:
        raise ValueError(f"face pipeline pool capacity must be positive, got {capacity}")
    executor = ThreadPoolExecutor(max_workers=n, thread_name_prefix="face_pipeline")
    gate = FacePipelineAdmissionGate(n)
    _FACE_PIPELINE_EXECUTOR = executor
    _FACE_PIPELINE_ADMISSION = gate
    _FACE_PIPELINE_POOL_CAPACITY = n
    _FACE_PIPELINE_SUBMIT_SEMAPHORE = gate
    return executor, gate


def _ensure_face_pipeline_pool() -> tuple[ThreadPoolExecutor, FacePipelineAdmissionGate]:
    """Lazy process-wide pool: executor + admission sized from settings.max_workers."""
    global _FACE_PIPELINE_EXECUTOR, _FACE_PIPELINE_ADMISSION
    with _POOL_LOCK:
        if _FACE_PIPELINE_EXECUTOR is not None and _FACE_PIPELINE_ADMISSION is not None:
            return _FACE_PIPELINE_EXECUTOR, _FACE_PIPELINE_ADMISSION
        return _install_process_pool(_resolve_pool_capacity_from_settings())


def face_pipeline_pool_max_workers() -> int:
    """Return configured process executor capacity (ensures lazy pool)."""
    with _POOL_LOCK:
        if _FACE_PIPELINE_POOL_CAPACITY is not None:
            return int(_FACE_PIPELINE_POOL_CAPACITY)
    executor, _gate = _ensure_face_pipeline_pool()
    return int(executor._max_workers)


def face_pipeline_admission_capacity() -> int:
    """Return process admission gate capacity (matches executor max_workers)."""
    _executor, gate = _ensure_face_pipeline_pool()
    return int(gate.capacity)


def reconfigure_face_pipeline_pool_from_settings() -> None:
    """Rebind process executor + admission from live ``get_settings()``.

    Safe only when no process-pool work still holds admission slots (tests rebind
    after prior work completes). Does not shut down the previous executor so any
    residual thread is not force-cancelled mid-flight.
    """
    with _POOL_LOCK:
        _install_process_pool(_resolve_pool_capacity_from_settings())


def reset_face_pipeline_pool_for_tests() -> None:
    """Test hook: rebind process pool from current settings (alias of reconfigure)."""
    reconfigure_face_pipeline_pool_from_settings()


def _observe_quality_factors(
    metrics: FacePipelineMetricsObserver | None,
    *,
    sharpness: float,
    embedding_norm: float,
    occlusion_severity: float,
) -> None:
    """Best-effort per-factor metrics (CAL-09); never break detection."""
    if metrics is None:
        return
    observe = getattr(metrics, "observe_quality_factors", None)
    if not callable(observe):
        return
    try:
        observe(
            sharpness=float(sharpness),
            embedding_norm=float(embedding_norm),
            occlusion_severity=float(occlusion_severity),
        )
    except Exception:
        pass


def _observe_submit_wait(metrics: FacePipelineMetricsObserver | None, wait_s: float) -> None:
    """Record admission wait on an injected observer; never raise to detect path."""
    if metrics is None:
        return
    try:
        metrics.observe_submit_wait(float(wait_s))
    except Exception:  # pragma: no cover - metrics must never break detect path
        logger.debug("face_pipeline submit wait metric observe failed", exc_info=True)


def _observe_admission_timeout(metrics: FacePipelineMetricsObserver | None) -> None:
    """Increment admission-timeout counter on injected observer; never raise."""
    if metrics is None:
        return
    try:
        metrics.record_admission_timeout()
    except Exception:  # pragma: no cover - metrics must never break detect path
        logger.debug("face_pipeline admission timeout metric inc failed", exc_info=True)


def _observe_faces_dropped(
    metrics: FacePipelineMetricsObserver | None,
    *,
    reason: str,
    count: int,
) -> None:
    """Meter quality drops split by reason (FIR23-05); never raise to detect path."""
    if metrics is None or count <= 0:
        return
    record = getattr(metrics, "record_faces_dropped", None)
    if record is None:
        return
    try:
        record(reason, int(count))
    except Exception:  # pragma: no cover - metrics must never break detect path
        logger.debug("face_pipeline faces_dropped metric inc failed", exc_info=True)


class FacePipelineRuntimeUnavailableError(RuntimeError):
    """Cached whole-profile activation failure (atomic YuNet+SFace load)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Assignment wording alias (Unavailable outcome).
FacePipelineRuntimeUnavailable = FacePipelineRuntimeUnavailableError


@dataclass(frozen=True, slots=True)
class FacePipelineRuntime:
    """Verified YuNet + aligner + embedder unit for one process."""

    detector: OrtYuNetDetector
    aligner: FivePointAligner
    embedder: OrtSFaceEmbedder
    manifest: EmbeddingModelManifest
    models_dir: Path
    score_threshold: float
    nms_threshold: float
    top_k: int
    embedder_models_dir: Path | None = None
    runtime_generation_id: str | None = None
    session_receipts: Any = None
    frozen_config: FrozenFaceRuntimeConfig | None = None
    artifact_identity: tuple = ()
    compatibility_sha256: str | None = None
    frozen_preprocessing_spec: Any = None


def sface_embedding_model_manifest() -> EmbeddingModelManifest:
    """Map MODEL_MANIFEST['sface'] provenance → EmbeddingModelManifest (rg-015).

    Embedding-space identity includes the numeric-relevant runtime token
    (OpenCV full version + onnxruntime major.minor; see
    ``NumericRuntimeFingerprint.space_token``) so aligner-numeric bumps and
    ORT minor bumps cannot share a ``model_id`` string while ORT patch bumps
    do not orphan rows (CVUP-1 findings LC-02 / HARM-02).
    """
    from recognition.infrastructure.face_pipeline.provenance import numeric_runtime_fingerprint

    entry = MODEL_MANIFEST["sface"]
    if entry.embedding_dim is None or entry.normalization is None or entry.metric is None:
        raise ValueError("MODEL_MANIFEST['sface'] missing embedding contract fields")
    space = numeric_runtime_fingerprint().space_token
    return EmbeddingModelManifest(
        framework=entry.framework,
        name=f"sface+{space}",
        dimensions=int(entry.embedding_dim),
        normalization=entry.normalization,
        metric=entry.metric,
    )


def auraface_embedding_model_manifest(*, _fingerprint=None) -> EmbeddingModelManifest:
    """Map MODEL_MANIFEST['auraface'] provenance → EmbeddingModelManifest (rg-015).

    Embedding-space identity includes the numeric-relevant runtime token
    (OpenCV full version + onnxruntime major.minor; see
    ``NumericRuntimeFingerprint.space_token``) so aligner-numeric bumps and
    ORT minor bumps cannot share a ``model_id`` string while ORT patch bumps
    do not orphan rows (FIR23-01 / CVUP1-GR-03). AuraFace uses the same
    ``FivePointAligner`` warp as SFace.
    """
    from recognition.infrastructure.face_pipeline.provenance import numeric_runtime_fingerprint

    entry = MODEL_MANIFEST["auraface"]
    if entry.embedding_dim is None or entry.normalization is None or entry.metric is None:
        raise ValueError("MODEL_MANIFEST['auraface'] missing embedding contract fields")
    space = (_fingerprint if _fingerprint is not None else numeric_runtime_fingerprint()).space_token
    return EmbeddingModelManifest(
        framework=entry.framework,
        name=f"auraface+{space}",
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


def _artifact_stat_identity(path: Path) -> tuple[Any, ...]:
    """Portable file identity for cache invalidation (no content hash).

    Atomic operator replace changes size and/or mtime_ns (and typically
    inode/ctime). Missing paths return a non-sticky sentinel so absence cannot
    pin a ModelIntegrityError across provisioning.
    """
    try:
        st = path.stat()
    except (FileNotFoundError, OSError):
        return ("missing",)
    # st_ino / st_ctime_ns: useful on POSIX; fall back safely where absent.
    ino = int(getattr(st, "st_ino", 0) or 0)
    ctime_ns = int(getattr(st, "st_ctime_ns", 0) or 0)
    if ctime_ns == 0:
        ctime_ns = int(st.st_ctime * 1_000_000_000)
    return (int(st.st_size), int(st.st_mtime_ns), ino, ctime_ns)


def _resolved_model_artifact_identity(
    models_dir: Path,
    *,
    embedder_models_dir: Path | None = None,
    space: ModelSpace = ModelSpace.FACE_PIPELINE,
) -> tuple[Any, ...]:
    """Detector+embedder model+license identity for shared-runtime cache keys.

    YuNet is always resolved from the face_pipeline models dir. The embedder
    (SFace or AuraFace) is resolved from ``embedder_models_dir`` when supplied.
    Includes each manifest license file so a license-only repair invalidates
    sticky ModelIntegrityError entries (FIR-PM-01 / [DRIFT-02]). Missing
    paths use the portable missing sentinel (non-sticky absence).
    """
    detector_root = Path(models_dir)
    embedder_root = Path(embedder_models_dir) if embedder_models_dir is not None else detector_root
    embedder_name = "auraface" if space is ModelSpace.AURAFACE else "sface"
    named_roots = (("yunet", detector_root), (embedder_name, embedder_root))
    parts: list[tuple[Any, ...]] = []
    for name, root in named_roots:
        entry = MODEL_MANIFEST[name]
        model_path = root / entry.file_name
        license_path = root / entry.license_file
        parts.append(
            (
                name,
                entry.file_name,
                _artifact_stat_identity(model_path),
                entry.license_file,
                _artifact_stat_identity(license_path),
            )
        )
    return tuple(parts)


def _runtime_cache_key(
    *,
    profile: ModelSpace,
    models_dir: Path,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
    pgvector_dimension: int,
    embedding_dimension: int,
    artifact_identity: tuple[Any, ...] | None = None,
    embedder_models_dir: Path | None = None,
    retry_max_side: int = 0,
) -> tuple[Any, ...]:
    detector_root = Path(models_dir)
    embedder_root = Path(embedder_models_dir) if embedder_models_dir is not None else detector_root
    artifacts = (
        artifact_identity
        if artifact_identity is not None
        else _resolved_model_artifact_identity(
            detector_root,
            embedder_models_dir=embedder_root,
            space=profile,
        )
    )
    return (
        profile,
        str(detector_root.resolve()),
        str(embedder_root.resolve()),
        float(score_threshold),
        float(nms_threshold),
        int(top_k),
        int(pgvector_dimension),
        int(embedding_dimension),
        int(retry_max_side),
        artifacts,
    )


_API_ADAPTERS = deque(maxlen=256)
_API_ADAPTERS_LOCK = threading.Lock()


def _contract_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, default=str).encode()).hexdigest()


def _frozen_detector_recipe(detector) -> dict:
    """Detector recipe; the scale-retry block exists only when enabled, so the OFF digest is unchanged."""
    recipe = {"channel_order": "BGR", "dtype": "float32", "layout": "NCHW",
              "pad_divisor": 32, "pad_value": 0, "score_threshold": detector.score_threshold,
              "nms_threshold": detector.nms_threshold, "top_k": detector.top_k}
    if detector.retry_max_side:
        recipe["scale_retry"] = {
            "max_side": detector.retry_max_side, "passes": 2, "interpolation": "INTER_AREA",
            "resize": "longer_side_to_max_side_rounded_per_axis",
            "projection": "original_pixels_with_sx_sy_from_rounded_sizes",
            "dedupe": "nms_iou_against_all_original_and_accepted_rows",
            "pass_one_rows": "unchanged_and_first", "top_k": "never_drops_pass_one",
        }
    return recipe


def _freeze_pair(detector, embedder, aligner, manifest, space, detector_dir,
                 embedder_dir, score_threshold, nms_threshold, top_k, fingerprint):
    artifacts = [getattr(adapter, "_verified_artifact", None) for adapter in (detector, embedder)]
    if not all(isinstance(artifact, VerifiedModelBytes) for artifact in artifacts):
        return {}
    generation = str(uuid4())
    config = FrozenFaceRuntimeConfig(space.value, detector_dir.resolve(), embedder_dir.resolve(),
                                     float(score_threshold), float(nms_threshold), int(top_k),
                                     manifest.dimensions, manifest.dimensions, detector.retry_max_side)
    # Retain the exact destination consumed by alignment, independent of the
    # ambient template registry. Immutable bytes also prevent setflags(write=True).
    template = aligner.dst_landmarks
    aligner.dst_landmarks = np.frombuffer(template.tobytes(), dtype=template.dtype).reshape(template.shape)
    spec = FrozenPreprocessingSpecV1(
            detector=_frozen_detector_recipe(detector),
            embedding={**asdict(artifacts[1].manifest_snapshot.preprocessing),
                       "layout": "NCHW", "dtype": "float32"},
            alignment={"template_sha256": tensor_record(aligner.dst_landmarks)["sha256"],
                          "template": aligner.dst_landmarks.tolist(), "dtype": str(aligner.dst_landmarks.dtype),
                          "estimator": "opencv_sface" if aligner.template_id == "sface-5pt-112" else "umeyama",
                          "landmark_order": YUNET_LANDMARK_NAMES,
                          "output_size": (aligner.output_size, aligner.output_size),
                          "interpolation": "INTER_LINEAR",
                          "border": "BORDER_CONSTANT", "border_value": 0},
            pipeline_normalization="l2", graph_analysis=None)
    spec_digest = spec.digest()
    receipts = {}
    identities = []
    now = datetime.now(timezone.utc)
    for adapter, artifact, root in zip((detector, embedder), artifacts, (detector_dir, embedder_dir), strict=True):
        metadata = adapter._session_metadata
        receipts[artifact.logical_name] = SessionReceiptV1(
            session_id=str(uuid4()), runtime_generation_id=generation,
            logical_model_name=artifact.logical_name, constructed_at=now,
            observed_weight_sha256=artifact.model_sha256, observed_weight_size_bytes=artifact.model_size_bytes,
            observed_license_sha256=artifact.license_sha256, observed_license_size_bytes=artifact.license_size_bytes,
            manifest_expectation_sha256=artifact.manifest_expectation_sha256,
            frozen_preprocessing_sha256=spec_digest, numeric_runtime_fingerprint=fingerprint,
            actual_providers=metadata["providers"], actual_input_metadata=metadata["inputs"],
            actual_output_metadata=metadata["outputs"],
            actual_session_options=metadata["options"], graph_analysis=None)
        identities.extend(((root / artifact.manifest_snapshot.file_name, artifact.observed_model_file_identity),
                           (root / artifact.manifest_snapshot.license_file, artifact.observed_license_file_identity)))
    compatibility = _contract_digest({"artifacts": [(a.model_sha256, a.license_sha256,
                                                    a.manifest_expectation_sha256) for a in artifacts],
                                      "preprocessing": spec_digest, "numeric": asdict(fingerprint),
                                      "model_id": manifest.model_id})
    return dict(runtime_generation_id=generation, session_receipts=MappingProxyType(receipts),
                frozen_config=config, artifact_identity=tuple(identities),
                compatibility_sha256=compatibility, frozen_preprocessing_spec=spec)


def observe_api_face_adapters(*, expected_config, captured_at):
    with _API_ADAPTERS_LOCK:
        references = tuple(_API_ADAPTERS)
    observations = []
    for reference in references:
        adapter = reference()
        if adapter is not None:
            observations.append(AdapterObservationV1(adapter._adapter_instance_id, "serving",
                adapter.loaded_runtime_record(expected_config=expected_config,
                    active_generation_id=None, captured_at=captured_at),
                adapter._last_execution_at, adapter._last_execution_at is not None))
    return tuple(observations)


def _load_face_pipeline_runtime(
    *,
    models_dir: Path,
    score_threshold: float,
    nms_threshold: float,
    top_k: int,
    space: ModelSpace = ModelSpace.FACE_PIPELINE,
    embedder_models_dir: Path | None = None,
    retry_max_side: int | None = None,
) -> FacePipelineRuntime:
    """Load YuNet + embedder as one atomic unit; any failure raises (caller decides cache)."""
    assert_space_activatable(space)
    assert_embedding_pgvector_pair()
    if retry_max_side is None:
        retry_max_side = resolve_retry_max_side(os.environ.get(RETRY_MAX_SIDE_ENV))
    fingerprint =numeric_runtime_fingerprint() if space is ModelSpace.AURAFACE else None
    if space is ModelSpace.AURAFACE:
        manifest = auraface_embedding_model_manifest(_fingerprint=fingerprint)
    else:
        manifest = sface_embedding_model_manifest()
    assert_three_way_embedding_dimensions(manifest)
    detector_dir = Path(models_dir)
    embedder_dir = Path(embedder_models_dir) if embedder_models_dir is not None else detector_dir
    try:
        detector = OrtYuNetDetector(
            models_dir=detector_dir,
            score_threshold=score_threshold,
            nms_threshold=nms_threshold,
            top_k=top_k,
            retry_max_side=retry_max_side,
            **({"acquire_verified": True} if space is ModelSpace.AURAFACE else {}),
        )
    except ModelMissingError as exc:
        raise FacePipelineRuntimeUnavailableError(
            f"face_pipeline runtime unavailable: detector missing yunet: {exc}"
        ) from exc
    aligner = FivePointAligner(space=space)
    if space is ModelSpace.AURAFACE:
        embedder = OrtSFaceEmbedder(model_name="auraface", models_dir=embedder_dir, acquire_verified=True)
    else:
        embedder = OrtSFaceEmbedder(models_dir=embedder_dir)
    return FacePipelineRuntime(
        detector=detector,
        aligner=aligner,
        embedder=embedder,
        manifest=manifest,
        models_dir=detector_dir,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
        embedder_models_dir=embedder_dir,
        **_freeze_pair(detector, embedder, aligner, manifest, space, detector_dir, embedder_dir,
                       score_threshold, nms_threshold, top_k, fingerprint),
    )


def get_shared_face_pipeline_runtime(
    *,
    profile: str | ModelSpace = ModelSpace.FACE_PIPELINE,
    models_dir: Path | None = None,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
    nms_threshold: float = DEFAULT_NMS_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
    embedder_models_dir: Path | None = None,
) -> FacePipelineRuntime:
    """Process-wide face_pipeline runtime singleton (memo on profile+dirs+thresholds+dims+artifacts).

    Double-checked lock with a single ``_SHARED`` tuple read for the fast path.
    Only ``ModelIntegrityError`` (size/hash mismatch / tamper, model or license)
    is sticky-cached as ``FacePipelineRuntimeUnavailableError`` while the
    resolved detector/embedder model+license artifact identity is unchanged.
    Operator model or license replacement (stat identity drift) invalidates the
    sticky entry and re-verifies/rebuilds. ``ModelMissingError`` and other
    config-class failures (dim-guard ``ValueError``, missing files) fall through
    the non-sticky ``except Exception`` branch so corrected env/models_dir
    recovers without process restart.

    AuraFace keeps YuNet in ``models_dir`` (face_pipeline store) and the
    embedder in ``embedder_models_dir`` (AuraFace store).
    """
    global _SHARED

    space = ModelSpace(profile)
    assert_space_activatable(space)
    root = Path(models_dir) if models_dir is not None else DEFAULT_MODELS_DIR
    embedder_root = Path(embedder_models_dir) if embedder_models_dir is not None else root
    pg_dim = int(get_database_settings().pgvector_dimension)
    id_dim = int(get_settings().identity_detection.embedding_dimension)
    retry_max_side = resolve_retry_max_side(os.environ.get(RETRY_MAX_SIDE_ENV))
    key = _runtime_cache_key(
        profile=space,
        models_dir=root,
        score_threshold=score_threshold,
        nms_threshold=nms_threshold,
        top_k=top_k,
        pgvector_dimension=pg_dim,
        embedding_dimension=id_dim,
        embedder_models_dir=embedder_root,
        retry_max_side=retry_max_side,
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
                space=space,
                embedder_models_dir=embedder_root,
                retry_max_side=retry_max_side,
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


def get_shared_face_pipeline_detect_breaker() -> AdapterCircuitBreaker:
    """Process-wide circuit breaker for face_pipeline.detect [RES-03][SERVE-01].

    Double-checked lock mirroring ``get_shared_face_pipeline_runtime`` so HTTP
    and inline build_embedding_runtime sites share open/closed state with the
    long-lived worker (not a fresh breaker per detector instance).
    """
    global _SHARED_DETECT_BREAKER

    shared = _SHARED_DETECT_BREAKER
    if shared is not None:
        return shared
    with _SHARED_LOCK:
        if _SHARED_DETECT_BREAKER is None:
            _SHARED_DETECT_BREAKER = create_adapter_circuit_breaker("face_pipeline.detect")
        return _SHARED_DETECT_BREAKER


def reset_shared_face_pipeline_runtime_for_tests() -> None:
    """Clear the process singleton for isolated tests.

    The dedicated face_pipeline executor is intentionally process-lifetime
    and is **not** shut down or replaced here. Workers may still be running when
    the runtime snapshot is cleared; tests that need a clean executor must not
    assume reset reclaims in-flight work (CR-10). Pool capacity rebind is a
    separate hook (``reconfigure_face_pipeline_pool_from_settings``).

    Also clears the shared ``face_pipeline.detect`` breaker so tests do not
    leak open/closed state across cases (local finding GROKHARM-03).
    """
    global _SHARED, _SHARED_DETECT_BREAKER
    with _SHARED_LOCK:
        _SHARED = None
        _SHARED_DETECT_BREAKER = None


class FacePipelineFaceDetector(FaceDetectorProtocol):
    """One-pass YuNet→align→SFace detector implementing FaceDetectorProtocol.

    ``detect()`` submits sync ORT work via a dedicated ThreadPoolExecutor gated
    by a loop-agnostic process admission gate sized to settings ``max_workers``.
    One overall detection deadline bounds both submit admission and executor
    result wait (no second independent full timeout window — [RES-02][RES-14]).
    A timeout raises ``DetectionTimeoutError`` without cancelling the worker; the
    admission slot is released only when the executor future completes
    (head-of-line residual under sustained timeouts — [RES-02]). Release is
    worker-owned and does not require the caller's event loop to remain open
    ([RES-04][RES-15]). Admission timeout maps through ``AdapterTimeoutError``
    so the shared breaker counts it ([RES-03][OBS-05]).
    """

    def __init__(
        self,
        runtime: FacePipelineRuntime,
        *,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
        breaker: AdapterCircuitBreaker | None = None,
        executor: ThreadPoolExecutor | None = None,
        submit_semaphore: asyncio.Semaphore | FacePipelineAdmissionGate | None = None,
        metrics: FacePipelineMetricsObserver | None = None,
    ) -> None:
        assert_three_way_embedding_dimensions(runtime.manifest)
        self._runtime = runtime
        self._adapter_instance_id = str(uuid4())
        self._call_records = threading.local()
        self._execution_receipt = None
        self._last_execution_at = None
        if timeout is not None:
            self._timeout = float(timeout)
        else:
            self._timeout = float(get_settings().face_pipeline.timeout_s)
        self._client = client
        self._breaker = breaker or create_adapter_circuit_breaker("face_pipeline.detect")
        if executor is not None:
            self._executor = executor
        else:
            self._executor, _default_gate = _ensure_face_pipeline_pool()
        if submit_semaphore is not None:
            self._submit_semaphore: asyncio.Semaphore | FacePipelineAdmissionGate = submit_semaphore
        else:
            _exec, gate = _ensure_face_pipeline_pool()
            self._submit_semaphore = gate
        # Injected process-local observer (FINALB-06). No HTTP middleware import.
        self._metrics: FacePipelineMetricsObserver | None = metrics
        if isinstance(runtime.runtime_generation_id, str):
            with _API_ADAPTERS_LOCK:
                _API_ADAPTERS.append(weakref.ref(self))

    async def _fetch_image(self, url: str) -> bytes | None:
        """Fetch image bytes from a URL (mirrors InsightFaceFaceDetector)."""
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    return await fetch_public_image(url, client=client, timeout=self._timeout)
            return await fetch_public_image(url, client=self._client, timeout=self._timeout)
        except SafeFetchError as e:
            logger.error("Failed to fetch image: %s", e)
            return None

    def _drift_reason(self, expected_config, active_generation_id):
        runtime = self._runtime
        if runtime.frozen_config != expected_config:
            return "effective_config_changed"
        if active_generation_id is not None and active_generation_id != runtime.runtime_generation_id:
            return "active_generation_changed"
        for path, identity in runtime.artifact_identity:
            current = _artifact_stat_identity(path)
            if current != identity:
                return "artifact_identity_unknown" if current == ("missing",) else "artifact_identity_changed"
        if runtime.frozen_preprocessing_spec is not None:
            expected = runtime.frozen_preprocessing_spec["alignment"]["template_sha256"]
            if tensor_record(runtime.aligner.dst_landmarks)["sha256"] != expected:
                return "preprocessing_changed"
        return None

    def loaded_runtime_record(self, *, expected_config, active_generation_id, captured_at):
        runtime = self._runtime
        generation = runtime.runtime_generation_id
        applicable = isinstance(generation, str)
        reason = self._drift_reason(expected_config, active_generation_id) if applicable else "producer_not_available"
        receipt = self._execution_receipt
        state = "not_loaded" if not applicable else "drifted" if reason else "loaded_unexercised"
        if applicable and not reason and receipt is not None and receipt.completion == "failed":
            state = "failed"
        return LoadedRuntimeRecordV1(
            producer_abi_version=1, runtime_generation_id=generation if applicable else None,
            model_id=runtime.manifest.model_id, effective_profile=runtime.frozen_config.profile if applicable else "face_pipeline",
            declared_embedding_dimension=runtime.manifest.dimensions,
            observed_embedding_dimension=receipt.normalized_output.get("dimension") if receipt else None,
            preprocessing_id=next(iter(runtime.session_receipts.values())).frozen_preprocessing_sha256 if applicable else None,
            compatibility_sha256=runtime.compatibility_sha256,
            config_sha256=_contract_digest(asdict(runtime.frozen_config)) if applicable else None,
            sessions=runtime.session_receipts or {}, frozen_preprocessing_spec=runtime.frozen_preprocessing_spec,
            execution_receipt=receipt, state=state, reason_code=reason, observed_at=captured_at)

    def _detect_sync(self, image_bytes: bytes, media_id: str) -> list[FaceDetection]:
        runtime = self._runtime
        if not isinstance(runtime.runtime_generation_id, str):
            return self._detect_sync_impl(image_bytes, media_id)
        reason = self._drift_reason(runtime.frozen_config, None)
        if reason:
            raise DetectionAdapterError(media_id=media_id, error_message=reason)
        captured_at = datetime.now(timezone.utc)
        with recording_tensors() as tensors:
            tensors["alignment"] = {}
            tensors["input_lineage"] = {}
            tensors["detections_sha256"] = None
            tensors["normalized"] = {}
            self._call_records.current = tensors
            completion = "failed"
            try:
                result = self._detect_sync_impl(image_bytes, media_id)
                completion = "executed_unreferenced" if tensors["normalized"] else "partial"
                return result
            finally:
                self._call_records.current = None
                if tensors["embedder"]:
                    recipe = runtime.frozen_preprocessing_spec["embedding"]
                    tensors["embedder"][-1].update(mean=recipe.get("input_mean", 0.0),
                                                   scale=recipe["input_scale"])
                self._execution_receipt = ExecutionReceiptV1(
                    execution_id=str(uuid4()), runtime_generation_id=runtime.runtime_generation_id,
                    detector_session_id=runtime.session_receipts["yunet"].session_id,
                    embedder_session_id=runtime.session_receipts["auraface"].session_id, captured_at=captured_at,
                    input_lineage=tensors["input_lineage"], detector_input=tensors["detector"][0] if tensors["detector"] else {},
                    detections_sha256=tensors["detections_sha256"], alignment=tensors["alignment"],
                    embedder_input=tensors["embedder"][-1] if tensors["embedder"] else {},
                    raw_output=tensors["raw"][-1] if tensors["raw"] else {},
                    normalized_output=tensors["normalized"], graph_analysis_sha256=None, completion=completion)
                self._last_execution_at = captured_at

    def _detect_sync_impl(self, image_bytes: bytes, media_id: str) -> list[FaceDetection]:
        """Sync one-pass path: decode → detect → clamp/drop → align → embed."""
        try:
            bgr = decode_image_bytes(image_bytes)
        except Exception as exc:
            raise DetectionAdapterError(media_id=media_id, error_message=f"decode failed: {exc}") from exc

        # Same phash helper as InsightFaceFaceDetector (no forked math) — CR-01.
        image_phash = InsightFaceFaceDetector._compute_phash(image_bytes)

        raw_batches = self._runtime.detector.detect([bgr])
        raw_faces: list[RawDetection] = raw_batches[0] if raw_batches else []
        records = getattr(self._call_records, "current", None)
        if records is not None:
            records["detections_sha256"] = _contract_digest([
                {"bbox": face.bbox.tolist(), "landmarks": face.landmarks.tolist(), "score": float(face.score)} for face in raw_faces])
        if not raw_faces:
            return []

        h, w = bgr.shape[:2]
        kept: list[tuple[RawDetection, tuple[int, int, int, int]]] = []
        dropped_bbox = 0
        dropped_align_embed = 0
        for face in raw_faces:
            x1, y1, x2, y2 = xywh_to_corner_bbox(face.bbox)
            # Clamp corners into image bounds for safety (still corner format).
            x1 = max(0, min(x1, w))
            y1 = max(0, min(y1, h))
            x2 = max(0, min(x2, w))
            y2 = max(0, min(y2, h))
            if x2 <= x1 or y2 <= y1:
                dropped_bbox += 1
                continue
            kept.append((face, (x1, y1, x2, y2)))

        if dropped_bbox:
            logger.debug(
                "Dropped %d degenerate bbox detection(s) for %s before align/embed",
                dropped_bbox,
                media_id[:20],
            )
            _observe_faces_dropped(
                self._metrics,
                reason="bbox_degenerate",
                count=dropped_bbox,
            )
        if not kept:
            return []

        # Per-face align+embed: one bad face must not fail the whole media (E2E-04).
        model_id = self._runtime.manifest.model_id
        results: list[FaceDetection] = []
        for face, bbox in kept:
            try:
                if records is not None:
                    records["alignment"] = {}
                    records["normalized"] = {}
                    records["embedder"].clear()
                    records["raw"].clear()
                aligned = self._runtime.aligner.align(bgr, face.landmarks)
                if records is not None:
                    records["alignment"] = {"landmarks_sha256": tensor_record(face.landmarks)["sha256"],
                        "template_sha256": tensor_record(self._runtime.aligner.dst_landmarks)["sha256"],
                        "affine_sha256": tensor_record(aligned.affine)["sha256"],
                        "crop_sha256": tensor_record(aligned.crop)["sha256"],
                        "executing_spec_sha256": self._runtime.session_receipts["auraface"].frozen_preprocessing_sha256}
                batch = self._runtime.embedder.embed([aligned.crop])
                embedding = batch.vectors[0]
                emb_norm = float(batch.norms[0])
                if records is not None:
                    records["normalized"] = dict(tensor_record(embedding), dimension=int(embedding.size),
                                                  norm=float(np.linalg.norm(embedding)))
            except (AlignmentError, ZeroNormEmbeddingError) as exc:
                dropped_align_embed += 1
                logger.debug(
                    "Dropped face for %s during align/embed: %s",
                    media_id[:20],
                    type(exc).__name__,
                )
                continue
            factors = compute_face_quality_factors(
                crop_bgr=aligned.crop,
                embedding_norm=emb_norm,
                landmarks=face.landmarks,
            )
            landmark_quality = _compute_detection_quality(
                confidence=float(face.score),
                bbox=bbox,
                occlusion_severity=factors.occlusion_severity,
            )
            # CAL-09: per-factor breakdown at the FIR-4 emit site (never one scalar).
            logger.debug(
                "face_quality_factors media_id=%s sharpness=%.4f embedding_norm=%.4f "
                "occlusion_severity=%.4f pose_yaw=%s pose_roll=%s",
                media_id[:20],
                factors.sharpness,
                factors.embedding_norm,
                factors.occlusion_severity,
                factors.pose_yaw,
                factors.pose_roll,
            )
            _observe_quality_factors(
                self._metrics,
                sharpness=factors.sharpness,
                embedding_norm=factors.embedding_norm,
                occlusion_severity=factors.occlusion_severity,
            )
            results.append(
                FaceDetection(
                    media_id=media_id,
                    bbox=bbox,
                    confidence=float(face.score),
                    embedding=np.asarray(embedding, dtype=np.float32),
                    pose_pitch=None,
                    pose_yaw=factors.pose_yaw,
                    pose_roll=factors.pose_roll,
                    image_phash=image_phash,
                    landmark_quality=landmark_quality,
                    model_id=model_id,
                    landmarks=normalize_landmarks(face.landmarks),
                    sharpness=factors.sharpness,
                    embedding_norm=factors.embedding_norm,
                    occlusion_severity=factors.occlusion_severity,
                )
            )

        if dropped_align_embed:
            _observe_faces_dropped(
                self._metrics,
                reason="align_or_embed",
                count=dropped_align_embed,
            )

        # FIR-6 S1: effective-detection-settings confidence floor + max-faces cap.
        from recognition.config.settings import resolve_effective_detection_settings

        detection_settings = resolve_effective_detection_settings()
        min_confidence = float(detection_settings.default_threshold)
        max_faces = int(detection_settings.max_identities_per_image)
        filtered = [face for face in results if float(face.confidence) >= min_confidence]
        if len(filtered) > max_faces:
            filtered = sorted(filtered, key=lambda face: face.confidence, reverse=True)[:max_faces]
        dropped_threshold_cap = len(results) - len(filtered)

        dropped_total = dropped_bbox + dropped_align_embed + dropped_threshold_cap
        if dropped_total:
            logger.debug(
                "Dropped %d face(s) for %s (bbox=%d align_embed=%d threshold_cap=%d)",
                dropped_total,
                media_id[:20],
                dropped_bbox,
                dropped_align_embed,
                dropped_threshold_cap,
            )
        return filtered

    async def _acquire_admission(self, timeout_s: float) -> None:
        """Acquire one submit slot within timeout_s; loop-agnostic for process gate."""
        gate = self._submit_semaphore
        if isinstance(gate, asyncio.Semaphore):
            await asyncio.wait_for(gate.acquire(), timeout=timeout_s)
            return
        await gate.acquire(timeout_s=timeout_s)

    def _release_admission(self) -> None:
        """Release one submit slot (sync; process gate is thread-safe)."""
        self._submit_semaphore.release()

    def _release_admission_from_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        """Worker-completion release: never requires a live loop for process gate.

        Injected ``asyncio.Semaphore`` doubles still hop via call_soon_threadsafe
        when the loop is open (constructor contract for test isolation).
        """
        gate = self._submit_semaphore
        if isinstance(gate, asyncio.Semaphore):
            try:
                loop.call_soon_threadsafe(gate.release)
            except RuntimeError:
                # Loop closed: injected asyncio.Semaphore cannot safely release
                # from a foreign thread. Process-wide path uses FacePipelineAdmissionGate.
                logger.warning(
                    "face_pipeline admission release skipped: event loop closed (injected asyncio.Semaphore)"
                )
            return
        gate.release()

    async def detect(self, sources: Iterable[bytes | str]) -> list[FaceDetection]:
        """Detect faces and return embeddings in one pass per image.

        Submission is gated by process admission capacity (== executor max_workers).
        Timeouts raise without reclaiming a still-running worker; the admission
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
                    # One overall deadline covers admission + executor wait.
                    # Do not give each stage a full independent timeout window.
                    deadline = time.perf_counter() + self._timeout
                    adapter_name = "face_pipeline.detect"

                    def _remaining() -> float:
                        return deadline - time.perf_counter()

                    def _raise_timeout(cause: BaseException | None = None) -> None:
                        err = AdapterTimeoutError(
                            adapter_name=adapter_name,
                            timeout_s=self._timeout,
                        )
                        if cause is not None:
                            raise err from cause
                        raise err

                    # Saturation signal: metrics + log when wait exceeds ~50ms.
                    wait_started = time.perf_counter()
                    admit_budget = _remaining()
                    if admit_budget <= 0:
                        _observe_submit_wait(self._metrics, 0.0)
                        _observe_admission_timeout(self._metrics)
                        _raise_timeout()
                    try:
                        await self._acquire_admission(admit_budget)
                    except TimeoutError as exc:
                        # Never acquired: do not release. Cancellation of the wait
                        # must not over-release ([RES-15]). Record wait + timeout.
                        wait_s = time.perf_counter() - wait_started
                        _observe_submit_wait(self._metrics, wait_s)
                        _observe_admission_timeout(self._metrics)
                        _raise_timeout(exc)
                    wait_s = time.perf_counter() - wait_started
                    _observe_submit_wait(self._metrics, wait_s)
                    if wait_s > 0.05:
                        logger.info(
                            "face_pipeline submit queue wait %.0fms",
                            wait_s * 1000.0,
                        )
                    # Slot held. Release only via the real concurrent worker future
                    # completion callback after a successful submit — never on
                    # timeout of the asyncio waiter ([RES-02][RES-04]).
                    # If submit fails before the callback is registered, release here.
                    callback_owns_release = False
                    try:
                        # Submit via concurrent.futures so the release callback tracks the
                        # real worker, not the asyncio Future that wait_for may cancel on
                        # timeout (which would free the slot while the thread still runs).
                        cfut = self._executor.submit(self._detect_sync, payload, mid)

                        def _release_on_worker_done(_f: object) -> None:
                            self._release_admission_from_worker(loop)

                        cfut.add_done_callback(_release_on_worker_done)
                        callback_owns_release = True
                        afut = asyncio.wrap_future(cfut, loop=loop)
                        exec_budget = _remaining()
                        if exec_budget <= 0:
                            # Worker already running; callback releases the slot.
                            _raise_timeout()
                        return await wait_for_adapter(
                            afut,
                            timeout_s=exec_budget,
                            adapter_name=adapter_name,
                        )
                    except BaseException:
                        if not callback_owns_release:
                            self._release_admission()
                        raise

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
    "FacePipelineAdmissionGate",
    "FacePipelineFaceDetector",
    "FacePipelineRuntime",
    "FacePipelineRuntimeUnavailable",
    "FacePipelineRuntimeUnavailableError",
    "assert_embedding_pgvector_pair",
    "assert_three_way_embedding_dimensions",
    "auraface_embedding_model_manifest",
    "decode_image_bytes",
    "face_pipeline_admission_capacity",
    "face_pipeline_pool_max_workers",
    "face_pipeline_unavailable_generator",
    "get_shared_face_pipeline_detect_breaker",
    "get_shared_face_pipeline_runtime",
    "reconfigure_face_pipeline_pool_from_settings",
    "reset_face_pipeline_pool_for_tests",
    "reset_shared_face_pipeline_runtime_for_tests",
    "sface_embedding_model_manifest",
    "xywh_to_corner_bbox",
]

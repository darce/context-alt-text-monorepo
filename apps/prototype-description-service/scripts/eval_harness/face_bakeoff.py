"""Candidate face bake-off walker (FIR-5 S2): YuNet → align → SFace offline.

ARCH-06: intentional fork from ``cli.fetch_run_record``. That walker is
caption-only (describe → analyze → remote identity listing). This module walks
the same manifest with **in-process** detect→align→embed only and writes §B face
run-records. Control flow (sequential loop, per-item try/except, bounded stall)
mirrors ``cli.fetch_run_record``; the caption client is not reused.

Heuristics: REF-15 (consume face_pipeline adapters), SERVE-08 (full leg
transform), EMB-01 (128D leg space only), rg-007 (per-item isolation + stall),
rg-015 (dim from resolve_sface_embedding_dim, never a 128/512 literal),
PROV-05 (no tenant / remote path).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from recognition.infrastructure.face_pipeline._common import (
    RawDetection,
    resolve_sface_embedding_dim,
)
from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
from recognition.infrastructure.face_pipeline.ort_adapters import (
    OrtSFaceEmbedder,
    OrtYuNetDetector,
)

from ._pathtext import _printable_message, _printable_path
from .face_assignment import associate_detections
from .face_metrics import named_box_name
from .face_run_record import (
    build_face_detection,
    build_face_run_item,
    build_face_run_record,
)
from .landmark_cache import LandmarkCacheProvenance, build_landmark_cache
from .manifest import GoldenManifest, _resolve_image
from .synthetic_occlusion import KIND_TO_SLICE_TAG, generate_twin_specs, render_twin

# Mirror cli.DEFAULT_STALL_LIMIT / BoundedStallError without importing cli
# (cli pulls remote_client / seed_roster — forbidden by the S2 negative-import gate).
DEFAULT_STALL_LIMIT = 5
CANDIDATE_MODEL_ID = "ort-yunet-sface"


def _printable_exc(exc: BaseException) -> str:
    """Encode exception text at this module's persisted-report boundary.

    OSError formats its filename separately from its message. Reconstructing
    it with the path-text encoder prevents PEP 383 surrogate escapes from
    leaking through the filename-bearing tail; other exceptions are encoded as
    operator messages rather than paths.
    """
    if isinstance(exc, OSError) and exc.filename is not None:
        return str(OSError(exc.errno, exc.strerror, _printable_path(exc.filename)))
    return str(_printable_message(str(exc)))


class BoundedStallError(RuntimeError):
    """Aborted after too many consecutive per-item failures (rg-007).

    Carries the partial face run-record (``aborted: true``) for diagnosis.
    """

    def __init__(self, message: str, partial_record: dict[str, Any]) -> None:
        super().__init__(message)
        self.partial_record = partial_record


class FaceDetector(Protocol):
    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]: ...


class FaceEmbedder(Protocol):
    embedding_dim: int

    def embed(self, crops: Sequence[np.ndarray]) -> np.ndarray: ...


def decode_image_bytes_bgr(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes → contiguous HxWx3 BGR uint8 (local; no embeddings import)."""
    if not image_bytes:
        raise ValueError("empty image bytes")
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cv2.imdecode failed (unsupported or corrupt image bytes)")
    if not img.flags["C_CONTIGUOUS"]:
        img = np.ascontiguousarray(img)
    return img


def _manifest_sha(manifest: GoldenManifest) -> str:
    canonical = json.dumps(manifest.model_dump(), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


def _detection_to_face(
    det: RawDetection,
    embedding: np.ndarray,
) -> dict[str, Any]:
    """Map RawDetection (.bbox/.landmarks/.score) + embedding → §B face dict."""
    bbox = np.asarray(det.bbox, dtype=np.float64).reshape(4)
    landmarks = np.asarray(det.landmarks, dtype=np.float64).reshape(5, 2)
    emb = np.asarray(embedding, dtype=np.float64).reshape(-1)
    return build_face_detection(
        bbox_px=[float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])],
        landmarks_px=[[float(landmarks[i, 0]), float(landmarks[i, 1])] for i in range(5)],
        embedding=[float(v) for v in emb],
        det_score=float(det.score),
    )


def process_image_bgr(
    image_bgr: np.ndarray,
    *,
    detector: FaceDetector,
    embedder: FaceEmbedder,
    aligner: FivePointAligner,
) -> list[dict[str, Any]]:
    """Run detect→align→embed on one BGR image; return §B faces list."""
    batch = detector.detect([image_bgr])
    detections = batch[0] if batch else []
    if not detections:
        return []
    crops: list[np.ndarray] = []
    for det in detections:
        aligned = aligner.align(image_bgr, det.landmarks)
        crops.append(aligned.crop)
    # Fused buffalo leg: pass detect-time bboxes so same-count reorder fails closed.
    if getattr(embedder, "fused_pending_box_guard", False):
        boxes = [np.asarray(det.bbox, dtype=np.float32) for det in detections]
        embeddings = embedder.embed(crops, boxes=boxes)  # type: ignore[call-arg]
    else:
        embeddings = embedder.embed(crops)
    faces: list[dict[str, Any]] = []
    for i, det in enumerate(detections):
        faces.append(_detection_to_face(det, embeddings[i]))
    return faces


def walk_face_run_record(
    manifest: GoldenManifest,
    images_dir: str | Path,
    *,
    detector: FaceDetector,
    embedder: FaceEmbedder,
    aligner: FivePointAligner | None = None,
    model_id: str = CANDIDATE_MODEL_ID,
    head_sha: str,
    limit: int | None = None,
    stall_limit: int = DEFAULT_STALL_LIMIT,
    started_at: str = "1970-01-01T00:00:00Z",
    embedding_dim: int | None = None,
    leg: str = "candidate",
    leg_mode: str | None = None,
) -> dict[str, Any]:
    """Walk manifest entries; isolate per-item failures; bound stalls (rg-007).

    Returns a ``DocKind.FACE_RUN_RECORD`` document. Raises ``BoundedStallError``
    (with ``partial_record``) after ``stall_limit`` consecutive failures.

    ``leg``/``model_id``/``embedding_dim`` are caller-supplied provenance (never
    hardcoded to the candidate — the buffalo baseline walks this same loop);
    ``leg_mode`` is stamped only when set (e.g. ``"fused"`` when the leg's
    detect/embed are one pipeline call and must not be read as separable stages).
    """
    if stall_limit < 1:
        raise ValueError(f"stall_limit must be >= 1, got {stall_limit}")
    if limit is not None and limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")

    images_root = Path(images_dir)
    entries = manifest.entries[:limit] if limit is not None else manifest.entries
    aligner = aligner if aligner is not None else FivePointAligner()
    dim = int(embedding_dim) if embedding_dim is not None else int(resolve_sface_embedding_dim())
    items: list[dict[str, Any]] = []
    consecutive_failures = 0

    def _record(*, aborted: bool = False) -> dict[str, Any]:
        provenance: dict[str, Any] = {
            "manifest_sha256": _manifest_sha(manifest),
            "head_sha": head_sha,
            "started_at": started_at,
            "leg": leg,
            "model_id": model_id,
            "embedding_dim": dim,
        }
        if leg_mode is not None:
            provenance["leg_mode"] = leg_mode
        return build_face_run_record(items, provenance=provenance, aborted=aborted)

    for entry in entries:
        entry_path = _printable_path(entry.path)
        # image_size is required on every item (score-time GT normalize); use a
        # 1×1 sentinel only when decode never produced dimensions.
        image_size: list[int] = [1, 1]
        try:
            image_path = _resolve_image(images_root, entry.path)
            if image_path is None:
                raise FileNotFoundError(
                    f"image file missing after NFC/NFD resolve: {entry_path}"
                )
            image_bytes = image_path.read_bytes()
            image_bgr = decode_image_bytes_bgr(image_bytes)
            image_size = [int(image_bgr.shape[1]), int(image_bgr.shape[0])]  # [W, H]
            faces = process_image_bgr(
                image_bgr,
                detector=detector,
                embedder=embedder,
                aligner=aligner,
            )
            item = build_face_run_item(
                media_id=entry.media_id,
                path=entry_path,
                model_id=model_id,
                embedding_dim=dim,
                image_size=image_size,
                faces=faces,
            )
        except Exception as exc:  # noqa: BLE001 — per-item isolation is the contract (rg-007)
            consecutive_failures += 1
            item = build_face_run_item(
                media_id=entry.media_id,
                path=entry_path,
                model_id=model_id,
                embedding_dim=dim,
                image_size=image_size,
                error=f"{type(exc).__name__}: {_printable_exc(exc)}",
            )
            items.append(item)
            if consecutive_failures >= stall_limit:
                raise BoundedStallError(
                    f"{consecutive_failures} consecutive item failures "
                    f"(last: {entry_path}); aborting run",
                    partial_record=_record(aborted=True),
                ) from exc
        else:
            consecutive_failures = 0
            items.append(item)

    return _record()


def build_occlusion_twin_pairs(
    manifest: GoldenManifest,
    images_dir: str | Path,
    *,
    detector: FaceDetector,
    embedder: FaceEmbedder,
    aligner: FivePointAligner | None = None,
    seed: int = 0,
    limit: int | None = None,
    cache_detector: FaceDetector | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Synthetic occlusion twin pass (FIR5GL-01 / §D): specs → render → re-detect+embed.

    Per entry with named GT boxes: build the frozen landmark cache over the
    UN-occluded original (pinned-YuNet family, PROV-01 — placement never reads
    the leg live), generate twin specs (every cache-detected named roster face ×
    kinds), render each twin, run the SAME leg detect→align→embed on the
    occluded pixels, and §C-associate re-detections back to the entry's GT
    boxes. The twin's re-detected embedding is the §C pair whose ``gt_index``
    equals the spec's source box; no such pair → ``embedding=None`` (re-detect
    miss, scored as a failure inside the eligible frame, EMB-03).

    Returns ``(pairs_by_tag, twin_pass_provenance)``. Pairs are DOCUMENT-level
    inputs for ``occlusion_pairs_by_tag`` — never run-record items (EVAL-16
    headline firewall). Per-entry failures are isolated into
    ``provenance["errors"]`` (rg-007 spirit): one broken image drops its own
    twins, visible in the report as reduced eligibility, and never halts the
    pass.

    ``cache_detector`` (default: the leg ``detector``) builds the frozen
    landmark cache. Non-candidate legs (buffalo) MUST pass the pinned
    candidate-family YuNet here (``build_pinned_cache_detector``) so the twin
    universe is the SAME for both legs (EXP-08 disclosure). Twin-pass
    ``landmark_cache`` provenance is derived from the injected cache detector
    (rg-015) — never hardcoded to pinned-YuNet when another detector is used.
    """
    images_root = Path(images_dir)
    cache_det = cache_detector if cache_detector is not None else detector
    aligner = aligner if aligner is not None else FivePointAligner()
    entries = manifest.entries[:limit] if limit is not None else manifest.entries
    pairs_by_tag: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    n_specs = 0
    n_cached = 0
    for entry in entries:
        # Namedness predicate (not raw truthiness): whitespace-only / Cf-only
        # names are anonymous — any(box.name) would spuriously open the twin
        # universe for corpora with no actually-named boxes (wE4 residual / wF2).
        if not any(named_box_name(box) for box in entry.face_boxes):
            continue  # no named GT faces → no twin universe on this entry
        entry_path = _printable_path(entry.path)
        try:
            image_path = _resolve_image(images_root, entry.path)
            if image_path is None:
                raise FileNotFoundError(
                    f"image file missing after NFC/NFD resolve: {entry_path}"
                )
            image_bgr = decode_image_bytes_bgr(image_path.read_bytes())
            width, height = int(image_bgr.shape[1]), int(image_bgr.shape[0])
            cache = build_landmark_cache(
                images_by_media={entry.media_id: image_bgr},
                gt_by_media={entry.media_id: list(entry.face_boxes)},
                detector=cache_det,
            )
            n_cached += len(cache.entries)
            specs = generate_twin_specs(cache, seed=seed)
            n_specs += len(specs)
            for spec in specs:
                twin_bgr = render_twin(image_bgr, spec)
                faces = process_image_bgr(
                    twin_bgr,
                    detector=detector,
                    embedder=embedder,
                    aligner=aligner,
                )
                assoc = associate_detections(
                    [f["bbox_px"] for f in faces],
                    list(entry.face_boxes),
                    [width, height],
                )
                embedding: list[float] | None = None
                for pair in assoc.pairs:
                    if pair.gt_index == spec.box_index:
                        embedding = [float(v) for v in faces[pair.det_index]["embedding"]]
                        break
                tag = KIND_TO_SLICE_TAG[spec.kind].value
                pairs_by_tag.setdefault(tag, []).append(
                    {
                        "media_id": spec.media_id,
                        "box_index": spec.box_index,
                        "true_name": spec.true_name,
                        "kind": spec.kind,
                        "embedding": embedding,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — per-entry isolation (rg-007)
            errors.append(f"{entry_path}: {type(exc).__name__}: {_printable_exc(exc)}")
    provenance: dict[str, Any] = {
        "seed": int(seed),
        "n_twin_specs": n_specs,
        "n_cached_landmarks": n_cached,
        "n_pairs": sum(len(v) for v in pairs_by_tag.values()),
        "n_re_detect_miss": sum(
            1 for pairs in pairs_by_tag.values() for p in pairs if p["embedding"] is None
        ),
        "landmark_cache": _cache_provenance_from_detector(cache_det).to_dict(),
        "errors": errors,
    }
    return pairs_by_tag, provenance


def _cache_provenance_from_detector(cache_det: Any) -> LandmarkCacheProvenance:
    """Derive landmark-cache provenance from the injected detector (rg-015).

    Preference order:
    1. ``landmark_cache_provenance`` attribute (``LandmarkCacheProvenance`` or dict)
    2. ``model_id`` + ``weights_sha256`` attributes on the detector
    3. ``OrtYuNetDetector`` → pinned candidate-family YuNet
    """
    prov = getattr(cache_det, "landmark_cache_provenance", None)
    if isinstance(prov, LandmarkCacheProvenance):
        return prov
    if isinstance(prov, dict):
        return LandmarkCacheProvenance.from_dict(prov)
    model_id = getattr(cache_det, "model_id", None)
    weights = getattr(cache_det, "weights_sha256", None)
    if model_id is not None and weights is not None:
        return LandmarkCacheProvenance(model_id=str(model_id), weights_sha256=str(weights))
    if isinstance(cache_det, OrtYuNetDetector):
        return LandmarkCacheProvenance.pinned_yunet()
    raise TypeError(
        "cache_detector must expose landmark_cache_provenance, "
        "(model_id + weights_sha256), or be OrtYuNetDetector for pinned-YuNet "
        f"default; got {type(cache_det).__name__}"
    )


def build_candidate_leg(
    *,
    models_dir: Path | None = None,
) -> tuple[OrtYuNetDetector, FivePointAligner, OrtSFaceEmbedder]:
    """Construct the ACX-owned candidate leg (OrtYuNet + FivePoint + OrtSFace)."""
    detector = OrtYuNetDetector(models_dir=models_dir)
    aligner = FivePointAligner()
    embedder = OrtSFaceEmbedder(models_dir=models_dir)
    return detector, aligner, embedder


def build_pinned_cache_detector(*, models_dir: Path | None = None) -> OrtYuNetDetector:
    """Pinned candidate-family YuNet for the frozen twin landmark cache.

    Non-candidate legs pass this to ``build_occlusion_twin_pairs`` so occlusion
    twin eligibility stays conditioned on the SAME candidate-family cache for
    every leg (EXP-08 / ``LANDMARK_CACHE_LEG_ASYMMETRY_DISCLOSURE``).
    Stamps ``landmark_cache_provenance`` so twin-pass provenance stays truthful
    (rg-015) even when other detectors are injected in tests.
    """
    det = OrtYuNetDetector(models_dir=models_dir)
    det.landmark_cache_provenance = LandmarkCacheProvenance.pinned_yunet()  # type: ignore[attr-defined]
    return det


__all__ = [
    "BoundedStallError",
    "CANDIDATE_MODEL_ID",
    "DEFAULT_STALL_LIMIT",
    "FaceDetector",
    "FaceEmbedder",
    "build_candidate_leg",
    "build_occlusion_twin_pairs",
    "build_pinned_cache_detector",
    "decode_image_bytes_bgr",
    "process_image_bgr",
    "walk_face_run_record",
]

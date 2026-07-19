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

from .face_run_record import (
    build_face_detection,
    build_face_run_item,
    build_face_run_record,
)
from .manifest import GoldenManifest, _resolve_image

# Mirror cli.DEFAULT_STALL_LIMIT / BoundedStallError without importing cli
# (cli pulls remote_client / seed_roster — forbidden by the S2 negative-import gate).
DEFAULT_STALL_LIMIT = 5
CANDIDATE_MODEL_ID = "ort-yunet-sface"


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
) -> dict[str, Any]:
    """Walk manifest entries; isolate per-item failures; bound stalls (rg-007).

    Returns a ``DocKind.FACE_RUN_RECORD`` document. Raises ``BoundedStallError``
    (with ``partial_record``) after ``stall_limit`` consecutive failures.
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
            "leg": "candidate",
            "model_id": model_id,
            "embedding_dim": dim,
        }
        return build_face_run_record(items, provenance=provenance, aborted=aborted)

    for entry in entries:
        image_path = _resolve_image(images_root, entry.path)
        # image_size is required on every item (score-time GT normalize); use a
        # 1×1 sentinel only when decode never produced dimensions.
        image_size: list[int] = [1, 1]
        try:
            if image_path is None:
                raise FileNotFoundError(f"image file missing after NFC/NFD resolve: {entry.path}")
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
                path=entry.path,
                model_id=model_id,
                embedding_dim=dim,
                image_size=image_size,
                faces=faces,
            )
        except Exception as exc:  # noqa: BLE001 — per-item isolation is the contract (rg-007)
            consecutive_failures += 1
            item = build_face_run_item(
                media_id=entry.media_id,
                path=entry.path,
                model_id=model_id,
                embedding_dim=dim,
                image_size=image_size,
                error=f"{type(exc).__name__}: {exc}",
            )
            items.append(item)
            if consecutive_failures >= stall_limit:
                raise BoundedStallError(
                    f"{consecutive_failures} consecutive item failures "
                    f"(last: {entry.path}); aborting run",
                    partial_record=_record(aborted=True),
                ) from exc
        else:
            consecutive_failures = 0
            items.append(item)

    return _record()


def build_candidate_leg(
    *,
    models_dir: Path | None = None,
) -> tuple[OrtYuNetDetector, FivePointAligner, OrtSFaceEmbedder]:
    """Construct the ACX-owned candidate leg (OrtYuNet + FivePoint + OrtSFace)."""
    detector = OrtYuNetDetector(models_dir=models_dir)
    aligner = FivePointAligner()
    embedder = OrtSFaceEmbedder(models_dir=models_dir)
    return detector, aligner, embedder


__all__ = [
    "BoundedStallError",
    "CANDIDATE_MODEL_ID",
    "DEFAULT_STALL_LIMIT",
    "FaceDetector",
    "FaceEmbedder",
    "build_candidate_leg",
    "decode_image_bytes_bgr",
    "process_image_bgr",
    "walk_face_run_record",
]

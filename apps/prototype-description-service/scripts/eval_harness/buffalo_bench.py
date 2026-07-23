"""Buffalo_l reference leg for face bake-off (FIR-5 S2) — eval-only, SC-1.

License isolation (hard rule):
- Import gated by ``ACX_EVAL_BENCH=1``; guard fires **before** insightface loads
  so unit tests pass without the ``[bench]`` extra installed.
- Imports ``insightface`` **directly** — never
  ``recognition.infrastructure.embeddings.InsightFaceAdapter``,
  ``get_shared_insightface_adapter``, or
  ``recognition.infrastructure.embeddings.runtime_factory``.
- Never ``RemoteSceneClient`` / ``face_pass`` / ``seed_roster`` / tenant paths.
- Emits the same §B face run-record schema as the candidate leg (512D, JSON only).
- PROV-01: buffalo run-records are non-commercial derived artifacts — stay in
  git-ignored ``out/``, never promote to ``docs/tasks/**``.

Heuristics: PROV-05 (limit prediction surface / license isolation), EMB-01
(512D leg space only — never crossed with 128D), PROV-01 (raw-512D non-promotion).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from recognition.infrastructure.face_pipeline._common import RawDetection

from .face_run_record import build_face_detection, build_face_run_item

_ENV_FLAG = "ACX_EVAL_BENCH"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
BUFFALO_MODEL_ID = "buffalo_l"
# Buffalo_l / InsightFace recognition embedding width (eval-only reference leg).
BUFFALO_EMBEDDING_DIM = 512
# Provenance marker: buffalo detect+embed run as ONE insightface pipeline call
# (FaceAnalysis.get), never as separable stages (see BuffaloFusedLeg).
BUFFALO_LEG_MODE = "fused"


class BuffaloBenchGuardError(RuntimeError):
    """Raised when buffalo_bench is imported without the eval-bench env flag."""


def _env_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").strip().lower() in _TRUTHY


def _require_eval_bench() -> None:
    """Fail closed unless ACX_EVAL_BENCH enables the eval-only buffalo path."""
    if not _env_enabled():
        raise BuffaloBenchGuardError(
            f"{_ENV_FLAG}=1 is required to import scripts.eval_harness.buffalo_bench "
            "(eval-only buffalo_l reference; SC-1 license isolation). "
            "Install the [bench] extra and set the env flag only for offline bake-off runs."
        )


# Env guard fires BEFORE insightface import so tests need no [bench] install.
_require_eval_bench()

# Lazy: module import succeeds with ACX_EVAL_BENCH=1 even if insightface is absent
# (negative-import graph + source gates still run). Runtime entry points load it.
_insightface_mod: Any | None = None


def _load_insightface() -> Any:
    """Import insightface only after the env guard (and only when a leg runs)."""
    global _insightface_mod
    if _insightface_mod is not None:
        return _insightface_mod
    try:
        import insightface  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "insightface is required for buffalo_bench; install the [bench] extra "
            '(e.g. `uv sync --extra bench`) and keep ACX_EVAL_BENCH=1'
        ) from exc
    _insightface_mod = insightface
    return insightface


def _resolve_insightface_root() -> str | None:
    """Model-root env resolution: INSIGHTFACE_CACHE_DIR → INSIGHTFACE_HOME → None.

    None → insightface's own default (``~/.insightface``). Mirrors
    ``recognition.config.settings._resolve_insightface_cache_root`` WITHOUT
    importing recognition config (S2 negative-import isolation keeps this
    module's closure free of runtime settings/db imports). FaceAnalysis expects
    the parent of ``models/``: root ``X`` → weights at ``X/models/buffalo_l/``.
    """
    for var in ("INSIGHTFACE_CACHE_DIR", "INSIGHTFACE_HOME"):
        raw = os.environ.get(var, "").strip()
        if raw:
            return raw
    return None


def _build_face_analysis() -> Any:
    """Construct + prepare a CPU FaceAnalysis(buffalo_l) honoring the env root."""
    _load_insightface()
    from insightface.app import FaceAnalysis  # type: ignore[import-untyped]

    kwargs: dict[str, Any] = {"name": BUFFALO_MODEL_ID, "providers": ["CPUExecutionProvider"]}
    root = _resolve_insightface_root()
    if root is not None:
        kwargs["root"] = root
    app = FaceAnalysis(**kwargs)
    app.prepare(ctx_id=-1, det_size=(640, 640))
    return app


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows; raise on zero/non-finite norms (no silent zero-fill)."""
    arr = np.asarray(vectors, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0.0):
        raise ValueError(f"buffalo embedding has zero/non-finite L2 norm: {norms.reshape(-1)}")
    return (arr / norms).astype(np.float32, copy=False)


def _face_bbox_xywh(face: Any) -> list[float]:
    """InsightFace Face.bbox (xyxy) → detector-verbatim xywh pixel-corner floats."""
    bbox = np.asarray(face.bbox, dtype=np.float64).reshape(-1)
    if bbox.size != 4:
        raise ValueError(f"buffalo face bbox must be length 4, got {bbox.size}")
    x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    return [x1, y1, x2 - x1, y2 - y1]


def _face_landmarks5(face: Any) -> np.ndarray:
    """InsightFace Face.kps → (5, 2) float64.

    Index-compatible with the walker's YuNet order contract: both SCRFD kps and
    YuNet landmarks are [image-left eye, image-right eye, nose, image-left mouth,
    image-right mouth] — the naming differs (anatomical vs viewer) but the
    per-index image positions match the same canonical 112 template row.
    """
    kps = getattr(face, "kps", None)
    if kps is None:
        raise ValueError("buffalo face missing kps (5 landmarks)")
    return np.asarray(kps, dtype=np.float64).reshape(5, 2)


def _face_embedding_vector(face: Any, *, embedding_dim: int) -> np.ndarray:
    """InsightFace Face → L2 unit embedding row (float64), dim-gated (rg-015)."""
    emb = getattr(face, "embedding", None)
    if emb is None:
        normed = getattr(face, "normed_embedding", None)
        if normed is None:
            raise ValueError("buffalo face missing embedding")
        # Already L2'd by insightface when normed_embedding is present.
        emb_vec = np.asarray(normed, dtype=np.float64).reshape(-1)
    else:
        emb_vec = np.asarray(
            l2_normalize(np.asarray(emb, dtype=np.float64).reshape(1, -1))[0], dtype=np.float64
        )
    if emb_vec.size != embedding_dim:
        raise ValueError(f"buffalo embedding dim {emb_vec.size} != {embedding_dim}")
    return emb_vec


def _face_det_score(face: Any) -> float:
    return float(getattr(face, "det_score", getattr(face, "prob", 0.0)))


def faces_from_insightface_results(
    faces: Sequence[Any],
    *,
    embedding_dim: int = BUFFALO_EMBEDDING_DIM,
) -> list[dict[str, Any]]:
    """Map insightface Face objects → §B face dicts (pixel bbox/landmarks + L2 emb)."""
    out: list[dict[str, Any]] = []
    for face in faces:
        landmarks = _face_landmarks5(face)
        emb_vec = _face_embedding_vector(face, embedding_dim=embedding_dim)
        out.append(
            build_face_detection(
                bbox_px=_face_bbox_xywh(face),
                landmarks_px=[[float(landmarks[i, 0]), float(landmarks[i, 1])] for i in range(5)],
                embedding=[float(v) for v in emb_vec],
                det_score=_face_det_score(face),
            )
        )
    return out


class FusedLegProtocolError(RuntimeError):
    """detect()/embed() called out of the fused per-image sequence (BuffaloFusedLeg)."""


@dataclass(frozen=True)
class _PlaceholderAlignment:
    """Shape stand-in for FivePointAligner's AlignmentResult (crop attr only)."""

    crop: np.ndarray


class FusedPlaceholderAligner:
    """Walker-slot aligner for the fused buffalo leg — preserves crop COUNT only.

    Buffalo's recognizer aligns internally (ArcFace norm_crop inside
    ``FaceAnalysis.get``); the walker's align step must not feed it
    SFace-canonical crops. This placeholder keeps the walker loop shape
    (one crop per detection so ``embed()`` can cross-check counts) while the
    pixels are never read.
    """

    _CROP = np.zeros((112, 112, 3), dtype=np.uint8)

    def align(self, image: np.ndarray, landmarks: np.ndarray) -> _PlaceholderAlignment:
        return _PlaceholderAlignment(crop=self._CROP)


class BuffaloFusedLeg:
    """FaceDetector + FaceEmbedder protocol adapter over InsightFace buffalo_l.

    DESIGN — fused, not separable (``leg_mode="fused"``): buffalo's recognition
    model requires its OWN ArcFace alignment keyed to its detector's kps;
    embedding walker-supplied SFace-canonical crops would change buffalo's
    operating mode and misattribute alignment error to the incumbent. So
    ``detect()`` runs ``FaceAnalysis.get()`` ONCE per image (detect + align +
    embed inside insightface) and caches the embeddings in detection order;
    ``embed()`` serves that cache and ignores crop PIXELS (crop COUNT is still
    cross-checked, and out-of-sequence calls fail closed). Provenance stamps
    ``leg_mode="fused"`` so detect/embed are never read as separable stages.

    PROV-01: run-records produced through this leg hold 512D embeddings of
    private images — they stay in git-ignored ``out/``; only score reports are
    promoted to ``benchmarks/results/``.
    """

    leg_mode = BUFFALO_LEG_MODE
    model_id = BUFFALO_MODEL_ID

    def __init__(self, *, app: Any | None = None, embedding_dim: int = BUFFALO_EMBEDDING_DIM) -> None:
        self._app = app if app is not None else _build_face_analysis()
        self.embedding_dim = int(embedding_dim)
        self._pending: list[np.ndarray] | None = None

    def detect(self, images: Sequence[np.ndarray]) -> list[list[RawDetection]]:
        """Fused pass: detections returned now, embeddings cached for embed()."""
        batches: list[list[RawDetection]] = []
        pending: list[np.ndarray] = []
        for image in images:
            faces = self._app.get(image)
            dets: list[RawDetection] = []
            for face in faces:
                dets.append(
                    RawDetection(
                        bbox=np.asarray(_face_bbox_xywh(face), dtype=np.float32),
                        landmarks=_face_landmarks5(face).astype(np.float32),
                        score=_face_det_score(face),
                    )
                )
                pending.append(_face_embedding_vector(face, embedding_dim=self.embedding_dim))
            batches.append(dets)
        self._pending = pending
        return batches

    def embed(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        """Serve the embeddings cached by the immediately-preceding detect()."""
        if self._pending is None:
            raise FusedLegProtocolError(
                "embed() before detect(): the fused buffalo leg serves embeddings cached by "
                "detect() on the same image (leg_mode='fused')"
            )
        pending, self._pending = self._pending, None
        if len(crops) != len(pending):
            raise FusedLegProtocolError(
                f"fused embed() got {len(crops)} crops but detect() cached {len(pending)} "
                "detections; detect() and embed() must come from the same image pass"
            )
        if not pending:
            return np.zeros((0, self.embedding_dim), dtype=np.float32)
        return np.stack(pending, axis=0).astype(np.float32, copy=False)


def build_baseline_leg(
    *,
    app: Any | None = None,
    embedding_dim: int = BUFFALO_EMBEDDING_DIM,
) -> tuple[BuffaloFusedLeg, FusedPlaceholderAligner, BuffaloFusedLeg]:
    """Construct the buffalo baseline leg (mirror of ``build_candidate_leg``).

    Returns ``(detector, aligner, embedder)`` where detector and embedder are
    the SAME fused adapter instance (see ``BuffaloFusedLeg``) and the aligner is
    a placeholder — alignment happens inside insightface.
    """
    leg = BuffaloFusedLeg(app=app, embedding_dim=embedding_dim)
    return leg, FusedPlaceholderAligner(), leg


def process_image_bgr_buffalo(
    image_bgr: np.ndarray,
    *,
    app: Any | None = None,
    embedding_dim: int = BUFFALO_EMBEDDING_DIM,
) -> list[dict[str, Any]]:
    """Run buffalo_l detect+embed on one BGR image; return §B faces list."""
    if app is None:
        app = _build_face_analysis()
    faces = app.get(image_bgr)
    return faces_from_insightface_results(faces, embedding_dim=embedding_dim)


def build_buffalo_run_item(
    *,
    media_id: int,
    path: str,
    image_bgr: np.ndarray,
    app: Any | None = None,
    model_id: str = BUFFALO_MODEL_ID,
    embedding_dim: int = BUFFALO_EMBEDDING_DIM,
    error: str | None = None,
) -> dict[str, Any]:
    """Build one §B face run item for the buffalo reference leg."""
    h, w = int(image_bgr.shape[0]), int(image_bgr.shape[1])
    if error is not None:
        return build_face_run_item(
            media_id=media_id,
            path=path,
            model_id=model_id,
            embedding_dim=embedding_dim,
            image_size=[w, h],
            error=error,
        )
    faces = process_image_bgr_buffalo(image_bgr, app=app, embedding_dim=embedding_dim)
    return build_face_run_item(
        media_id=media_id,
        path=path,
        model_id=model_id,
        embedding_dim=embedding_dim,
        image_size=[w, h],
        faces=faces,
    )


__all__ = [
    "BUFFALO_EMBEDDING_DIM",
    "BUFFALO_LEG_MODE",
    "BUFFALO_MODEL_ID",
    "BuffaloBenchGuardError",
    "BuffaloFusedLeg",
    "FusedLegProtocolError",
    "FusedPlaceholderAligner",
    "build_baseline_leg",
    "build_buffalo_run_item",
    "faces_from_insightface_results",
    "l2_normalize",
    "process_image_bgr_buffalo",
]

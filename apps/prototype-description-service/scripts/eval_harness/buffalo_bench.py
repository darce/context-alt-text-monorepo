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
from typing import Any

import numpy as np

from .face_run_record import build_face_detection, build_face_run_item

_ENV_FLAG = "ACX_EVAL_BENCH"
_TRUTHY = frozenset({"1", "true", "yes", "on"})
BUFFALO_MODEL_ID = "buffalo_l"
# Buffalo_l / InsightFace recognition embedding width (eval-only reference leg).
BUFFALO_EMBEDDING_DIM = 512


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


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """L2-normalize rows; raise on zero/non-finite norms (no silent zero-fill)."""
    arr = np.asarray(vectors, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if not np.all(np.isfinite(norms)) or np.any(norms == 0.0):
        raise ValueError(f"buffalo embedding has zero/non-finite L2 norm: {norms.reshape(-1)}")
    return (arr / norms).astype(np.float32, copy=False)


def faces_from_insightface_results(
    faces: Sequence[Any],
    *,
    embedding_dim: int = BUFFALO_EMBEDDING_DIM,
) -> list[dict[str, Any]]:
    """Map insightface Face objects → §B face dicts (pixel bbox/landmarks + L2 emb)."""
    out: list[dict[str, Any]] = []
    for face in faces:
        bbox = np.asarray(getattr(face, "bbox"), dtype=np.float64).reshape(-1)
        if bbox.size != 4:
            raise ValueError(f"buffalo face bbox must be length 4, got {bbox.size}")
        # InsightFace Face.bbox is xyxy; convert to detector-verbatim xywh pixel-corner.
        x1, y1, x2, y2 = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        bbox_px = [x1, y1, x2 - x1, y2 - y1]

        kps = getattr(face, "kps", None)
        if kps is None:
            raise ValueError("buffalo face missing kps (5 landmarks)")
        landmarks = np.asarray(kps, dtype=np.float64).reshape(5, 2)
        landmarks_px = [[float(landmarks[i, 0]), float(landmarks[i, 1])] for i in range(5)]

        emb = getattr(face, "embedding", None)
        if emb is None:
            normed = getattr(face, "normed_embedding", None)
            if normed is None:
                raise ValueError("buffalo face missing embedding")
            emb_vec = np.asarray(normed, dtype=np.float64).reshape(-1)
            # Already L2'd by insightface when normed_embedding is present.
            if emb_vec.size != embedding_dim:
                raise ValueError(f"buffalo embedding dim {emb_vec.size} != {embedding_dim}")
            embedding = [float(v) for v in emb_vec]
        else:
            emb_vec = l2_normalize(np.asarray(emb, dtype=np.float64).reshape(1, -1))[0]
            if emb_vec.size != embedding_dim:
                raise ValueError(f"buffalo embedding dim {emb_vec.size} != {embedding_dim}")
            embedding = [float(v) for v in emb_vec]

        det_score = float(getattr(face, "det_score", getattr(face, "prob", 0.0)))
        out.append(
            build_face_detection(
                bbox_px=bbox_px,
                landmarks_px=landmarks_px,
                embedding=embedding,
                det_score=det_score,
            )
        )
    return out


def process_image_bgr_buffalo(
    image_bgr: np.ndarray,
    *,
    app: Any | None = None,
    embedding_dim: int = BUFFALO_EMBEDDING_DIM,
) -> list[dict[str, Any]]:
    """Run buffalo_l detect+embed on one BGR image; return §B faces list."""
    if app is None:
        insightface = _load_insightface()
        from insightface.app import FaceAnalysis  # type: ignore[import-untyped]

        app = FaceAnalysis(name=BUFFALO_MODEL_ID, providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(640, 640))
        _ = insightface  # mark used after load
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
    "BUFFALO_MODEL_ID",
    "BuffaloBenchGuardError",
    "build_buffalo_run_item",
    "faces_from_insightface_results",
    "l2_normalize",
    "process_image_bgr_buffalo",
]

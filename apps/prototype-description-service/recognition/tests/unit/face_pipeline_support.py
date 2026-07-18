"""Shared helpers + module-scoped fixtures for face_pipeline unit tests (BR-08).

Centralizes _MODELS_PRESENT / skip strings / loaders / dim so the three
test_face_pipeline_*.py files cannot drift (REF-19, sr-007).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _SERVICE_ROOT / "recognition" / "tests" / "fixtures" / "face_pipeline"

MODELS_PRESENT = (
    (DEFAULT_MODELS_DIR / MODEL_MANIFEST["yunet"].file_name).is_file()
    and (DEFAULT_MODELS_DIR / MODEL_MANIFEST["sface"].file_name).is_file()
)
MODELS_SKIP = (
    "FIR-3 face models missing under recognition/infrastructure/face_pipeline/models/ — "
    "run: uv run python scripts/fetch_face_pipeline_models.py "
    f"(expected yunet={MODEL_MANIFEST['yunet'].file_name}, "
    f"sface={MODEL_MANIFEST['sface'].file_name})"
)

# Manifest dim is the only allowed embedding-size constant (sr-007 / rg-015).
SFACE_EMBEDDING_DIM = int(MODEL_MANIFEST["sface"].embedding_dim)  # type: ignore[arg-type]

# Back-compat aliases used by existing test modules.
_MODELS_PRESENT = MODELS_PRESENT
_MODELS_SKIP = MODELS_SKIP


def load_json(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def load_generate_goldens():
    gen_path = _FIXTURE_DIR / "generate_goldens.py"
    spec = importlib.util.spec_from_file_location("face_pipeline_generate_goldens", gen_path)
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def run_import_purity_check(
    *,
    import_stmt: str,
    forbidden_prefixes: tuple[str, ...],
    required_modules: tuple[str, ...] = (),
    forbidden_modules: tuple[str, ...] = (),
) -> None:
    """Subprocess import purity probe (shared by opencv_ref / ort / _common)."""
    required_checks = "\n".join(
        f'if "{m}" not in sys.modules:\n    raise SystemExit("expected {m} imported")'
        for m in required_modules
    )
    forbidden_mod_checks = "\n".join(
        f'if "{m}" in sys.modules:\n    raise SystemExit("forbidden module present: {m}")'
        for m in forbidden_modules
    )
    code = f"""
import sys
{import_stmt}
forbidden_prefixes = {forbidden_prefixes!r}
for name in list(sys.modules):
    for bad in forbidden_prefixes:
        if name == bad or name.startswith(bad + "."):
            raise SystemExit(f"forbidden import present: {{name}}")
{required_checks}
{forbidden_mod_checks}
print("ok")
"""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(_SERVICE_ROOT) if not existing else f"{_SERVICE_ROOT}{os.pathsep}{existing}"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_SERVICE_ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"import purity failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ok" in result.stdout


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def iou_xywh(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(4)
    b = np.asarray(b, dtype=np.float64).reshape(4)
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return float(inter / union) if union > 0 else 0.0


def landmark_max_dist(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(5, 2)
    b = np.asarray(b, dtype=np.float64).reshape(5, 2)
    return float(np.max(np.linalg.norm(a - b, axis=1)))


def greedy_match_by_iou(left, right) -> list[tuple[object, object, float]]:
    """1-1 greedy match of detections by IoU (higher first)."""
    remaining = list(enumerate(right))
    pairs: list[tuple[object, object, float]] = []
    for fa in left:
        best_i = -1
        best_iou = -1.0
        best_fb = None
        for i, (orig_j, fb) in enumerate(remaining):
            iou = iou_xywh(fa.bbox, fb.bbox)
            if iou > best_iou:
                best_iou = iou
                best_i = i
                best_fb = fb
        if best_fb is None or best_i < 0:
            continue
        remaining.pop(best_i)
        pairs.append((fa, best_fb, best_iou))
    return pairs


def cartoon_from_procedure(meta: dict) -> np.ndarray:
    proc = meta["procedure"]
    gen = load_generate_goldens()
    return gen.cartoon_face_image(
        size=int(proc["size"]),
        seed=int(proc["seed"]),
        eye_sep=float(proc["eye_sep"]),
        mouth_y=float(proc["mouth_y"]),
        head_rx=float(proc["head_rx"]),
        head_ry=float(proc["head_ry"]),
        noise_scale=float(proc["noise_scale"]),
    )


def three_face_canvas_640x480() -> np.ndarray:
    """Three drawn cartoon faces on a 640×480 canvas (BR-01 multi-face parity)."""
    gen = load_generate_goldens()
    face = gen.cartoon_face_image(size=160, seed=19)
    canvas = np.full((480, 640, 3), 200, dtype=np.uint8)
    placements = ((30, 40), (160, 240), (280, 440))
    fh, fw = face.shape[:2]
    for y, x in placements:
        canvas[y : y + fh, x : x + fw] = face
    return canvas


def non_multiple_of_32_canvas() -> np.ndarray:
    """Single cartoon face on a non-×32 canvas (481×479)."""
    gen = load_generate_goldens()
    face = gen.cartoon_face_image(size=240, seed=19)
    canvas = np.full((479, 481, 3), 200, dtype=np.uint8)
    y0, x0 = 100, 110
    canvas[y0 : y0 + face.shape[0], x0 : x0 + face.shape[1]] = face
    return canvas


def border_clipped_face_canvas() -> np.ndarray:
    """Face partial-pasted at top-left so the prior is border-clipped."""
    gen = load_generate_goldens()
    face = gen.cartoon_face_image(size=200, seed=19)
    canvas = np.full((300, 320, 3), 200, dtype=np.uint8)
    # Keep only the bottom-right portion of the face (simulates TL clip).
    src = face[50:, 50:]
    canvas[0 : src.shape[0], 0 : src.shape[1]] = src
    return canvas


@pytest.fixture(scope="module")
def ort_sface_embedder():
    if not MODELS_PRESENT:
        pytest.skip(MODELS_SKIP)
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    return OrtSFaceEmbedder()


@pytest.fixture(scope="module")
def ocv_sface_embedder():
    if not MODELS_PRESENT:
        pytest.skip(MODELS_SKIP)
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    return OpenCVSFaceEmbedder()


@pytest.fixture(scope="module")
def ort_yunet_detector():
    if not MODELS_PRESENT:
        pytest.skip(MODELS_SKIP)
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    return OrtYuNetDetector()


@pytest.fixture(scope="module")
def ocv_yunet_detector():
    if not MODELS_PRESENT:
        pytest.skip(MODELS_SKIP)
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    return OpenCVYuNetDetector()

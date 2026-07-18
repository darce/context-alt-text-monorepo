"""FIR-3 S2: OpenCV reference aligner/detector/embedder + golden fixtures.

Heuristics: TEST-06/TEST-08 (determinism), rg-015 (landmark order contract),
AGT-06 (name the skip), rg-013-style import purity for opencv_ref.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline.aligner import (
    ALIGNED_SIZE,
    AlignmentError,
    FivePointAligner,
    SFACE_CANONICAL_LANDMARKS_112,
    YUNET_LANDMARK_NAMES,
    similarity_transform_matrix,
)
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    load_verified_model,
)

_SERVICE_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = _SERVICE_ROOT / "recognition" / "tests" / "fixtures" / "face_pipeline"

_MODELS_PRESENT = (
    (DEFAULT_MODELS_DIR / MODEL_MANIFEST["yunet"].file_name).is_file()
    and (DEFAULT_MODELS_DIR / MODEL_MANIFEST["sface"].file_name).is_file()
)
_MODELS_SKIP = (
    "FIR-3 face models missing under recognition/infrastructure/face_pipeline/models/ — "
    "run: uv run python scripts/fetch_face_pipeline_models.py "
    f"(expected yunet={MODEL_MANIFEST['yunet'].file_name}, "
    f"sface={MODEL_MANIFEST['sface'].file_name})"
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Landmark order contract
# ---------------------------------------------------------------------------


def test_yunet_landmark_order_contract_names() -> None:
    """Documented order is fixed: RE, LE, nose, RM, LM (YuNet / SFace)."""
    assert YUNET_LANDMARK_NAMES == (
        "right_eye",
        "left_eye",
        "nose_tip",
        "right_mouth_corner",
        "left_mouth_corner",
    )
    assert SFACE_CANONICAL_LANDMARKS_112.shape == (5, 2)
    # First canonical point is left-of-image (anatomical right eye) on 112 crop.
    assert SFACE_CANONICAL_LANDMARKS_112[0, 0] < SFACE_CANONICAL_LANDMARKS_112[1, 0]


def test_similarity_transform_rejects_bad_landmark_shape() -> None:
    with pytest.raises(AlignmentError, match="expected 5 landmarks"):
        similarity_transform_matrix(np.zeros((4, 2)))


def test_aligner_affine_and_crop_match_goldens() -> None:
    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    expected_affine = np.load(_FIXTURE_DIR / "aligner_affine.npy")
    expected_crop = np.load(_FIXTURE_DIR / "aligner_crop.npy")
    meta = _load_json("aligner_meta.json")

    result = FivePointAligner().align(img, landmarks)

    assert result.crop.shape == (ALIGNED_SIZE, ALIGNED_SIZE, 3)
    np.testing.assert_allclose(result.affine, expected_affine, atol=1e-4)
    assert _sha256_bytes(result.crop.tobytes()) == meta["crop_sha256"]
    np.testing.assert_array_equal(result.crop, expected_crop)


def test_aligner_determinism() -> None:
    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    a = FivePointAligner().align(img, landmarks)
    b = FivePointAligner().align(img, landmarks)
    np.testing.assert_array_equal(a.crop, b.crop)
    np.testing.assert_allclose(a.affine, b.affine, atol=0.0)


# ---------------------------------------------------------------------------
# Embedder goldens (require real SFace model)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_sface_models_load_via_verified_path() -> None:
    path = load_verified_model("sface")
    assert path.is_file()


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_golden_dim_norm_cosine() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    expected = np.load(_FIXTURE_DIR / "synthetic_112_embedding.npy")
    meta = _load_json("embedding_meta.json")

    emb = OpenCVSFaceEmbedder().embed([crop])
    assert emb.shape == (1, 128)
    assert emb.shape[1] == meta["embedding_dim"]
    norm = float(np.linalg.norm(emb[0]))
    assert norm == pytest.approx(1.0, abs=1e-6)

    cosine = float(np.dot(emb[0], expected[0]))
    assert cosine >= 0.9999


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_determinism_two_runs() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    emb = OpenCVSFaceEmbedder()
    a = emb.embed([crop])
    b = emb.embed([crop])
    np.testing.assert_array_equal(a, b)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_zero_norm_embedding_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import (
        OpenCVSFaceEmbedder,
        ZeroNormEmbeddingError,
    )

    emb = OpenCVSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _zero_feature(_crop: np.ndarray) -> np.ndarray:
        return np.zeros((1, 128), dtype=np.float32)

    monkeypatch.setattr(emb, "_feature", _zero_feature)
    with pytest.raises(ZeroNormEmbeddingError, match="zero"):
        emb.embed([crop])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embed_empty_batch_shape() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    out = OpenCVSFaceEmbedder().embed([])
    assert out.shape == (0, 128)


# ---------------------------------------------------------------------------
# Detector plumbing (no detector-output golden — see detector_golden_skip.json)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_empty_image_no_detections() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    det = OpenCVYuNetDetector()
    empty = np.zeros((100, 100, 3), dtype=np.uint8)
    out = det.detect([empty])
    assert out == [[]]


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_wrong_dtype_and_noncontiguous_coerced() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import (
        FacePipelineInputError,
        OpenCVYuNetDetector,
    )

    det = OpenCVYuNetDetector(score_threshold=0.9)
    # float image in [0,1] would clip poorly; use 0-255 float
    img_f = np.zeros((64, 64, 3), dtype=np.float32)
    out = det.detect([img_f])
    assert out == [[]]

    # non-contiguous view
    big = np.zeros((64, 128, 3), dtype=np.uint8)
    view = big[:, :64, :]
    assert not view.flags["C_CONTIGUOUS"] or view.base is not None
    out2 = det.detect([view])
    assert out2 == [[]]

    with pytest.raises(FacePipelineInputError):
        det.detect([np.zeros((10, 10), dtype=np.uint8)])  # missing channel dim


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_batch_length_matches() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    det = OpenCVYuNetDetector()
    imgs = [
        np.zeros((80, 80, 3), dtype=np.uint8),
        np.zeros((120, 90, 3), dtype=np.uint8),
    ]
    out = det.detect(imgs)
    assert len(out) == 2
    assert all(isinstance(x, list) for x in out)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_cartoon_golden_within_tolerances() -> None:
    """YuNet detections on seeded cartoon match recorded golden (tolerances)."""
    import importlib.util

    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    golden_path = _FIXTURE_DIR / "detector_faces.json"
    skip_path = _FIXTURE_DIR / "detector_golden_skip.json"
    if skip_path.is_file() and not golden_path.is_file():
        note = _load_json("detector_golden_skip.json")
        pytest.skip(
            f"detector-output golden skipped ({note.get('status')}): "
            f"{note.get('reason', '')[:200]}"
        )
    assert golden_path.is_file(), "expected detector_faces.json golden fixture"
    meta = _load_json("detector_faces.json")
    assert meta["status"] == "recorded"

    # Rebuild image from committed procedure (no large raster in git).
    gen_path = _FIXTURE_DIR / "generate_goldens.py"
    spec = importlib.util.spec_from_file_location("face_pipeline_generate_goldens", gen_path)
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    proc = meta["procedure"]
    img = gen.cartoon_face_image(
        size=int(proc["size"]),
        seed=int(proc["seed"]),
        eye_sep=float(proc["eye_sep"]),
        mouth_y=float(proc["mouth_y"]),
        head_rx=float(proc["head_rx"]),
        head_ry=float(proc["head_ry"]),
        noise_scale=float(proc["noise_scale"]),
    )
    assert _sha256_bytes(img.tobytes()) == meta["image_sha256"]

    det = OpenCVYuNetDetector(
        score_threshold=float(meta["score_threshold"]),
        nms_threshold=float(meta["nms_threshold"]),
    )
    faces = det.detect([img])[0]
    assert len(faces) >= 1
    d0 = faces[0]
    exp = meta["detection"]
    tol = meta["tolerances"]
    np.testing.assert_allclose(
        d0.bbox, np.asarray(exp["bbox_xywh"], dtype=np.float32), atol=tol["bbox_px"]
    )
    np.testing.assert_allclose(
        d0.landmarks,
        np.asarray(exp["landmarks_xy"], dtype=np.float32),
        atol=tol["landmarks_px"],
    )
    assert d0.score == pytest.approx(exp["score"], abs=tol["score"])
    assert d0.landmarks.shape == (5, 2)
    # Landmark order: right eye x < left eye x on this frontal synthetic face.
    assert d0.landmarks[0, 0] < d0.landmarks[1, 0]


# ---------------------------------------------------------------------------
# Import purity: package root stays cv2-free; opencv_ref may use cv2 only
# ---------------------------------------------------------------------------


def test_opencv_ref_import_purity_no_worker_http() -> None:
    """opencv_ref may import cv2; must not import worker/HTTP layers (rg-013)."""
    code = """
import sys
import recognition.infrastructure.face_pipeline.opencv_ref  # noqa: F401
import recognition.infrastructure.face_pipeline.aligner  # noqa: F401
forbidden_prefixes = (
    "fastapi",
    "starlette",
    "recognition.worker",
    "recognition.api",
)
for name in list(sys.modules):
    for bad in forbidden_prefixes:
        if name == bad or name.startswith(bad + "."):
            raise SystemExit(f"forbidden import present: {name}")
# cv2 is expected for the reference impl
if "cv2" not in sys.modules:
    raise SystemExit("expected cv2 to be imported by opencv_ref")
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
        f"opencv_ref purity failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ok" in result.stdout


def test_package_root_still_cv2_free() -> None:
    """Importing package root + provenance must not load cv2 (S1 BR-06)."""
    code = """
import sys
import recognition.infrastructure.face_pipeline  # noqa: F401
import recognition.infrastructure.face_pipeline.provenance  # noqa: F401
for name in list(sys.modules):
    if name == "cv2" or name.startswith("cv2."):
        raise SystemExit(f"forbidden import present: {name}")
    if name == "recognition.infrastructure.face_pipeline.opencv_ref":
        raise SystemExit("opencv_ref must not load via package root")
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
        f"root purity failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )

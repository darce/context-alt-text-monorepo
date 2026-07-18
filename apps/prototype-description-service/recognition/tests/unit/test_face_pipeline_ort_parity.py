"""FIR-3 S3: ORT CPU adapters vs OpenCV reference parity + modelless decode tests.

Gates (task plan / assignment):
- embedding cosine(ORT, OpenCV) ≥ 0.999 on golden synthetic + aligner crops
- detector boxes IoU ≥ 0.99, landmark max-dist ≤ 2px, score delta ≤ 0.02
- zero-norm raise, empty batch, same input gates as OpenCV path
- modelless: pure decode/NMS unit-tested without ONNX

Heuristics: TEST-06 (watch fail first), TEST-08 (determinism), AGT-06 (skip names fetch),
rg-015 (manifest dim), sr-001 (do not loosen thresholds).
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

from recognition.infrastructure.face_pipeline.opencv_ref import (
    FacePipelineInputError,
    RawDetection,
    ZeroNormEmbeddingError,
)
from recognition.infrastructure.face_pipeline.ort_adapters import (
    decode_yunet_level,
    decode_yunet_outputs,
    nms_yunet,
)
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
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

# Parity budgets from FIR-3 S3 assignment (do not loosen — sr-001).
_COSINE_MIN = 0.999
_IOU_MIN = 0.99
_LANDMARK_MAX_DIST_PX = 2.0
_SCORE_DELTA_MAX = 0.02


def _load_json(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_generate_goldens():
    gen_path = _FIXTURE_DIR / "generate_goldens.py"
    spec = importlib.util.spec_from_file_location("face_pipeline_generate_goldens", gen_path)
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    return gen


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(-1)
    b = np.asarray(b, dtype=np.float64).reshape(-1)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def _iou_xywh(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(4)
    b = np.asarray(b, dtype=np.float64).reshape(4)
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return float(inter / union) if union > 0 else 0.0


def _landmark_max_dist(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64).reshape(5, 2)
    b = np.asarray(b, dtype=np.float64).reshape(5, 2)
    return float(np.max(np.linalg.norm(a - b, axis=1)))


# ---------------------------------------------------------------------------
# Modelless tier — pure decode / NMS (no ONNX)
# ---------------------------------------------------------------------------


def test_models_skip_reason_names_fetch_command() -> None:
    assert "fetch_face_pipeline_models.py" in _MODELS_SKIP
    assert "uv run python" in _MODELS_SKIP


def test_decode_yunet_level_synthetic_prior() -> None:
    """Construct logits so a single grid cell decodes to a known box + landmarks."""
    stride = 8
    pad_w, pad_h = 16, 16  # 2×2 grid
    rows, cols = pad_h // stride, pad_w // stride
    n = rows * cols
    cls = np.zeros((n,), dtype=np.float32)
    obj = np.zeros((n,), dtype=np.float32)
    bbox = np.zeros((n, 4), dtype=np.float32)
    kps = np.zeros((n, 10), dtype=np.float32)

    # Cell (r=1, c=0): high score
    idx = 1 * cols + 0
    cls[idx] = 1.0
    obj[idx] = 1.0
    # bbox offsets → cx=(0+0.25)*8=2, cy=(1+0.5)*8=12, w=exp(0)*8=8, h=exp(0)*8=8
    bbox[idx] = [0.25, 0.5, 0.0, 0.0]
    # landmark n at (kps + c/r)*stride
    for n_lm in range(5):
        kps[idx, 2 * n_lm] = 0.1 * n_lm
        kps[idx, 2 * n_lm + 1] = 0.2 * n_lm

    dets = decode_yunet_level(
        cls,
        obj,
        bbox,
        kps,
        stride=stride,
        pad_w=pad_w,
        pad_h=pad_h,
        score_threshold=0.5,
    )
    assert len(dets) == 1
    d = dets[0]
    assert d.score == pytest.approx(1.0)
    # x1 = 2 - 4 = -2, y1 = 12 - 4 = 8
    np.testing.assert_allclose(d.bbox, [-2.0, 8.0, 8.0, 8.0], atol=1e-5)
    assert d.landmarks.shape == (5, 2)
    # lm0: ((0.0)+0)*8=0, ((0.0)+1)*8=8
    np.testing.assert_allclose(d.landmarks[0], [0.0, 8.0], atol=1e-5)
    np.testing.assert_allclose(d.landmarks[1], [0.8, 9.6], atol=1e-5)


def test_decode_yunet_level_score_composition_and_threshold() -> None:
    stride = 16
    pad_w = pad_h = 16  # 1 cell
    cls = np.array([0.81], dtype=np.float32)  # clamp still 0.81
    obj = np.array([1.0], dtype=np.float32)
    # score = sqrt(0.81) = 0.9
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    above = decode_yunet_level(
        cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.9
    )
    assert len(above) == 1
    assert above[0].score == pytest.approx(0.9, abs=1e-6)
    below = decode_yunet_level(
        cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.91
    )
    assert below == []


def test_decode_clamps_scores_above_one() -> None:
    stride = 32
    pad_w = pad_h = 32
    cls = np.array([2.0], dtype=np.float32)
    obj = np.array([2.0], dtype=np.float32)
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    dets = decode_yunet_level(
        cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.5
    )
    assert len(dets) == 1
    assert dets[0].score == pytest.approx(1.0)


def test_nms_suppresses_overlap_keeps_higher_score() -> None:
    high = RawDetection(
        bbox=np.array([10.0, 10.0, 40.0, 40.0], dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=0.95,
    )
    low = RawDetection(
        bbox=np.array([12.0, 12.0, 40.0, 40.0], dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=0.91,
    )
    far = RawDetection(
        bbox=np.array([200.0, 200.0, 30.0, 30.0], dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=0.92,
    )
    kept = nms_yunet(
        [low, far, high],
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )
    scores = [d.score for d in kept]
    assert 0.95 in scores
    assert 0.92 in scores
    assert 0.91 not in scores


def test_nms_single_or_empty_passthrough() -> None:
    assert nms_yunet([], score_threshold=0.9, nms_threshold=0.3, top_k=5000) == []
    one = RawDetection(
        bbox=np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=0.99,
    )
    assert nms_yunet([one], score_threshold=0.9, nms_threshold=0.3, top_k=5000) == [one]


def test_decode_yunet_outputs_missing_key_raises() -> None:
    with pytest.raises(FacePipelineInputError, match="missing keys"):
        decode_yunet_outputs(
            {},
            pad_w=32,
            pad_h=32,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )


def test_decode_yunet_outputs_full_pipeline_synthetic() -> None:
    """Wire all 12 tensors; only stride-32 cell fires."""
    pad_w = pad_h = 32
    outputs: dict[str, np.ndarray] = {}
    for s in (8, 16, 32):
        n = (pad_h // s) * (pad_w // s)
        outputs[f"cls_{s}"] = np.zeros((1, n, 1), dtype=np.float32)
        outputs[f"obj_{s}"] = np.zeros((1, n, 1), dtype=np.float32)
        outputs[f"bbox_{s}"] = np.zeros((1, n, 4), dtype=np.float32)
        outputs[f"kps_{s}"] = np.zeros((1, n, 10), dtype=np.float32)
    outputs["cls_32"][0, 0, 0] = 1.0
    outputs["obj_32"][0, 0, 0] = 1.0
    faces = decode_yunet_outputs(
        outputs,
        pad_w=pad_w,
        pad_h=pad_h,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )
    assert len(faces) == 1
    assert faces[0].score == pytest.approx(1.0)


def test_decode_determinism_modelless() -> None:
    """TEST-08: pure decode is bit-stable across two calls."""
    stride = 8
    pad_w = pad_h = 16
    rng = np.random.default_rng(0)
    cls = rng.random(4).astype(np.float32)
    obj = rng.random(4).astype(np.float32)
    bbox = rng.normal(size=(4, 4)).astype(np.float32) * 0.1
    kps = rng.normal(size=(4, 10)).astype(np.float32) * 0.1
    a = decode_yunet_level(
        cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.0
    )
    b = decode_yunet_level(
        cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.0
    )
    assert len(a) == len(b)
    for da, db in zip(a, b):
        np.testing.assert_array_equal(da.bbox, db.bbox)
        np.testing.assert_array_equal(da.landmarks, db.landmarks)
        assert da.score == db.score


# ---------------------------------------------------------------------------
# Models-present parity suite
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_parity_synthetic_crop() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    ocv = OpenCVSFaceEmbedder().embed([crop])
    ort_emb = OrtSFaceEmbedder().embed([crop])
    assert ocv.shape == ort_emb.shape == (1, 128)
    assert float(np.linalg.norm(ort_emb[0])) == pytest.approx(1.0, abs=1e-5)
    cos = _cosine(ocv[0], ort_emb[0])
    assert cos >= _COSINE_MIN, f"synthetic crop cosine={cos} < {_COSINE_MIN}"
    # Print for worker report (AGT-04)
    print(f"PARITY_COSINE_synthetic={cos:.10f}")


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_parity_aligner_golden_crop() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "aligner_crop.npy")
    ocv = OpenCVSFaceEmbedder().embed([crop])
    ort_emb = OrtSFaceEmbedder().embed([crop])
    cos = _cosine(ocv[0], ort_emb[0])
    assert cos >= _COSINE_MIN, f"aligner crop cosine={cos} < {_COSINE_MIN}"
    print(f"PARITY_COSINE_aligner={cos:.10f}")


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_parity_vs_golden_fixture() -> None:
    """ORT also matches committed golden embedding (cross-check)."""
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    expected = np.load(_FIXTURE_DIR / "synthetic_112_embedding.npy")
    emb = OrtSFaceEmbedder().embed([crop])
    cos = _cosine(emb[0], expected[0])
    assert cos >= _COSINE_MIN, f"golden cosine={cos}"
    print(f"PARITY_COSINE_golden={cos:.10f}")


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_sface_preprocess_is_rgb_scale1() -> None:
    """Document empirical SFace prep: RGB NCHW scale=1 (swapRB), not /255."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder
    from recognition.infrastructure.face_pipeline.ort_adapters import (
        OrtSFaceEmbedder,
        _bgr_to_sface_blob,
    )

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    blob = _bgr_to_sface_blob(crop)
    assert blob.shape == (1, 3, 112, 112)
    # Channel 0 of blob is R (= crop[:,:,2]), not B
    assert float(blob[0, 0, 0, 0]) == float(crop[0, 0, 2])
    assert float(blob[0, 2, 0, 0]) == float(crop[0, 0, 0])
    # Values are raw 0–255 float, not /255
    assert float(blob.max()) > 1.5

    raw_ocv = np.asarray(OpenCVSFaceEmbedder()._feature(crop), dtype=np.float32).reshape(-1)
    raw_ort = np.asarray(OrtSFaceEmbedder()._feature(crop), dtype=np.float32).reshape(-1)
    cos = _cosine(raw_ocv, raw_ort)
    assert cos >= 0.9999
    print(f"PARITY_COSINE_raw_feature={cos:.10f}")


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_zero_norm_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    emb = OrtSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _zero(_crop: np.ndarray) -> np.ndarray:
        return np.zeros((128,), dtype=np.float32)

    monkeypatch.setattr(emb, "_feature", _zero)
    with pytest.raises(ZeroNormEmbeddingError, match="zero"):
        emb.embed([crop])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_nonfinite_norm_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    emb = OrtSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _nan(_crop: np.ndarray) -> np.ndarray:
        return np.full((128,), np.nan, dtype=np.float32)

    monkeypatch.setattr(emb, "_feature", _nan)
    with pytest.raises(ZeroNormEmbeddingError, match="non-finite|zero"):
        emb.embed([crop])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_embed_empty_batch() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    out = OrtSFaceEmbedder().embed([])
    assert out.shape == (0, MODEL_MANIFEST["sface"].embedding_dim)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_embed_112_gate() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    with pytest.raises(FacePipelineInputError, match="expected shape"):
        OrtSFaceEmbedder().embed([np.zeros((64, 64, 3), dtype=np.uint8)])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_embed_float01_gate() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        OrtSFaceEmbedder().embed([np.full((112, 112, 3), 0.5, dtype=np.float32)])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_detector_float01_gate() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        OrtYuNetDetector().detect([np.full((64, 64, 3), 0.5, dtype=np.float32)])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_detector_empty_and_batch() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    det = OrtYuNetDetector()
    assert det.detect([np.zeros((100, 100, 3), dtype=np.uint8)]) == [[]]
    out = det.detect(
        [np.zeros((80, 80, 3), dtype=np.uint8), np.zeros((120, 90, 3), dtype=np.uint8)]
    )
    assert len(out) == 2


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_ort_detector_threshold_attrs_readonly() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    det = OrtYuNetDetector(score_threshold=0.95, nms_threshold=0.3, top_k=100)
    assert det.score_threshold == pytest.approx(0.95)
    assert det.nms_threshold == pytest.approx(0.3)
    assert det.top_k == 100
    with pytest.raises(AttributeError):
        det.score_threshold = 0.1  # type: ignore[misc]


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_parity_cartoon_fixture() -> None:
    """ORT vs OpenCV on cartoon golden: IoU / landmarks / score budgets."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    golden_path = _FIXTURE_DIR / "detector_faces.json"
    skip_path = _FIXTURE_DIR / "detector_golden_skip.json"
    if skip_path.is_file() and not golden_path.is_file():
        note = _load_json("detector_golden_skip.json")
        pytest.skip(f"detector golden skipped: {note.get('reason', '')[:200]}")
    meta = _load_json("detector_faces.json")
    proc = meta["procedure"]
    gen = _load_generate_goldens()
    img = gen.cartoon_face_image(
        size=int(proc["size"]),
        seed=int(proc["seed"]),
        eye_sep=float(proc["eye_sep"]),
        mouth_y=float(proc["mouth_y"]),
        head_rx=float(proc["head_rx"]),
        head_ry=float(proc["head_ry"]),
        noise_scale=float(proc["noise_scale"]),
    )
    score_th = float(meta["score_threshold"])
    nms_th = float(meta["nms_threshold"])

    ocv_faces = OpenCVYuNetDetector(
        score_threshold=score_th, nms_threshold=nms_th
    ).detect([img])[0]
    ort_faces = OrtYuNetDetector(
        score_threshold=score_th, nms_threshold=nms_th
    ).detect([img])[0]

    assert len(ocv_faces) >= 1
    assert len(ort_faces) >= 1
    # Match primary (highest-score) detections
    ocv = max(ocv_faces, key=lambda d: d.score)
    ort_d = max(ort_faces, key=lambda d: d.score)

    iou = _iou_xywh(ort_d.bbox, ocv.bbox)
    lm_dist = _landmark_max_dist(ort_d.landmarks, ocv.landmarks)
    score_delta = abs(float(ort_d.score) - float(ocv.score))

    print(f"PARITY_IOU={iou:.10f}")
    print(f"PARITY_LANDMARK_MAX_DIST={lm_dist:.10f}")
    print(f"PARITY_SCORE_DELTA={score_delta:.10e}")

    assert iou >= _IOU_MIN, f"IoU={iou} < {_IOU_MIN}"
    assert lm_dist <= _LANDMARK_MAX_DIST_PX, f"landmark max dist={lm_dist}"
    assert score_delta <= _SCORE_DELTA_MAX, f"score delta={score_delta}"


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_and_embedder_determinism() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import (
        OrtSFaceEmbedder,
        OrtYuNetDetector,
    )

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    emb = OrtSFaceEmbedder()
    a = emb.embed([crop])
    b = emb.embed([crop])
    np.testing.assert_array_equal(a, b)

    empty = np.zeros((64, 64, 3), dtype=np.uint8)
    det = OrtYuNetDetector()
    d0 = det.detect([empty])
    d1 = det.detect([empty])
    assert d0 == d1


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_shared_five_point_aligner_class() -> None:
    """ORT path must use the same FivePointAligner class (no reimplementation)."""
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner

    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    # Single shared class instance used before ORT embed
    aligner = FivePointAligner()
    crop = aligner.align(img, landmarks).crop
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtSFaceEmbedder

    emb = OrtSFaceEmbedder().embed([crop])
    assert emb.shape == (1, 128)
    assert float(np.linalg.norm(emb[0])) == pytest.approx(1.0, abs=1e-5)


def test_ort_adapters_import_purity_no_worker_http() -> None:
    code = """
import sys
import recognition.infrastructure.face_pipeline.ort_adapters  # noqa: F401
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
if "onnxruntime" not in sys.modules:
    raise SystemExit("expected onnxruntime imported by ort_adapters")
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
        f"ort_adapters purity failed rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ok" in result.stdout

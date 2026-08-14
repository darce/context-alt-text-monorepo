"""FIR-3 S3: ORT CPU adapters vs OpenCV reference parity + modelless decode tests.

Gates (task plan / assignment, amended):
- embedding cosine(ORT, OpenCV) ≥ 0.99999999 on golden synthetic + aligner crops
  (S3 parity-budget amendment; supersedes the assigned 0.999 floor — see
  docs/tasks/fir/FIR-3-yunet-sface-adapters-task-plan.md and ``_COSINE_MIN``)
- detector boxes IoU ≥ 0.99, landmark max-dist ≤ 2px, score delta ≤ 0.02
- zero-norm raise, empty batch, same input gates as OpenCV path
- modelless: pure decode/NMS unit-tested without ONNX

Heuristics: TEST-06 (watch fail first), TEST-08 (determinism), AGT-06 (skip names fetch),
rg-015 (manifest dim), sr-001 (do not loosen thresholds), REF-05 (decode refactor).
"""

from __future__ import annotations

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline._common import EmbedBatchResult
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
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST
from recognition.tests.unit.face_pipeline_support import (
    _FIXTURE_DIR,
    MODELS_PRESENT,
    MODELS_SKIP,
    SFACE_EMBEDDING_DIM,
    border_clipped_face_canvas,
    cartoon_from_procedure,
    cosine,
    greedy_match_by_iou,
    iou_xywh,
    landmark_max_dist,
    load_json,
    models_absent_allows_skip,
    non_multiple_of_32_canvas,
    run_import_purity_check,
    three_face_canvas_640x480,
)

# Parity / golden budgets (CVUP1-LC-03; do not loosen without re-measure — sr-001).
# Measurement 2026-07-29, OpenCV 5.0.0 / ORT 1.28.0 / numpy 2.5.1:
#   ORT↔OpenCV cosine (synthetic + aligner crops): ≥ 0.999999999997 (1-cos ≤ 5e-12)
#   ORT vs synthetic_112_embedding golden: ≥ 0.999999999997
# Noise floor ≈ 0 for unit cosine. Floor 0.99999999 is 10× above a 1e-9 slack
# band; prior decorative floors were 0.999 / 0.9999. This supersedes the FIR-3
# S3 assigned budget (cosine ≥ 0.999) — see the S3 parity-budget amendment in
# docs/tasks/fir/FIR-3-yunet-sface-adapters-task-plan.md for the evidence.
_COSINE_MIN = 0.99999999
_GOLDEN_COSINE_MIN = 0.99999999
_IOU_MIN = 0.99
_LANDMARK_MAX_DIST_PX = 2.0
_SCORE_DELTA_MAX = 0.02

# Legacy aliases for skip markers (BR-08 shared source).
_MODELS_PRESENT = MODELS_PRESENT
_MODELS_SKIP = MODELS_SKIP


# ---------------------------------------------------------------------------
# Modelless tier — pure decode / NMS (no ONNX)
# ---------------------------------------------------------------------------


def test_models_skip_reason_names_fetch_command() -> None:
    assert "fetch_face_pipeline_models.py" in MODELS_SKIP
    assert "uv run python" in MODELS_SKIP


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
    above = decode_yunet_level(cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.9)
    assert len(above) == 1
    assert above[0].score == pytest.approx(0.9, abs=1e-6)
    below = decode_yunet_level(cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.91)
    assert below == []


def test_decode_clamps_scores_above_one() -> None:
    stride = 32
    pad_w = pad_h = 32
    cls = np.array([2.0], dtype=np.float32)
    obj = np.array([2.0], dtype=np.float32)
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    dets = decode_yunet_level(cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.5)
    assert len(dets) == 1
    assert dets[0].score == pytest.approx(1.0)


def test_decode_negative_logits_clamped_to_unit_interval() -> None:
    """cls/obj must be clamped to [0,1] (lower+upper) before sqrt (FIR3-BR-02).

    Upper-only MIN(x,1) leaves negatives; mixed signs then yield NaN and drop.
    Lower+upper clamp yields score 0 and also drops at any positive threshold.
    """
    stride = 16
    pad_w = pad_h = 16
    cls = np.array([-0.5], dtype=np.float32)
    obj = np.array([1.0], dtype=np.float32)
    bbox = np.zeros((1, 4), dtype=np.float32)
    kps = np.zeros((1, 10), dtype=np.float32)
    dets = decode_yunet_level(cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.01)
    assert dets == []


# both-negative false-detection regression lives once in
# test_face_pipeline_pure_contracts.test_decode_both_negative_cls_obj_no_false_detection


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
    a = decode_yunet_level(cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.0)
    b = decode_yunet_level(cls, obj, bbox, kps, stride=stride, pad_w=pad_w, pad_h=pad_h, score_threshold=0.0)
    assert len(a) == len(b)
    for da, db in zip(a, b, strict=False):
        np.testing.assert_array_equal(da.bbox, db.bbox)
        np.testing.assert_array_equal(da.landmarks, db.landmarks)
        assert da.score == db.score


# ---------------------------------------------------------------------------
# Models-present parity suite
# ---------------------------------------------------------------------------


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_embedding_parity_synthetic_crop(ort_sface_embedder, ocv_sface_embedder) -> None:
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    ocv = ocv_sface_embedder.embed([crop]).vectors
    ort_emb = ort_sface_embedder.embed([crop]).vectors
    assert ocv.shape == ort_emb.shape == (1, SFACE_EMBEDDING_DIM)
    assert float(np.linalg.norm(ort_emb[0])) == pytest.approx(1.0, abs=1e-5)
    cos = cosine(ocv[0], ort_emb[0])
    assert cos >= _COSINE_MIN, f"synthetic crop cosine={cos} < {_COSINE_MIN}"
    print(f"PARITY_COSINE_synthetic={cos:.10f}")


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_embedding_parity_aligner_golden_crop(ort_sface_embedder, ocv_sface_embedder) -> None:
    crop = np.load(_FIXTURE_DIR / "aligner_crop.npy")
    ocv = ocv_sface_embedder.embed([crop]).vectors
    ort_emb = ort_sface_embedder.embed([crop]).vectors
    cos = cosine(ocv[0], ort_emb[0])
    assert cos >= _COSINE_MIN, f"aligner crop cosine={cos} < {_COSINE_MIN}"
    print(f"PARITY_COSINE_aligner={cos:.10f}")


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_embedding_parity_vs_golden_fixture(ort_sface_embedder) -> None:
    """ORT also matches committed golden embedding (cross-check)."""
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    expected = np.load(_FIXTURE_DIR / "synthetic_112_embedding.npy")
    meta = load_json("embedding_meta.json")
    cosine_min = float(meta.get("cosine_min", _GOLDEN_COSINE_MIN))
    emb = ort_sface_embedder.embed([crop]).vectors
    cos = cosine(emb[0], expected[0])
    assert cos >= cosine_min, f"golden cosine={cos} < {cosine_min}"
    print(f"PARITY_COSINE_golden={cos:.10f}")


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_sface_preprocess_is_rgb_scale1(ort_sface_embedder, ocv_sface_embedder) -> None:
    """Document empirical SFace prep: RGB NCHW scale=1 (swapRB), not /255."""
    from recognition.infrastructure.face_pipeline.ort_adapters import _bgr_to_sface_blob

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    blob = _bgr_to_sface_blob(crop)
    assert blob.shape == (1, 3, 112, 112)
    # Channel 0 of blob is R (= crop[:,:,2]), not B
    assert float(blob[0, 0, 0, 0]) == float(crop[0, 0, 2])
    assert float(blob[0, 2, 0, 0]) == float(crop[0, 0, 0])
    # Values are raw 0–255 float, not /255
    assert float(blob.max()) > 1.5

    raw_ocv = np.asarray(ocv_sface_embedder._feature(crop), dtype=np.float32).reshape(-1)
    raw_ort = np.asarray(ort_sface_embedder._feature(crop), dtype=np.float32).reshape(-1)
    cos = cosine(raw_ocv, raw_ort)
    assert cos >= _COSINE_MIN, f"raw feature cosine={cos} < {_COSINE_MIN}"
    print(f"PARITY_COSINE_raw_feature={cos:.10f}")


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_zero_norm_raises(ort_sface_embedder, monkeypatch: pytest.MonkeyPatch) -> None:
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _zero(_crop: np.ndarray) -> np.ndarray:
        return np.zeros((SFACE_EMBEDDING_DIM,), dtype=np.float32)

    monkeypatch.setattr(ort_sface_embedder, "_feature", _zero)
    with pytest.raises(ZeroNormEmbeddingError, match="zero"):
        ort_sface_embedder.embed([crop])


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_nonfinite_norm_raises(ort_sface_embedder, monkeypatch: pytest.MonkeyPatch) -> None:
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _nan(_crop: np.ndarray) -> np.ndarray:
        return np.full((SFACE_EMBEDDING_DIM,), np.nan, dtype=np.float32)

    monkeypatch.setattr(ort_sface_embedder, "_feature", _nan)
    with pytest.raises(ZeroNormEmbeddingError, match="non-finite|zero"):
        ort_sface_embedder.embed([crop])


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_embed_empty_batch(ort_sface_embedder) -> None:
    out = ort_sface_embedder.embed([]).vectors
    assert out.shape == (0, MODEL_MANIFEST["sface"].embedding_dim)
    assert out.shape == (0, SFACE_EMBEDDING_DIM)


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_embed_112_gate(ort_sface_embedder) -> None:
    with pytest.raises(FacePipelineInputError, match="expected shape"):
        ort_sface_embedder.embed([np.zeros((64, 64, 3), dtype=np.uint8)])


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_embed_float01_gate(ort_sface_embedder) -> None:
    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        ort_sface_embedder.embed([np.full((112, 112, 3), 0.5, dtype=np.float32)])


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_detector_float01_gate(ort_yunet_detector) -> None:
    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        ort_yunet_detector.detect([np.full((64, 64, 3), 0.5, dtype=np.float32)])


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_detector_empty_and_batch(ort_yunet_detector) -> None:
    assert ort_yunet_detector.detect([np.zeros((100, 100, 3), dtype=np.uint8)]) == [[]]
    out = ort_yunet_detector.detect([np.zeros((80, 80, 3), dtype=np.uint8), np.zeros((120, 90, 3), dtype=np.uint8)])
    assert len(out) == 2


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_detector_threshold_attrs_readonly() -> None:
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    det = OrtYuNetDetector(score_threshold=0.95, nms_threshold=0.3, top_k=100)
    assert det.score_threshold == pytest.approx(0.95)
    assert det.nms_threshold == pytest.approx(0.3)
    assert det.top_k == 100
    with pytest.raises(AttributeError):
        det.score_threshold = 0.1  # type: ignore[misc]


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_ort_detector_accepts_initial_input_size_kwarg() -> None:
    """BR-07: same kwargs dict constructs both detector classes."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    kwargs = {
        "score_threshold": 0.85,
        "nms_threshold": 0.3,
        "top_k": 100,
        "initial_input_size": (256, 256),
    }
    ocv = OpenCVYuNetDetector(**kwargs)
    ort = OrtYuNetDetector(**kwargs)
    assert ocv.score_threshold == ort.score_threshold == pytest.approx(0.85)
    assert ort._initial_input_size == (256, 256)


def _assert_detector_count_and_match(
    ocv_faces: list,
    ort_faces: list,
    *,
    expect_min: int = 1,
) -> None:
    assert len(ocv_faces) == len(ort_faces), f"detection count mismatch ocv={len(ocv_faces)} ort={len(ort_faces)}"
    assert len(ocv_faces) >= expect_min
    pairs = greedy_match_by_iou(ocv_faces, ort_faces)
    assert len(pairs) == len(ocv_faces)
    for ocv_d, ort_d, iou in pairs:
        lm_dist = landmark_max_dist(ort_d.landmarks, ocv_d.landmarks)
        score_delta = abs(float(ort_d.score) - float(ocv_d.score))
        assert iou >= _IOU_MIN, f"IoU={iou} < {_IOU_MIN}"
        assert lm_dist <= _LANDMARK_MAX_DIST_PX, f"landmark max dist={lm_dist}"
        assert score_delta <= _SCORE_DELTA_MAX, f"score delta={score_delta}"


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_detector_parity_cartoon_fixture() -> None:
    """ORT vs OpenCV on cartoon golden: IoU / landmarks / score budgets."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    golden_path = _FIXTURE_DIR / "detector_faces.json"
    skip_path = _FIXTURE_DIR / "detector_golden_skip.json"
    if skip_path.is_file() and not golden_path.is_file():
        note = load_json("detector_golden_skip.json")
        pytest.skip(f"detector golden skipped: {note.get('reason', '')[:200]}")
    meta = load_json("detector_faces.json")
    img = cartoon_from_procedure(meta)
    score_th = float(meta["score_threshold"])
    nms_th = float(meta["nms_threshold"])

    ocv_faces = OpenCVYuNetDetector(score_threshold=score_th, nms_threshold=nms_th).detect([img])[0]
    ort_faces = OrtYuNetDetector(score_threshold=score_th, nms_threshold=nms_th).detect([img])[0]

    assert len(ocv_faces) == len(ort_faces)
    assert len(ocv_faces) >= 1
    # Match primary (highest-score) detections
    ocv = max(ocv_faces, key=lambda d: d.score)
    ort_d = max(ort_faces, key=lambda d: d.score)

    iou = iou_xywh(ort_d.bbox, ocv.bbox)
    lm_dist = landmark_max_dist(ort_d.landmarks, ocv.landmarks)
    score_delta = abs(float(ort_d.score) - float(ocv.score))

    print(f"PARITY_IOU={iou:.10f}")
    print(f"PARITY_LANDMARK_MAX_DIST={lm_dist:.10f}")
    print(f"PARITY_SCORE_DELTA={score_delta:.10e}")

    assert iou >= _IOU_MIN, f"IoU={iou} < {_IOU_MIN}"
    assert lm_dist <= _LANDMARK_MAX_DIST_PX, f"landmark max dist={lm_dist}"
    assert score_delta <= _SCORE_DELTA_MAX, f"score delta={score_delta}"


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_detector_parity_three_faces_640x480_th05() -> None:
    """BR-01: multi-face count equality + greedy IoU ≥ 0.99 @ th=0.5."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    img = three_face_canvas_640x480()
    ocv_faces = OpenCVYuNetDetector(score_threshold=0.5, nms_threshold=0.3).detect([img])[0]
    ort_faces = OrtYuNetDetector(score_threshold=0.5, nms_threshold=0.3).detect([img])[0]
    print(f"PARITY_MULTI_COUNT ocv={len(ocv_faces)} ort={len(ort_faces)}")
    _assert_detector_count_and_match(ocv_faces, ort_faces, expect_min=3)


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_detector_parity_non_multiple_of_32() -> None:
    """BR-01: non-×32 canvas count equality + IoU budget."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    img = non_multiple_of_32_canvas()
    assert img.shape[0] % 32 != 0 or img.shape[1] % 32 != 0
    ocv_faces = OpenCVYuNetDetector(score_threshold=0.5, nms_threshold=0.3).detect([img])[0]
    ort_faces = OrtYuNetDetector(score_threshold=0.5, nms_threshold=0.3).detect([img])[0]
    print(f"PARITY_NON32_COUNT ocv={len(ocv_faces)} ort={len(ort_faces)}")
    _assert_detector_count_and_match(ocv_faces, ort_faces, expect_min=1)


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_detector_parity_border_clipped_face() -> None:
    """BR-01: border-clipped face count equality + IoU budget."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    img = border_clipped_face_canvas()
    ocv_faces = OpenCVYuNetDetector(score_threshold=0.5, nms_threshold=0.3).detect([img])[0]
    ort_faces = OrtYuNetDetector(score_threshold=0.5, nms_threshold=0.3).detect([img])[0]
    print(f"PARITY_BORDER_COUNT ocv={len(ocv_faces)} ort={len(ort_faces)}")
    _assert_detector_count_and_match(ocv_faces, ort_faces, expect_min=1)


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_detector_and_embedder_determinism(ort_sface_embedder) -> None:
    """TEST-08 / BR-05: embed bit-stable; cartoon bbox/score double-run equality."""
    from recognition.infrastructure.face_pipeline.ort_adapters import OrtYuNetDetector

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    a = ort_sface_embedder.embed([crop])
    b = ort_sface_embedder.embed([crop])
    # EmbedBatchResult is a dataclass of ndarrays — compare fields, not the object
    # (assert_array_equal on the dataclass raises ambiguous-truth ValueError).
    np.testing.assert_array_equal(a.vectors, b.vectors)
    np.testing.assert_array_equal(a.norms, b.norms)

    empty = np.zeros((64, 64, 3), dtype=np.uint8)
    det = OrtYuNetDetector()
    d0 = det.detect([empty])
    d1 = det.detect([empty])
    assert d0 == d1

    # Real-signal cartoon (production threshold path) — not noise-floor empty.
    meta = load_json("detector_faces.json")
    img = cartoon_from_procedure(meta)
    score_th = float(meta["score_threshold"])
    nms_th = float(meta["nms_threshold"])
    det_real = OrtYuNetDetector(score_threshold=score_th, nms_threshold=nms_th)
    r0 = det_real.detect([img])[0]
    r1 = det_real.detect([img])[0]
    assert len(r0) >= 1
    assert len(r0) == len(r1)
    for fa, fb in zip(r0, r1, strict=False):
        np.testing.assert_array_equal(fa.bbox, fb.bbox)
        np.testing.assert_array_equal(fa.landmarks, fb.landmarks)
        assert fa.score == fb.score


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_aligner_crop_is_valid_ort_sface_input(ort_sface_embedder) -> None:
    """FivePointAligner crop is a valid SFace input for ORT (BR-04 replaces vacuous claim)."""
    from recognition.infrastructure.face_pipeline.aligner import ALIGNED_SIZE, FivePointAligner

    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    crop = FivePointAligner().align(img, landmarks).crop
    assert crop.shape == (ALIGNED_SIZE, ALIGNED_SIZE, 3)
    emb = ort_sface_embedder.embed([crop]).vectors
    assert emb.shape == (1, SFACE_EMBEDDING_DIM)
    assert float(np.linalg.norm(emb[0])) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.skipif(models_absent_allows_skip(), reason=MODELS_SKIP)
def test_composed_aligner_embedder_ort_matches_golden(ort_sface_embedder) -> None:
    """ORT path also hits the composed aligner→embedder golden (CVUP1-LC-03)."""
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner

    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    expected = np.load(_FIXTURE_DIR / "aligner_composed_embedding.npy")
    meta = load_json("aligner_composed_embedding_meta.json")
    cosine_min = float(meta.get("cosine_min", _GOLDEN_COSINE_MIN))

    crop = FivePointAligner().align(img, landmarks).crop
    emb = ort_sface_embedder.embed([crop]).vectors
    cos = cosine(emb[0], expected[0])
    assert cos >= cosine_min, f"composed golden cosine={cos} < {cosine_min}"
    print(f"PARITY_COSINE_composed_golden={cos:.10f}")


def test_ort_adapters_import_purity_no_worker_http() -> None:
    run_import_purity_check(
        import_stmt="import recognition.infrastructure.face_pipeline.ort_adapters  # noqa: F401",
        forbidden_prefixes=(
            "fastapi",
            "starlette",
            "recognition.worker",
            "recognition.api",
        ),
        required_modules=("onnxruntime",),
    )


def test_common_import_purity_no_cv2_or_ort() -> None:
    """BR-02: _common must stay free of cv2 and onnxruntime."""
    run_import_purity_check(
        import_stmt="import recognition.infrastructure.face_pipeline._common  # noqa: F401",
        forbidden_prefixes=(
            "fastapi",
            "starlette",
            "recognition.worker",
            "recognition.api",
        ),
        forbidden_modules=("cv2", "onnxruntime"),
    )

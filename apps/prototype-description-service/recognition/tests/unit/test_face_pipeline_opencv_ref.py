"""FIR-3 S2: OpenCV reference aligner/detector/embedder + golden fixtures.

Heuristics: TEST-06/TEST-08 (determinism), rg-015 (landmark order contract),
AGT-06 (name the skip), rg-013-style import purity for opencv_ref.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline._common import EmbedBatchResult
from recognition.infrastructure.face_pipeline.aligner import (
    ALIGNED_SIZE,
    SFACE_CANONICAL_LANDMARKS_112,
    YUNET_LANDMARK_NAMES,
    AlignmentError,
    FivePointAligner,
    similarity_transform_matrix,
)
from recognition.infrastructure.face_pipeline.opencv_ref import (
    FacePipelineInputError,
    ZeroNormEmbeddingError,
    _ensure_bgr_u8,
    _parse_faces,
    resolve_sface_embedding_dim,
)
from recognition.infrastructure.face_pipeline.provenance import (
    MODEL_MANIFEST,
    load_verified_model,
)
from recognition.tests.unit.face_pipeline_support import (
    _FIXTURE_DIR,
    MODELS_PRESENT,
    MODELS_SKIP,
    SFACE_EMBEDDING_DIM,
    load_generate_goldens,
    load_json,
    run_import_purity_check,
)

_MODELS_PRESENT = MODELS_PRESENT
_MODELS_SKIP = MODELS_SKIP

# Module-level skip marker for models-dependent suite (BR-05: skip reason names fetch).
pytestmark_models = pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)

# Cross-host aligner crop tolerances (BR-07). Same-host oracle parity stays bit-exact.
_ALIGN_CROP_MAX_ABS = 1.0
_ALIGN_CROP_MAE = 0.05

# Version-drift cosine floor for committed embedding goldens (CVUP1-LC-03).
# Measurement 2026-07-29, OpenCV 5.0.0 / ORT 1.28.0 / numpy 2.5.1, N=50 runs on
# the deterministic synthetic 112×112 crop (and composed aligner→embedder path):
#   synthetic crop vs golden: bit-exact (vector maxabs=0; float64 cosine ≈ 1-1e-12)
#   composed aligner→embedder: bit-exact (maxabs=0)
# Noise floor = 0. Floor 0.99999999 is 10× above a 1e-9 slack band so same-host
# regen noise cannot greenwash a real embedder shift (prior decorative floor was
# 0.9999). Not the corpus OpenCV 4→5 upgrade self-similarity (min 0.999524 /
# median 0.999933 over 83 faces — opencv-5-embedding-drift.md); that protocol
# measures cross-version match-band drift, not golden noise floor.
_GOLDEN_COSINE_MIN = 0.99999999


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_load_json = load_json
_load_generate_goldens = load_generate_goldens


# ---------------------------------------------------------------------------
# BR-05: modelless tier — always runs (no ONNX)
# ---------------------------------------------------------------------------


def test_models_skip_reason_names_fetch_command() -> None:
    """Skip string must name the fetch script so CI skip is actionable (AGT-06)."""
    assert "fetch_face_pipeline_models.py" in _MODELS_SKIP
    assert "uv run python" in _MODELS_SKIP


def test_parse_faces_none_empty_and_1d() -> None:
    assert _parse_faces(None) == []
    assert _parse_faces(np.zeros((0, 15), dtype=np.float32)) == []
    row = np.arange(15, dtype=np.float32)
    out = _parse_faces(row)  # 1-D → reshape to one face
    assert len(out) == 1
    np.testing.assert_array_equal(out[0].bbox, row[0:4])
    np.testing.assert_array_equal(out[0].landmarks, row[4:14].reshape(5, 2))
    assert out[0].score == pytest.approx(float(row[14]))


def test_parse_faces_short_row_raises() -> None:
    with pytest.raises(FacePipelineInputError, match="expected ≥15"):
        _parse_faces(np.arange(10, dtype=np.float32))


def test_ensure_bgr_u8_float01_trap_raises() -> None:
    img01 = np.full((8, 8, 3), 0.5, dtype=np.float32)
    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        _ensure_bgr_u8(img01, label="probe")


def test_ensure_bgr_u8_float255_ok() -> None:
    img = np.full((8, 8, 3), 128.0, dtype=np.float64)
    out = _ensure_bgr_u8(img, label="probe")
    assert out.dtype == np.uint8
    assert out.shape == (8, 8, 3)
    assert int(out.max()) == 128


def test_resolve_sface_embedding_dim_from_manifest() -> None:
    assert resolve_sface_embedding_dim() == MODEL_MANIFEST["sface"].embedding_dim
    assert resolve_sface_embedding_dim() == 128


def test_resolve_sface_embedding_dim_none_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from recognition.infrastructure.face_pipeline import opencv_ref as ocv
    from recognition.infrastructure.face_pipeline.provenance import (
        MODEL_MANIFEST as CANONICAL_MANIFEST,
    )

    sface = CANONICAL_MANIFEST["sface"]
    monkeypatch.setitem(
        CANONICAL_MANIFEST,
        "sface",
        replace(sface, embedding_dim=None),
    )
    with pytest.raises(ValueError, match="embedding_dim is None"):
        ocv.resolve_sface_embedding_dim()


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
    """Cross-host crop compare is tolerance-based (BR-07); affine stays tight."""
    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    expected_affine = np.load(_FIXTURE_DIR / "aligner_affine.npy")
    expected_crop = np.load(_FIXTURE_DIR / "aligner_crop.npy")

    result = FivePointAligner().align(img, landmarks)

    assert result.crop.shape == (ALIGNED_SIZE, ALIGNED_SIZE, 3)
    np.testing.assert_allclose(result.affine, expected_affine, atol=1e-4)
    diff = np.abs(result.crop.astype(np.float32) - expected_crop.astype(np.float32))
    assert float(diff.max()) <= _ALIGN_CROP_MAX_ABS
    assert float(diff.mean()) <= _ALIGN_CROP_MAE


def test_aligner_determinism() -> None:
    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    a = FivePointAligner().align(img, landmarks)
    b = FivePointAligner().align(img, landmarks)
    np.testing.assert_array_equal(a.crop, b.crop)
    np.testing.assert_allclose(a.affine, b.affine, atol=0.0)


def test_aligner_float01_trap_raises() -> None:
    img01 = np.full((40, 40, 3), 0.25, dtype=np.float32)
    landmarks = np.array([[10, 10], [30, 10], [20, 18], [12, 28], [28, 28]], dtype=np.float64)
    with pytest.raises(AlignmentError, match=r"\[0,1\]-float"):
        FivePointAligner().align(img01, landmarks)


def test_aligner_float255_ok() -> None:
    img = np.full((40, 40, 3), 200.0, dtype=np.float64)
    landmarks = np.array([[10, 10], [30, 10], [20, 18], [12, 28], [28, 28]], dtype=np.float64)
    result = FivePointAligner().align(img, landmarks)
    assert result.crop.shape == (ALIGNED_SIZE, ALIGNED_SIZE, 3)
    assert result.crop.dtype == np.uint8


# ---------------------------------------------------------------------------
# Models-present suite
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_sface_models_load_via_verified_path() -> None:
    path = load_verified_model("sface")
    assert path.is_file()


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_five_point_aligner_matches_aligncrop_oracle_bitexact() -> None:
    """Same-host parity: FivePointAligner ≡ FaceRecognizerSF.alignCrop (BR-01)."""
    import cv2

    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    expected_crop = np.load(_FIXTURE_DIR / "aligner_crop.npy")

    gen = _load_generate_goldens()
    oracle = gen.oracle_align_crop(img, landmarks)
    portable = FivePointAligner().align(img, landmarks).crop

    np.testing.assert_array_equal(portable, oracle)
    np.testing.assert_array_equal(oracle, expected_crop)
    assert _sha256_bytes(oracle.tobytes()) == _sha256_bytes(expected_crop.tobytes())

    # Also exercise FaceRecognizerSF directly so the test does not depend only on gen.
    rec = cv2.FaceRecognizerSF.create(str(load_verified_model("sface")), "")
    face_box = gen._face_box_from_landmarks(landmarks, image_shape=img.shape)
    direct = rec.alignCrop(img, face_box)
    np.testing.assert_array_equal(portable, direct)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_golden_dim_norm_cosine() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    expected = np.load(_FIXTURE_DIR / "synthetic_112_embedding.npy")
    meta = _load_json("embedding_meta.json")
    cosine_min = float(meta.get("cosine_min", _GOLDEN_COSINE_MIN))

    batch = OpenCVSFaceEmbedder().embed([crop])
    emb = batch.vectors
    assert emb.shape == (1, SFACE_EMBEDDING_DIM)
    assert emb.shape[1] == meta["embedding_dim"]
    norm = float(np.linalg.norm(emb[0]))
    assert norm == pytest.approx(1.0, abs=1e-6)

    # L2 unit vectors: float64 re-norm cosine; floor from measured noise (CVUP1-LC-03).
    a = np.asarray(emb[0], dtype=np.float64)
    b = np.asarray(expected[0], dtype=np.float64)
    cosine = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    assert cosine >= cosine_min


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embedding_determinism_two_runs() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    emb = OpenCVSFaceEmbedder()
    a = emb.embed([crop]).vectors
    b = emb.embed([crop]).vectors
    np.testing.assert_array_equal(a, b)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_composed_aligner_embedder_matches_golden() -> None:
    """Aligner→embedder composition guards warpAffine drift (CVUP1-LC-03).

    synthetic_112_embedding feeds a pre-baked crop that never calls cv2.warpAffine.
    This test is the missing arm: raw image + landmarks → FivePointAligner → SFace.
    """
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    img = np.load(_FIXTURE_DIR / "aligner_source_image.npy")
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy")
    expected = np.load(_FIXTURE_DIR / "aligner_composed_embedding.npy")
    meta = _load_json("aligner_composed_embedding_meta.json")
    cosine_min = float(meta.get("cosine_min", _GOLDEN_COSINE_MIN))

    crop = FivePointAligner().align(img, landmarks).crop
    assert _sha256_bytes(crop.tobytes()) == meta["crop_sha256"]
    emb = OpenCVSFaceEmbedder().embed([crop]).vectors
    assert emb.shape == (1, SFACE_EMBEDDING_DIM)
    assert emb.shape[1] == meta["embedding_dim"]
    assert float(np.linalg.norm(emb[0])) == pytest.approx(1.0, abs=1e-6)

    a = np.asarray(emb[0], dtype=np.float64)
    b = np.asarray(expected[0], dtype=np.float64)
    cosine = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    assert cosine >= cosine_min, f"composed cosine={cosine} < {cosine_min}"


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_zero_norm_embedding_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    emb = OpenCVSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _zero_feature(_crop: np.ndarray) -> np.ndarray:
        return np.zeros((1, SFACE_EMBEDDING_DIM), dtype=np.float32)

    monkeypatch.setattr(emb, "_feature", _zero_feature)
    with pytest.raises(ZeroNormEmbeddingError, match="zero"):
        emb.embed([crop])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_nonfinite_norm_embedding_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """NaN raw features hit non-finite-norm branch (BR-05 modelless-weight path)."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    emb = OpenCVSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _nan_feature(_crop: np.ndarray) -> np.ndarray:
        return np.full((1, SFACE_EMBEDDING_DIM), np.nan, dtype=np.float32)

    monkeypatch.setattr(emb, "_feature", _nan_feature)
    with pytest.raises(ZeroNormEmbeddingError, match="non-finite|zero"):
        emb.embed([crop])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embed_dim_mismatch_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    emb = OpenCVSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")

    def _wrong_dim(_crop: np.ndarray) -> np.ndarray:
        return np.ones((1, 64), dtype=np.float32)

    monkeypatch.setattr(emb, "_feature", _wrong_dim)
    with pytest.raises(FacePipelineInputError, match="embedding dim"):
        emb.embed([crop])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embed_rejects_non_112_crops() -> None:
    """Fail-closed on wrong crop size/channels (BR-02)."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    emb = OpenCVSFaceEmbedder()
    with pytest.raises(FacePipelineInputError, match="expected shape"):
        emb.embed([np.zeros((64, 64, 3), dtype=np.uint8)])
    with pytest.raises(FacePipelineInputError, match="expected shape"):
        emb.embed([np.zeros((224, 224, 3), dtype=np.uint8)])
    with pytest.raises(FacePipelineInputError, match="H×W×3"):
        emb.embed([np.zeros((112, 112, 1), dtype=np.uint8)])
    with pytest.raises(FacePipelineInputError, match="H×W×3"):
        emb.embed([np.zeros((112, 112), dtype=np.uint8)])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embed_float01_trap_raises() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    crop01 = np.full((112, 112, 3), 0.8, dtype=np.float32)
    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        OpenCVSFaceEmbedder().embed([crop01])


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embed_float255_ok() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    crop_u8 = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    crop_f = crop_u8.astype(np.float64)
    emb = OpenCVSFaceEmbedder()
    a = emb.embed([crop_u8]).vectors
    b = emb.embed([crop_f]).vectors
    np.testing.assert_allclose(a, b, atol=1e-6)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_raw_sface_feature_not_prenormalized() -> None:
    """Our L2 step carries weight: native feature norm is not already 1 (BR-08)."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    emb = OpenCVSFaceEmbedder()
    crop = np.load(_FIXTURE_DIR / "synthetic_112_crop.npy")
    raw = np.asarray(emb._feature(crop), dtype=np.float32).reshape(-1)
    raw_norm = float(np.linalg.norm(raw))
    assert np.isfinite(raw_norm) and raw_norm > 0.0
    assert abs(raw_norm - 1.0) > 1e-3, (
        f"raw FaceRecognizerSF.feature appears pre-normalized (norm={raw_norm}); normalization step would be untested"
    )
    out = emb.embed([crop]).vectors
    assert float(np.linalg.norm(out[0])) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_embed_empty_batch_shape() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVSFaceEmbedder

    out = OpenCVSFaceEmbedder().embed([]).vectors
    assert out.shape == (0, SFACE_EMBEDDING_DIM)


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_empty_image_no_detections() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    det = OpenCVYuNetDetector()
    empty = np.zeros((100, 100, 3), dtype=np.uint8)
    out = det.detect([empty])
    assert out == [[]]


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_wrong_dtype_and_noncontiguous_coerced() -> None:
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    det = OpenCVYuNetDetector(score_threshold=0.9)
    # 0–255 float64 is accepted and coerced (BR-03).
    img_f = np.zeros((64, 64, 3), dtype=np.float64)
    img_f[:] = 10.0
    out = det.detect([img_f])
    assert out == [[]]

    # [0,1] float must fail closed (BR-03).
    with pytest.raises(FacePipelineInputError, match=r"\[0,1\]-float"):
        det.detect([np.full((64, 64, 3), 0.5, dtype=np.float32)])

    # Non-contiguous channel-strided view must still coerce (BR-08).
    big = np.zeros((64, 64, 6), dtype=np.uint8)
    view = big[:, :, ::2]
    assert not view.flags["C_CONTIGUOUS"], "test setup requires a non-C-contiguous view"
    out2 = det.detect([view])
    assert out2 == [[]]

    with pytest.raises(FacePipelineInputError):
        det.detect([np.zeros((10, 10), dtype=np.uint8)])  # missing channel dim


@pytest.mark.skipif(not _MODELS_PRESENT, reason=_MODELS_SKIP)
def test_detector_threshold_attrs_are_readonly() -> None:
    """Post-construction mutation must not silently no-op (BR-06)."""
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    det = OpenCVYuNetDetector(score_threshold=0.95, nms_threshold=0.3, top_k=100)
    assert det.score_threshold == pytest.approx(0.95)
    assert det.nms_threshold == pytest.approx(0.3)
    assert det.top_k == 100
    with pytest.raises(AttributeError):
        det.score_threshold = 0.1  # type: ignore[misc]
    with pytest.raises(AttributeError):
        det.nms_threshold = 0.5  # type: ignore[misc]
    with pytest.raises(AttributeError):
        det.top_k = 10  # type: ignore[misc]


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
    from recognition.infrastructure.face_pipeline.opencv_ref import OpenCVYuNetDetector

    golden_path = _FIXTURE_DIR / "detector_faces.json"
    skip_path = _FIXTURE_DIR / "detector_golden_skip.json"
    if skip_path.is_file() and not golden_path.is_file():
        note = _load_json("detector_golden_skip.json")
        pytest.skip(f"detector-output golden skipped ({note.get('status')}): {note.get('reason', '')[:200]}")
    assert golden_path.is_file(), "expected detector_faces.json golden fixture"
    meta = _load_json("detector_faces.json")
    assert meta["status"] == "recorded"

    gen = _load_generate_goldens()
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
    np.testing.assert_allclose(d0.bbox, np.asarray(exp["bbox_xywh"], dtype=np.float32), atol=tol["bbox_px"])
    np.testing.assert_allclose(
        d0.landmarks,
        np.asarray(exp["landmarks_xy"], dtype=np.float32),
        atol=tol["landmarks_px"],
    )
    assert d0.score == pytest.approx(exp["score"], abs=tol["score"])
    assert d0.landmarks.shape == (5, 2)
    # Landmark order: right eye x < left eye x on this frontal synthetic face.
    assert d0.landmarks[0, 0] < d0.landmarks[1, 0]

    # BR-04: each landmark is nearest its known drawn cartoon feature.
    drawn = gen.cartoon_drawn_feature_coords(
        size=int(proc["size"]),
        eye_sep=float(proc["eye_sep"]),
        mouth_y=float(proc["mouth_y"]),
    )
    expected_names = meta.get("expected_landmark_nearest_names") or list(YUNET_LANDMARK_NAMES)
    nearest_budget = float(tol.get("landmark_nearest_px", 50.0))
    name_list = list(drawn.keys())
    coords = {n: np.asarray(drawn[n], dtype=np.float64) for n in name_list}
    for i, expected_name in enumerate(expected_names):
        lm = d0.landmarks[i].astype(np.float64)
        dists = {n: float(np.linalg.norm(lm - coords[n])) for n in name_list}
        nearest = min(dists, key=dists.get)  # type: ignore[arg-type]
        assert nearest == expected_name, (
            f"landmark[{i}] nearest={nearest} (d={dists[nearest]:.1f}) "
            f"expected {expected_name}; dists={ {k: round(v, 1) for k, v in dists.items()} }"
        )
        assert dists[expected_name] <= nearest_budget, (
            f"landmark[{i}] ({expected_name}) dist={dists[expected_name]:.1f} > budget {nearest_budget}"
        )


# ---------------------------------------------------------------------------
# Import purity: package root stays cv2-free; opencv_ref may use cv2 only
# ---------------------------------------------------------------------------


def test_opencv_ref_import_purity_no_worker_http() -> None:
    """opencv_ref may import cv2; must not import worker/HTTP layers (rg-013)."""
    run_import_purity_check(
        import_stmt=(
            "import recognition.infrastructure.face_pipeline.opencv_ref  # noqa: F401\n"
            "import recognition.infrastructure.face_pipeline.aligner  # noqa: F401"
        ),
        forbidden_prefixes=(
            "fastapi",
            "starlette",
            "recognition.worker",
            "recognition.api",
        ),
        required_modules=("cv2",),
    )


def test_package_root_still_cv2_free() -> None:
    """Importing package root + provenance must not load cv2 (S1 BR-06)."""
    run_import_purity_check(
        import_stmt=(
            "import recognition.infrastructure.face_pipeline  # noqa: F401\n"
            "import recognition.infrastructure.face_pipeline.provenance  # noqa: F401"
        ),
        forbidden_prefixes=(),
        forbidden_modules=("cv2", "recognition.infrastructure.face_pipeline.opencv_ref"),
    )

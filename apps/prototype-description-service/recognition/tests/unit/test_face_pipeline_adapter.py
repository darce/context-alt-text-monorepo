"""FIR-4 S2: face_pipeline bridge + FacePipelineSettings tests.

Modelless tier runs in CI without ONNX. Models-present E2E uses
face_pipeline_support.MODELS_PRESENT skip gate.

Heuristics: [TEST-06][SERVE-08][EMB-01][PROV-06][RLSE-05][PROV-08]
"""

from __future__ import annotations

import importlib
import io
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from recognition.application.embedding.detector import DetectionAdapterError
from recognition.application.embedding.generator import UnavailableEmbeddingGenerator
from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.face_pipeline.provenance import DEFAULT_MODELS_DIR, MODEL_MANIFEST
from recognition.tests.unit.face_pipeline_support import (
    MODELS_PRESENT,
    MODELS_SKIP,
    SFACE_EMBEDDING_DIM,
    cartoon_from_procedure,
    load_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_settings_module():
    import recognition.config.settings as settings_module

    importlib.reload(settings_module)
    return settings_module


def _incumbent_decode(image_bytes: bytes) -> np.ndarray:
    """Reference decode matching InsightFaceAdapter._bytes_to_cv2 (inline)."""
    pil_image = Image.open(io.BytesIO(image_bytes))
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    rgb_array = np.array(pil_image)
    return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)


def _png_bytes(image: Image.Image, *, format: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=format)
    return buf.getvalue()


def _clear_settings_caches() -> None:
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _align_dims_to_sface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three-way guard needs manifest==pgvector==identity_detection (all 128)."""
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", str(SFACE_EMBEDDING_DIM))
    monkeypatch.setenv("PGVECTOR_DIM", str(SFACE_EMBEDDING_DIM))
    _clear_settings_caches()


@pytest.fixture(autouse=True)
def _restore_settings_caches_after_test() -> None:
    """Avoid leaking RECOGNITION_EMBEDDING_DIMENSION / PGVECTOR_DIM into sibling modules."""
    yield
    _clear_settings_caches()
    fpa.reset_shared_face_pipeline_runtime_for_tests()

# ---------------------------------------------------------------------------
# Modelless — settings
# ---------------------------------------------------------------------------


def test_face_pipeline_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_PROFILE", raising=False)
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", raising=False)
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.face_pipeline.profile == "insightface"
    assert settings.face_pipeline.models_dir is None
    assert settings.face_pipeline.resolved_models_dir == DEFAULT_MODELS_DIR
    assert settings.face_pipeline.score_threshold == 0.9
    assert settings.face_pipeline.nms_threshold == 0.3
    assert settings.face_pipeline.top_k == 5000
    assert settings.face_pipeline.timeout_s > 0


def test_face_pipeline_settings_env_bindings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(models))
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.face_pipeline.profile == "face_pipeline"
    assert settings.face_pipeline.models_dir == models
    assert settings.face_pipeline.resolved_models_dir == models


def test_invalid_face_pipeline_profile_raises_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "buffalo")
    mod = _fresh_settings_module()
    with pytest.raises((ValueError, ValidationError)):
        mod.RecognitionSettings()


def test_invalid_face_pipeline_profile_explicit_raises() -> None:
    mod = _fresh_settings_module()
    with pytest.raises((ValueError, ValidationError)):
        mod.FacePipelineSettings(profile="not_a_profile")  # type: ignore[arg-type]


def test_embedding_dimension_env_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.identity_detection.embedding_dimension == 128


def test_embedding_dimension_default_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.identity_detection.embedding_dimension == 512


# ---------------------------------------------------------------------------
# Modelless — pure helpers
# ---------------------------------------------------------------------------


def test_xywh_to_corner_conversion() -> None:
    assert fpa.xywh_to_corner_bbox(np.array([10.2, 20.7, 30.0, 40.0], dtype=np.float32)) == (
        10,
        20,
        40,
        60,
    )
    assert fpa.xywh_to_corner_bbox((0, 0, 5, 5)) == (0, 0, 5, 5)


def test_sface_manifest_model_id_exact() -> None:
    manifest = fpa.sface_embedding_model_manifest()
    assert isinstance(manifest, EmbeddingModelManifest)
    assert manifest.model_id == "opencv-sface@128d/l2/cosine"
    assert manifest.dimensions == 128
    assert manifest.framework == MODEL_MANIFEST["sface"].framework
    assert manifest.normalization == "l2"
    assert manifest.metric == "cosine"


def test_three_way_dim_guard_raises_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default dims are 512; SFace manifest is 128 → mismatch.
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    monkeypatch.delenv("PGVECTOR_DIM", raising=False)
    _clear_settings_caches()

    manifest = fpa.sface_embedding_model_manifest()
    with pytest.raises(ValueError, match="three-way guard"):
        fpa.assert_three_way_embedding_dimensions(manifest)

def test_decode_image_bytes_matches_incumbent_rgb_and_non_rgb() -> None:
    # Deterministic RGB image
    rgb = Image.new("RGB", (8, 6), color=(10, 20, 30))
    for x in range(8):
        for y in range(6):
            rgb.putpixel((x, y), (x * 10 % 256, y * 20 % 256, (x + y) * 7 % 256))
    rgb_bytes = _png_bytes(rgb)

    # Palette (non-RGB) and LA
    palette = Image.new("P", (8, 6))
    palette.putpalette([i % 256 for i in range(768)])
    for x in range(8):
        for y in range(6):
            palette.putpixel((x, y), (x + y * 8) % 256)
    palette_bytes = _png_bytes(palette)

    la = Image.new("LA", (8, 6), color=(100, 200))
    la_bytes = _png_bytes(la)

    for label, payload in (("rgb", rgb_bytes), ("palette", palette_bytes), ("la", la_bytes)):
        expected = _incumbent_decode(payload)
        actual = fpa.decode_image_bytes(payload)
        assert actual.shape == expected.shape, label
        assert actual.dtype == expected.dtype, label
        np.testing.assert_array_equal(actual, expected, err_msg=label)


def test_decode_failure_raises_on_garbage() -> None:
    with pytest.raises(Exception):
        fpa.decode_image_bytes(b"not-an-image")


@pytest.mark.asyncio
async def test_unavailable_generator_message() -> None:
    gen = fpa.face_pipeline_unavailable_generator()
    assert isinstance(gen, UnavailableEmbeddingGenerator)
    assert gen.reason == fpa.FACE_PIPELINE_GENERATOR_REASON
    assert "face_pipeline embeds in detect()" in gen.reason
    with pytest.raises(Exception) as exc_info:
        await gen.generate([b"crop"])
    assert "face_pipeline embeds in detect()" in str(exc_info.value)


@pytest.mark.asyncio
async def test_zero_face_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decode succeeds but detector returns no faces → empty list (not error)."""
    _align_dims_to_sface(monkeypatch)
    manifest = fpa.sface_embedding_model_manifest()
    mock_detector = MagicMock()
    mock_detector.detect.return_value = [[]]
    runtime = fpa.FacePipelineRuntime(
        detector=mock_detector,
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=manifest,
        models_dir=DEFAULT_MODELS_DIR,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )
    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    # Tiny solid image
    img = Image.new("RGB", (16, 16), color=(40, 40, 40))
    faces = await det.detect([_png_bytes(img)])
    assert faces == []


@pytest.mark.asyncio
async def test_decode_failure_path_raises_adapter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _align_dims_to_sface(monkeypatch)
    manifest = fpa.sface_embedding_model_manifest()
    runtime = fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=manifest,
        models_dir=DEFAULT_MODELS_DIR,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )
    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    with pytest.raises(DetectionAdapterError, match="decode failed"):
        await det.detect([b"definitely-not-image-bytes"])


# ---------------------------------------------------------------------------
# Models-present — E2E + atomicity
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not MODELS_PRESENT, reason=MODELS_SKIP)
@pytest.mark.asyncio
async def test_bytes_to_face_detection_e2e(monkeypatch: pytest.MonkeyPatch) -> None:
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    meta = load_json("detector_faces.json")
    bgr = cartoon_from_procedure(meta)
    ok, encoded = cv2.imencode(".png", bgr)
    assert ok
    image_bytes = encoded.tobytes()

    runtime = fpa.get_shared_face_pipeline_runtime(
        profile="face_pipeline",
        models_dir=DEFAULT_MODELS_DIR,
    )
    detector = fpa.FacePipelineFaceDetector(runtime, timeout=60.0)
    faces = await detector.detect([image_bytes])

    assert len(faces) > 0
    h, w = bgr.shape[:2]
    for face in faces:
        emb = face.embedding
        assert emb is not None
        assert emb.shape == (SFACE_EMBEDDING_DIM,)
        norm = float(np.linalg.norm(emb))
        assert abs(norm - 1.0) < 1e-3
        x1, y1, x2, y2 = face.bbox
        assert 0 <= x1 <= x2 <= w
        assert 0 <= y1 <= y2 <= h
        assert face.model_id == "opencv-sface@128d/l2/cosine"
        assert face.pose_pitch is None
        assert face.pose_yaw is None
        assert face.pose_roll is None

    fpa.reset_shared_face_pipeline_runtime_for_tests()


@pytest.mark.skipif(not MODELS_PRESENT, reason=MODELS_SKIP)
def test_atomic_unavailable_when_sface_tampered(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tampered SFace → whole runtime Unavailable (not YuNet-only half-load)."""
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    models = tmp_path / "models"
    models.mkdir()
    # Copy both models + licenses, then corrupt SFace bytes.
    for key in ("yunet", "sface"):
        entry = MODEL_MANIFEST[key]
        shutil.copy2(DEFAULT_MODELS_DIR / entry.file_name, models / entry.file_name)
        shutil.copy2(DEFAULT_MODELS_DIR / entry.license_file, models / entry.license_file)

    sface_path = models / MODEL_MANIFEST["sface"].file_name
    # Keep size so size check may pass or fail; flip one byte after copy so hash fails.
    data = bytearray(sface_path.read_bytes())
    data[0] = (data[0] + 1) % 256
    sface_path.write_bytes(bytes(data))

    with pytest.raises(fpa.FacePipelineRuntimeUnavailable):
        fpa.get_shared_face_pipeline_runtime(
            profile="face_pipeline",
            models_dir=models,
        )

    # Cached failure: second call still Unavailable (no retry into half-state).
    with pytest.raises(fpa.FacePipelineRuntimeUnavailable):
        fpa.get_shared_face_pipeline_runtime(
            profile="face_pipeline",
            models_dir=models,
        )

    fpa.reset_shared_face_pipeline_runtime_for_tests()


@pytest.mark.skipif(not MODELS_PRESENT, reason=MODELS_SKIP)
def test_shared_runtime_singleton_memo(monkeypatch: pytest.MonkeyPatch) -> None:
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    a = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    b = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    assert a is b
    fpa.reset_shared_face_pipeline_runtime_for_tests()

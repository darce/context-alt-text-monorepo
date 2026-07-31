"""FIR-4 S2: face_pipeline bridge + FacePipelineSettings tests.

Modelless tier runs in CI without ONNX. Models-present E2E uses
face_pipeline_support.MODELS_PRESENT skip gate.

Heuristics: [TEST-06][SERVE-08][EMB-01][PROV-06][RLSE-05][PROV-08]
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import io
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from recognition.application.embedding.detector import (
    DetectionAdapterError,
    DetectionTimeoutError,
    _compute_detection_quality,
)
from recognition.application.embedding.generator import UnavailableEmbeddingGenerator
from recognition.application.embedding.manifest import EmbeddingModelManifest
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.face_pipeline._common import EmbedBatchResult
from recognition.infrastructure.face_pipeline._common import RawDetection, ZeroNormEmbeddingError
from recognition.infrastructure.face_pipeline.aligner import AlignmentError
from recognition.infrastructure.face_pipeline.provenance import (
    DEFAULT_MODELS_DIR,
    MODEL_MANIFEST,
    ModelIntegrityError,
    ModelMissingError,
    load_verified_model,
)
from recognition.tests.unit.face_pipeline_support import (
    MODELS_PRESENT,
    MODELS_SKIP,
    SFACE_EMBEDDING_DIM,
    cartoon_from_procedure,
    load_json,
)

DECODE_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "face_pipeline" / "decode_golden"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_settings_module():
    import recognition.config.settings as settings_module

    importlib.reload(settings_module)
    return settings_module


def _png_bytes(image: Image.Image, *, format: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=format)
    return buf.getvalue()


def _clear_settings_caches() -> None:
    from db.settings import get_database_settings
    from recognition.config import get_settings

    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _rereload_settings_modules() -> None:
    """One more reload after the test so sibling files see a consistent final state."""
    import recognition.config.settings as settings_module

    importlib.reload(settings_module)
    _clear_settings_caches()


def _align_dims_to_sface(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three-way guard needs manifest==pgvector==identity_detection (all 128)."""
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", str(SFACE_EMBEDDING_DIM))
    monkeypatch.setenv("PGVECTOR_DIM", str(SFACE_EMBEDDING_DIM))
    _clear_settings_caches()


def _mock_runtime(monkeypatch: pytest.MonkeyPatch) -> fpa.FacePipelineRuntime:
    _align_dims_to_sface(monkeypatch)
    manifest = fpa.sface_embedding_model_manifest()
    return fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=manifest,
        models_dir=DEFAULT_MODELS_DIR,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )


@pytest.fixture(autouse=True)
def _restore_settings_caches_after_test() -> None:
    """Avoid leaking RECOGNITION_EMBEDDING_DIMENSION / PGVECTOR_DIM into sibling modules."""
    yield
    _rereload_settings_modules()
    fpa.reset_shared_face_pipeline_runtime_for_tests()


# ---------------------------------------------------------------------------
# Modelless — settings
# ---------------------------------------------------------------------------


def test_face_pipeline_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_PROFILE", raising=False)
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", raising=False)
    monkeypatch.delenv("RECOGNITION_FACE_PIPELINE_MAX_WORKERS", raising=False)
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.face_pipeline.profile == "insightface"
    assert settings.face_pipeline.models_dir is None
    assert settings.face_pipeline.resolved_models_dir == DEFAULT_MODELS_DIR
    assert settings.face_pipeline.score_threshold == 0.9
    assert settings.face_pipeline.nms_threshold == 0.3
    assert settings.face_pipeline.top_k == 5000
    assert settings.face_pipeline.timeout_s > 0
    # FIR4-BR-05: capacity is a validated settings field (default 2), not a hard-coded
    # adapter constant as the policy source of truth.
    assert settings.face_pipeline.max_workers == 2


def test_face_pipeline_settings_env_bindings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "face_pipeline")
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MODELS_DIR", str(models))
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MAX_WORKERS", "4")
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.face_pipeline.profile == "face_pipeline"
    assert settings.face_pipeline.models_dir == models
    assert settings.face_pipeline.resolved_models_dir == models
    assert settings.face_pipeline.max_workers == 4


def test_invalid_face_pipeline_profile_raises_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_PROFILE", "buffalo")
    mod = _fresh_settings_module()
    with pytest.raises((ValueError, ValidationError)):
        mod.RecognitionSettings()


def test_invalid_face_pipeline_profile_explicit_raises() -> None:
    mod = _fresh_settings_module()
    with pytest.raises((ValueError, ValidationError)):
        mod.FacePipelineSettings(profile="not_a_profile")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "raw",
    ["0", "-1", "-3", "abc", "", "1.5", "two"],
)
def test_face_pipeline_max_workers_rejects_invalid_at_load(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    """FIR4-BR-05 [CFG-01/02]: reject <=0 / malformed max_workers at settings load."""
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MAX_WORKERS", raw)
    mod = _fresh_settings_module()
    with pytest.raises((ValueError, ValidationError)):
        mod.RecognitionSettings()


def test_face_pipeline_max_workers_rejects_zero_explicit() -> None:
    """FIR4-BR-05: explicit zero is rejected (capacity must be positive)."""
    mod = _fresh_settings_module()
    with pytest.raises((ValueError, ValidationError)):
        mod.FacePipelineSettings(max_workers=0)


def test_embedding_dimension_env_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIR2-BR-01: PGVECTOR_DIM is the sole root for identity embedding_dimension."""
    monkeypatch.setenv("PGVECTOR_DIM", "128")
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    _clear_settings_caches()
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.identity_detection.embedding_dimension == 128


def test_embedding_dimension_default_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    monkeypatch.delenv("PGVECTOR_DIM", raising=False)
    _clear_settings_caches()
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.identity_detection.embedding_dimension == 512


def test_embedding_pgvector_pair_agree(monkeypatch: pytest.MonkeyPatch) -> None:
    """FIR2-BR-01: recognition dim follows PGVECTOR_DIM (single root)."""
    monkeypatch.setenv("PGVECTOR_DIM", "256")
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    _clear_settings_caches()
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.identity_detection.embedding_dimension == 256


def test_embedding_dimension_ignores_recognition_env_when_pgvector_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR2-BR-01: RECOGNITION_EMBEDDING_DIMENSION is not a second root."""
    monkeypatch.setenv("PGVECTOR_DIM", "384")
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "128")
    _clear_settings_caches()
    mod = _fresh_settings_module()
    settings = mod.RecognitionSettings()
    assert settings.identity_detection.embedding_dimension == 384


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
    from recognition.infrastructure.face_pipeline.provenance import numeric_runtime_fingerprint

    manifest = fpa.sface_embedding_model_manifest()
    assert isinstance(manifest, EmbeddingModelManifest)
    space = numeric_runtime_fingerprint().space_token
    assert manifest.model_id == f"opencv-sface+{space}@128d/l2/cosine"
    assert manifest.dimensions == 128
    assert manifest.framework == MODEL_MANIFEST["sface"].framework
    assert manifest.normalization == "l2"
    assert manifest.metric == "cosine"
    # Space token folds OpenCV major + onnxruntime (CVUP1-LC-02 / HARM-02).
    assert "cv" in space and "ort" in space


def test_three_way_dim_guard_raises_on_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default dims are 512; SFace manifest is 128 → mismatch.
    monkeypatch.delenv("RECOGNITION_EMBEDDING_DIMENSION", raising=False)
    monkeypatch.delenv("PGVECTOR_DIM", raising=False)
    _clear_settings_caches()

    manifest = fpa.sface_embedding_model_manifest()
    with pytest.raises(ValueError, match="three-way guard|dimension mismatch"):
        fpa.assert_three_way_embedding_dimensions(manifest)


def test_decode_image_bytes_matches_golden_fixtures() -> None:
    """CR-02: decode_image_bytes equals committed .npy from real InsightFaceAdapter."""
    for name in ("rgb", "palette", "la"):
        payload = (DECODE_GOLDEN_DIR / f"{name}.png").read_bytes()
        expected = np.load(DECODE_GOLDEN_DIR / f"{name}.npy")
        actual = fpa.decode_image_bytes(payload)
        assert actual.shape == expected.shape, name
        assert actual.dtype == expected.dtype, name
        np.testing.assert_array_equal(actual, expected, err_msg=name)


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
    runtime = _mock_runtime(monkeypatch)
    runtime.detector.detect.return_value = [[]]  # type: ignore[attr-defined]
    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    img = Image.new("RGB", (16, 16), color=(40, 40, 40))
    faces = await det.detect([_png_bytes(img)])
    assert faces == []


@pytest.mark.asyncio
async def test_decode_failure_path_raises_adapter_error(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _mock_runtime(monkeypatch)
    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    with pytest.raises(DetectionAdapterError, match="decode failed"):
        await det.detect([b"definitely-not-image-bytes"])


# ---------------------------------------------------------------------------
# CR-01 — phash + quality parity
# ---------------------------------------------------------------------------


def test_quality_with_pose_none_via_helper() -> None:
    """CR-01 modelless: quality is confidence+bbox only (same helper as adapter)."""
    score = _compute_detection_quality(
        confidence=0.95,
        bbox=(10, 20, 50, 80),  # corner (x1,y1,x2,y2) → 40×60
    )
    assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_build_embedding_runtime_detectors_share_detect_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GROKHARM-03 [RES-03, SERVE-01]: process-wide face_pipeline.detect breaker shared.

    Two detectors from build_embedding_runtime must hold the same breaker instance;
    tripping one must open the other. Reset hook clears the shared breaker.
    """
    from recognition.infrastructure.embeddings import runtime_factory as rf

    fpa.reset_shared_face_pipeline_runtime_for_tests()
    runtime = _mock_runtime(monkeypatch)
    monkeypatch.setattr(fpa, "get_shared_face_pipeline_runtime", lambda **_kw: runtime)

    settings = type(
        "S",
        (),
        {
            "runtime_mode": "production",
            "face_pipeline": type(
                "FP",
                (),
                {
                    "profile": "face_pipeline",
                    "resolved_models_dir": DEFAULT_MODELS_DIR,
                    "score_threshold": 0.9,
                    "nms_threshold": 0.3,
                    "top_k": 5000,
                    "timeout_s": 5.0,
                },
            )(),
        },
    )()

    det1, _gen1 = await rf.build_embedding_runtime(settings=settings)  # type: ignore[arg-type]
    det2, _gen2 = await rf.build_embedding_runtime(settings=settings)  # type: ignore[arg-type]
    assert isinstance(det1, fpa.FacePipelineFaceDetector)
    assert isinstance(det2, fpa.FacePipelineFaceDetector)
    assert det1._breaker is det2._breaker
    assert det1._breaker.adapter_name == "face_pipeline.detect"

    det1._breaker.force_open()
    assert det2._breaker.snapshot().is_open is True

    fpa.reset_shared_face_pipeline_runtime_for_tests()
    det3, _gen3 = await rf.build_embedding_runtime(settings=settings)  # type: ignore[arg-type]
    assert isinstance(det3, fpa.FacePipelineFaceDetector)
    assert det3._breaker is not det1._breaker
    assert det3._breaker.snapshot().is_open is False
    fpa.reset_shared_face_pipeline_runtime_for_tests()


@pytest.mark.asyncio
async def test_detect_populates_phash_and_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-01: one-pass path stamps image_phash + landmark_quality in [0,1]."""
    runtime = _mock_runtime(monkeypatch)
    landmarks = np.array(
        [[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]],
        dtype=np.float32,
    )
    raw = RawDetection(
        bbox=np.array([10.0, 10.0, 40.0, 50.0], dtype=np.float32),
        landmarks=landmarks,
        score=0.97,
    )
    runtime.detector.detect.return_value = [[raw]]  # type: ignore[attr-defined]
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    aligned = MagicMock()
    aligned.crop = crop
    runtime.aligner.align.return_value = aligned  # type: ignore[attr-defined]
    emb = np.ones(SFACE_EMBEDDING_DIM, dtype=np.float32)
    emb /= float(np.linalg.norm(emb))
    runtime.embedder.embed.return_value = EmbedBatchResult(vectors=np.stack([emb], axis=0), norms=np.array([2.5], dtype=np.float32))  # type: ignore[attr-defined]

    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    img = Image.new("RGB", (64, 64), color=(12, 34, 56))
    faces = await det.detect([_png_bytes(img)])
    assert len(faces) == 1
    assert faces[0].image_phash is not None
    assert isinstance(faces[0].image_phash, str)
    assert faces[0].landmark_quality is not None
    assert 0.0 <= faces[0].landmark_quality <= 1.0


# ---------------------------------------------------------------------------
# CR-03 — selective Unavailable caching
# ---------------------------------------------------------------------------


def test_selective_cache_missing_file_retries_after_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-03 / E2E-02: ModelMissingError is non-sticky; integrity is sticky."""
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    calls: list[str] = []

    def loader(**kwargs: object) -> fpa.FacePipelineRuntime:
        calls.append("load")
        if len(calls) == 1:
            raise ModelMissingError("model file missing for 'sface'")
        return fpa.FacePipelineRuntime(
            detector=MagicMock(),
            aligner=MagicMock(),
            embedder=MagicMock(),
            manifest=fpa.sface_embedding_model_manifest(),
            models_dir=DEFAULT_MODELS_DIR,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", loader)

    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError, match="model file missing"):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)

    # Non-sticky: second call retries loader and succeeds after 'fetch'.
    runtime = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    assert runtime is not None
    assert len(calls) == 2

    fpa.reset_shared_face_pipeline_runtime_for_tests()
    integrity_calls = 0

    def integrity_loader(**kwargs: object) -> fpa.FacePipelineRuntime:
        nonlocal integrity_calls
        integrity_calls += 1
        raise ModelIntegrityError("sha256 mismatch for 'sface'")

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", integrity_loader)

    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    assert integrity_calls == 1  # sticky — no second load


def test_missing_sface_models_dir_recovers_when_file_appears(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E-02: missing sface is non-sticky; second call succeeds after file appears (no reset)."""
    import hashlib

    from recognition.infrastructure.face_pipeline.provenance import ModelProvenance

    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    yunet_payload = b"syn-yunet-recover"
    sface_payload = b"syn-sface-recover"
    yunet_lic = b"MIT-yunet"
    sface_lic = b"Apache-sface"

    def _sha(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    monkeypatch.setitem(
        MODEL_MANIFEST,
        "yunet",
        ModelProvenance(
            file_name="face_detection_yunet_2026may.onnx",
            sha256=_sha(yunet_payload),
            source_url="https://example.test/yunet.onnx",
            source_ref="syn",
            license_id="MIT",
            license_file="LICENSE.yunet",
            license_sha256=_sha(yunet_lic),
            size_bytes=len(yunet_payload),
            framework="opencv",
        ),
    )
    monkeypatch.setitem(
        MODEL_MANIFEST,
        "sface",
        ModelProvenance(
            file_name="face_recognition_sface_2021dec.onnx",
            sha256=_sha(sface_payload),
            source_url="https://example.test/sface.onnx",
            source_ref="syn",
            license_id="Apache-2.0",
            license_file="LICENSE.sface",
            license_sha256=_sha(sface_lic),
            size_bytes=len(sface_payload),
            framework="opencv",
            embedding_dim=128,
            normalization="l2",
            metric="cosine",
        ),
    )
    (tmp_path / "face_detection_yunet_2026may.onnx").write_bytes(yunet_payload)
    (tmp_path / "LICENSE.yunet").write_bytes(yunet_lic)
    (tmp_path / "LICENSE.sface").write_bytes(sface_lic)
    # sface model file intentionally absent for first call

    load_calls = 0

    def loader(*, models_dir: Path, **kwargs: object) -> fpa.FacePipelineRuntime:
        nonlocal load_calls
        load_calls += 1
        # Exercise real missing-file / verify path.
        load_verified_model("yunet", models_dir=models_dir)
        load_verified_model("sface", models_dir=models_dir)
        return fpa.FacePipelineRuntime(
            detector=MagicMock(),
            aligner=MagicMock(),
            embedder=MagicMock(),
            manifest=fpa.sface_embedding_model_manifest(),
            models_dir=models_dir,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", loader)

    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError) as first_exc:
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert isinstance(first_exc.value.__cause__, ModelMissingError)
    assert load_calls == 1

    # Provision sface without reset_shared_face_pipeline_runtime_for_tests.
    (tmp_path / "face_recognition_sface_2021dec.onnx").write_bytes(sface_payload)
    runtime = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert runtime is not None
    assert load_calls == 2


def test_selective_cache_value_error_not_sticky(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-03: dim-guard ValueError raises without caching."""
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    calls = 0

    def loader(**kwargs: object) -> fpa.FacePipelineRuntime:
        nonlocal calls
        calls += 1
        raise ValueError("three-way guard mismatch")

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", loader)
    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    assert calls == 2


def test_sticky_integrity_recovers_after_operator_model_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GROKHARM-01 [RES-04/08, SERVE-01, RLSE-05]: ModelIntegrityError is sticky
    for unchanged file identity, but an operator atomic model replace
    (mtime/size/content identity change) must re-verify/rebuild and return a
    runtime without process restart or reset_shared_face_pipeline_runtime_for_tests.
    """
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    sface_name = "face_recognition_sface_2021dec.onnx"
    sface_path = tmp_path / sface_name
    sface_path.write_bytes(b"tampered-sface-bytes-v1")
    # Touch companion artifact so dir looks provisioned for operators/re-stat.
    (tmp_path / "face_detection_yunet_2026may.onnx").write_bytes(b"yunet-bytes")

    load_calls = 0
    allow_success = False

    def loader(*, models_dir: Path, **kwargs: object) -> fpa.FacePipelineRuntime:
        nonlocal load_calls
        load_calls += 1
        if not allow_success:
            raise ModelIntegrityError("sha256 mismatch for 'sface'")
        return fpa.FacePipelineRuntime(
            detector=MagicMock(),
            aligner=MagicMock(),
            embedder=MagicMock(),
            manifest=fpa.sface_embedding_model_manifest(),
            models_dir=models_dir,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", loader)

    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError, match="sha256 mismatch"):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert load_calls == 1

    # Same file identity: integrity sticky — no second load attempt.
    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert load_calls == 1

    # Operator atomically replaces model bytes (mtime/size/content identity change).
    sface_path.write_bytes(b"good-sface-bytes-after-operator-replace-v2")
    allow_success = True

    runtime = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert runtime is not None
    assert load_calls == 2  # must re-verify/rebuild after identity change
    fpa.reset_shared_face_pipeline_runtime_for_tests()


def test_sticky_license_integrity_recovers_after_license_only_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FIR-PM-01: license ModelIntegrityError is sticky while license identity is
    unchanged, but replacing only the license file must invalidate the sticky
    runtime key and reload without reset_shared_face_pipeline_runtime_for_tests.

    ONNX model bytes stay fixed — readiness already tracks license identity; the
    shared runtime cache key must too ([RES-04], [DRIFT-02], [PROV-08]).
    """
    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()

    yunet_name = MODEL_MANIFEST["yunet"].file_name
    sface_name = MODEL_MANIFEST["sface"].file_name
    yunet_lic = MODEL_MANIFEST["yunet"].license_file
    sface_lic = MODEL_MANIFEST["sface"].license_file

    (tmp_path / yunet_name).write_bytes(b"yunet-onnx-stable")
    (tmp_path / sface_name).write_bytes(b"sface-onnx-stable")
    (tmp_path / yunet_lic).write_bytes(b"MIT-yunet-v1")
    sface_lic_path = tmp_path / sface_lic
    sface_lic_path.write_bytes(b"Apache-sface-bad-v1")

    load_calls = 0
    allow_success = False

    def loader(*, models_dir: Path, **kwargs: object) -> fpa.FacePipelineRuntime:
        nonlocal load_calls
        load_calls += 1
        if not allow_success:
            raise ModelIntegrityError("license sha256 mismatch for 'sface'")
        return fpa.FacePipelineRuntime(
            detector=MagicMock(),
            aligner=MagicMock(),
            embedder=MagicMock(),
            manifest=fpa.sface_embedding_model_manifest(),
            models_dir=models_dir,
            score_threshold=0.9,
            nms_threshold=0.3,
            top_k=5000,
        )

    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", loader)

    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError, match="license sha256"):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert load_calls == 1

    # Unchanged model + license identity: sticky — no reload.
    with pytest.raises(fpa.FacePipelineRuntimeUnavailableError):
        fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert load_calls == 1, "unchanged license identity must keep sticky integrity failure"

    # License-only repair (ONNX bytes untouched).
    sface_lic_path.write_bytes(b"Apache-sface-good-after-repair-v2")
    allow_success = True

    runtime = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=tmp_path)
    assert runtime is not None
    assert load_calls == 2, (
        "license-only identity change must re-verify/rebuild without test reset; "
        f"load_calls={load_calls}"
    )
    fpa.reset_shared_face_pipeline_runtime_for_tests()


def test_grok47c_02_ort_inference_session_has_no_explicit_cleanup_contract() -> None:
    """GROK47C-02 adjudication [RES-04]: onnxruntime InferenceSession exposes no
    close/dispose/context-manager contract. Failed constructors leave no live
    session requiring explicit teardown; inventing a partial-resource cleanup API
    would be unsupported and brittle. Finding is false-positive / non-actionable.
    """
    import gc

    import onnxruntime as ort

    assert not hasattr(ort.InferenceSession, "close")
    assert not hasattr(ort.InferenceSession, "dispose")
    assert not hasattr(ort.InferenceSession, "release")
    assert not hasattr(ort.InferenceSession, "__enter__")
    assert not hasattr(ort.InferenceSession, "__exit__")

    try:
        ort.InferenceSession(b"not-a-valid-onnx-model", providers=["CPUExecutionProvider"])
        pytest.fail("expected InferenceSession constructor to reject invalid protobuf")
    except Exception:
        # Constructor failed before returning a session; nothing to dispose.
        pass
    gc.collect()


# ---------------------------------------------------------------------------
# CR-04 / CR-05 — semaphore, timeout, breaker, executor identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-05(b): timeout path → DetectionTimeoutError."""
    runtime = _mock_runtime(monkeypatch)

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        time.sleep(1.0)
        return []

    det = fpa.FacePipelineFaceDetector(runtime, timeout=0.05)
    monkeypatch.setattr(det, "_detect_sync", slow_detect)
    img = Image.new("RGB", (8, 8), color=(1, 2, 3))
    with pytest.raises(DetectionTimeoutError):
        await det.detect([_png_bytes(img)])


@pytest.mark.asyncio
async def test_semaphore_timeout_queues_third(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-04: saturated slots → third does not submit; admission is timeout-bounded.

    Residual workers hold both semaphore slots after the first two detect calls
    time out. A third call must not submit a worker (queues on semaphore) and
    must raise DetectionTimeoutError within the overall deadline rather than
    hang until residual workers finish (GROK47C-01 / single overall deadline).
    """
    runtime = _mock_runtime(monkeypatch)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="face_pipeline_test")
    semaphore = asyncio.Semaphore(2)
    submitted = 0
    submit_lock = threading.Lock()
    release_workers = threading.Event()

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        nonlocal submitted
        with submit_lock:
            submitted += 1
        # Hold the worker until the test releases — models head-of-line residual.
        release_workers.wait(timeout=5.0)
        return []

    det = fpa.FacePipelineFaceDetector(
        runtime,
        timeout=0.05,
        executor=executor,
        submit_semaphore=semaphore,
    )
    monkeypatch.setattr(det, "_detect_sync", slow_detect)
    payload = _png_bytes(Image.new("RGB", (4, 4), color=(9, 9, 9)))

    async def one() -> None:
        with pytest.raises(DetectionTimeoutError):
            await det.detect([payload])

    try:
        # Fill both slots with slow work that outlives the wait timeout.
        t1 = asyncio.create_task(one())
        t2 = asyncio.create_task(one())
        # Wait until both workers have been submitted.
        for _ in range(100):
            with submit_lock:
                if submitted >= 2:
                    break
            await asyncio.sleep(0.02)
        with submit_lock:
            assert submitted == 2

        # First two timed out; residual workers still hold semaphore slots.
        await asyncio.gather(t1, t2)
        with submit_lock:
            assert submitted == 2
        assert semaphore._value == 0

        # Third call: no third submit; admission deadline yields DetectionTimeoutError.
        with pytest.raises(DetectionTimeoutError):
            await det.detect([payload])
        with submit_lock:
            assert submitted == 2
        assert semaphore._value == 0
    finally:
        release_workers.set()
        await asyncio.sleep(0.05)
        executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_admission_timeout_when_executor_slots_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GROK47C-01 [RES-02/03/04/14/15][OBS-05]: admission wait is timeout-bounded.

    When both executor slots are held by workers that outlive ``timeout``, a third
    ``detect`` must raise ``DetectionTimeoutError`` within the configured timeout
    (not hang forever on ``_submit_semaphore.acquire``). Occupied slots must stay
    held (no third submit; no premature release). Breaker failure accounting must
    observe the admission timeout.
    """
    runtime = _mock_runtime(monkeypatch)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="face_pipeline_adm")
    semaphore = asyncio.Semaphore(2)
    submitted = 0
    submit_lock = threading.Lock()
    release_workers = threading.Event()
    timeout_s = 0.05

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        nonlocal submitted
        with submit_lock:
            submitted += 1
        # Hold beyond timeout so slots remain occupied after wait_for times out.
        release_workers.wait(timeout=10.0)
        return []

    det = fpa.FacePipelineFaceDetector(
        runtime,
        timeout=timeout_s,
        executor=executor,
        submit_semaphore=semaphore,
    )
    monkeypatch.setattr(det, "_detect_sync", slow_detect)
    payload = _png_bytes(Image.new("RGB", (4, 4), color=(11, 12, 13)))

    async def fill_slot() -> None:
        with pytest.raises(DetectionTimeoutError):
            await det.detect([payload])

    try:
        # Occupy both process-executor slots with residual workers.
        t1 = asyncio.create_task(fill_slot())
        t2 = asyncio.create_task(fill_slot())
        for _ in range(100):
            with submit_lock:
                if submitted >= 2:
                    break
            await asyncio.sleep(0.02)
        with submit_lock:
            assert submitted == 2

        # First two timed out on in-flight work; residual workers still hold slots.
        await asyncio.gather(t1, t2)
        failures_after_fill = det._breaker.snapshot().failure_count
        assert failures_after_fill == 2
        with submit_lock:
            assert submitted == 2
        assert semaphore._value == 0  # both slots still held by residual workers

        # Third caller: must fail within timeout (admission bound), not hang on acquire.
        # Outer asyncio.wait_for is only a RED harness guard against infinite hang; the
        # production path must raise DetectionTimeoutError on its own budget.
        harness_cap_s = timeout_s * 8  # 0.4s — well above timeout, well below hang
        t0 = time.perf_counter()
        with pytest.raises(DetectionTimeoutError) as exc_info:
            await asyncio.wait_for(det.detect([payload]), timeout=harness_cap_s)
        elapsed = time.perf_counter() - t0

        assert elapsed <= timeout_s * 4, (
            f"admission timeout took {elapsed:.3f}s; expected within ~{timeout_s * 4:.3f}s "
            f"(configured timeout={timeout_s}s)"
        )
        assert exc_info.value.timeout_s == timeout_s

        # Must not submit a third worker or free either residual slot.
        with submit_lock:
            assert submitted == 2
        assert semaphore._value == 0

        # Breaker must count the admission timeout as a failure [RES-03][OBS-05].
        assert det._breaker.snapshot().failure_count == failures_after_fill + 1
    finally:
        release_workers.set()
        # Let residual workers finish and release callbacks run before loop teardown.
        await asyncio.sleep(0.05)
        executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.asyncio
async def test_breaker_name_and_executor_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-05(c)(d): breaker name face_pipeline.detect; work on dedicated pool thread."""
    runtime = _mock_runtime(monkeypatch)
    runtime.detector.detect.return_value = [[]]  # type: ignore[attr-defined]
    seen_thread: dict[str, str] = {}

    def track_sync(image_bytes: bytes, media_id: str) -> list:
        seen_thread["name"] = threading.current_thread().name
        return []

    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    monkeypatch.setattr(det, "_detect_sync", track_sync)
    assert det._breaker is not None
    assert det._breaker.adapter_name == "face_pipeline.detect"

    img = Image.new("RGB", (8, 8), color=(3, 3, 3))
    await det.detect([_png_bytes(img)])
    assert seen_thread["name"].startswith("face_pipeline")


def test_reset_hook_preserves_process_lifetime_executor() -> None:
    """CR-10: reset clears runtime/breaker but must leave the process executor live.

    Capture executor identity before/after reset; the same usable executor must
    survive. Docstring is checked strictly (no tautological disjuncts).
    """
    fpa._ensure_face_pipeline_pool()
    before = fpa._FACE_PIPELINE_EXECUTOR
    assert before is not None
    assert before.submit(lambda: "pre-reset").result(timeout=5.0) == "pre-reset"

    fpa.reset_shared_face_pipeline_runtime_for_tests()

    after = fpa._FACE_PIPELINE_EXECUTOR
    assert after is before, "reset must not shut down or replace the process-lifetime executor"
    assert after.submit(lambda: "post-reset").result(timeout=5.0) == "post-reset"

    doc = (fpa.reset_shared_face_pipeline_runtime_for_tests.__doc__ or "").lower()
    assert "process-lifetime" in doc or "process lifetime" in doc
    assert "executor" in doc


# ---------------------------------------------------------------------------
# FIR4-BR-05 / FIR4-BR-06 — configurable pool, cross-loop admission, metrics
# RED contract: fail on hard-coded asyncio.Semaphore + absent saturation metrics.
# ---------------------------------------------------------------------------


def _rebind_face_pipeline_pool_from_settings() -> None:
    """Ask the adapter to size process pool/admission from live settings when available.

    GREEN may expose an explicit rebind hook; until then, this is a no-op and
    capacity assertions still fail against the hard-coded import-time pool.
    """
    for name in (
        "reconfigure_face_pipeline_pool_from_settings",
        "configure_face_pipeline_pool_from_settings",
        "reset_face_pipeline_pool_for_tests",
    ):
        fn = getattr(fpa, name, None)
        if callable(fn):
            fn()
            return


def _install_isolated_face_pipeline_metrics(monkeypatch: pytest.MonkeyPatch):
    """Bind get_default_metrics() to a fresh CollectorRegistry for sample asserts."""
    from prometheus_client import CollectorRegistry

    from recognition.interface_adapters.http.middleware import metrics as metrics_mod
    from recognition.interface_adapters.http.middleware.metrics import MetricsRegistry

    registry = CollectorRegistry()
    isolated = MetricsRegistry(registry=registry)
    monkeypatch.setattr(metrics_mod, "_default", isolated)
    return isolated, registry


def _metric_sample_value(registry, sample_name: str, labels: dict[str, str] | None = None) -> float:
    total = 0.0
    found = False
    for metric in registry.collect():
        for sample in metric.samples:
            if sample.name != sample_name:
                continue
            if labels is not None and dict(sample.labels) != labels:
                continue
            total += float(sample.value)
            found = True
    if not found:
        raise AssertionError(f"metric sample {sample_name!r} not found (labels={labels!r})")
    return total


def test_process_pool_capacity_follows_settings_max_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR4-BR-05: configured max_workers sizes process executor + admission gate.

    Capacity policy lives in RecognitionSettings / RECOGNITION_FACE_PIPELINE_MAX_WORKERS.
    Hard-coded ``_FACE_PIPELINE_MAX_WORKERS`` must not be the sole source of truth.
    """
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MAX_WORKERS", "3")
    _clear_settings_caches()
    from recognition.config import get_settings

    settings = get_settings()
    assert settings.face_pipeline.max_workers == 3

    _rebind_face_pipeline_pool_from_settings()

    # Public or internal process capacity must track settings after rebind/load.
    capacity = getattr(fpa, "face_pipeline_pool_max_workers", None)
    if callable(capacity):
        assert capacity() == 3
    else:
        # Fall back to shared executor sizing (process pool, not an injected test pool).
        executor = getattr(fpa, "_FACE_PIPELINE_EXECUTOR", None)
        assert executor is not None, "expected process-wide face pipeline executor"
        assert int(executor._max_workers) == 3

    # Admission gate capacity must match executor (no hard-coded 2 when settings=3).
    gate = getattr(fpa, "_FACE_PIPELINE_SUBMIT_SEMAPHORE", None)
    # Prefer a settings-backed, loop-safe gate. Module-global asyncio.Semaphore is forbidden.
    assert not isinstance(gate, asyncio.Semaphore), (
        "process admission must not be a module-global asyncio.Semaphore "
        "(binds to a closed loop under multi-loop use; FIR4-BR-05)"
    )
    # If a capacity-aware gate is exposed, it must report the configured size.
    gate_capacity = getattr(fpa, "face_pipeline_admission_capacity", None)
    if callable(gate_capacity):
        assert gate_capacity() == 3


@pytest.mark.asyncio
async def test_configured_capacity_bounds_default_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR4-BR-05 [PERF-03][RES-02]: settings max_workers=1 → only one default slot.

    Uses process defaults (no injected executor/semaphore) so capacity must come
    from RecognitionSettings, not hard-coded constants alone.
    """
    monkeypatch.setenv("RECOGNITION_FACE_PIPELINE_MAX_WORKERS", "1")
    _clear_settings_caches()
    from recognition.config import get_settings

    assert get_settings().face_pipeline.max_workers == 1
    _rebind_face_pipeline_pool_from_settings()

    runtime = _mock_runtime(monkeypatch)
    submitted = 0
    submit_lock = threading.Lock()
    release_workers = threading.Event()
    timeout_s = 0.05

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        nonlocal submitted
        with submit_lock:
            submitted += 1
        release_workers.wait(timeout=10.0)
        return []

    # Process defaults only — do not inject executor/semaphore.
    det = fpa.FacePipelineFaceDetector(runtime, timeout=timeout_s)
    monkeypatch.setattr(det, "_detect_sync", slow_detect)
    payload = _png_bytes(Image.new("RGB", (4, 4), color=(21, 22, 23)))

    async def one() -> None:
        with pytest.raises(DetectionTimeoutError):
            await det.detect([payload])

    try:
        t1 = asyncio.create_task(one())
        for _ in range(100):
            with submit_lock:
                if submitted >= 1:
                    break
            await asyncio.sleep(0.02)
        with submit_lock:
            assert submitted == 1

        await t1

        # Second call must admission-timeout without a second active worker submit.
        t0 = time.perf_counter()
        with pytest.raises(DetectionTimeoutError):
            await asyncio.wait_for(det.detect([payload]), timeout=timeout_s * 8)
        elapsed = time.perf_counter() - t0
        assert elapsed <= timeout_s * 4
        with submit_lock:
            assert submitted == 1, "capacity=1 must not admit a second concurrent worker"
    finally:
        release_workers.set()
        await asyncio.sleep(0.05)


def test_admission_gate_safe_across_sequential_event_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR4-BR-05 [RES-02/04/15]: process admission survives loop A → close → loop B.

    Module-global ``asyncio.Semaphore`` + ``loop.call_soon_threadsafe(release)``
    binds release to loop A. After A closes, residual worker completion cannot
    free slots → loop B starves. Contract: saturate *all* process slots on A,
    close A, let residuals finish, then B recovers full capacity without stale-loop
    RuntimeError, over-release, or exceeding configured active workers.
    """
    runtime = _mock_runtime(monkeypatch)
    payload = _png_bytes(Image.new("RGB", (4, 4), color=(31, 32, 33)))
    release_workers = threading.Event()
    submitted = 0
    submit_lock = threading.Lock()
    timeout_s = 0.05

    # Process-wide pool capacity (defaults). Must recover fully across loops.
    capacity_fn = getattr(fpa, "face_pipeline_pool_max_workers", None)
    if callable(capacity_fn):
        capacity = int(capacity_fn())
    else:
        capacity = int(fpa._FACE_PIPELINE_EXECUTOR._max_workers)
    assert capacity >= 1

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        nonlocal submitted
        with submit_lock:
            submitted += 1
        release_workers.wait(timeout=10.0)
        return []

    def run_on_fresh_loop(coro_factory):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro_factory())
        finally:
            with contextlib.suppress(Exception):
                loop.run_until_complete(asyncio.sleep(0))
            loop.close()
            asyncio.set_event_loop(None)

    # --- Loop A: fill every process slot, time out, leave residual workers ---
    async def loop_a_body() -> None:
        det = fpa.FacePipelineFaceDetector(runtime, timeout=timeout_s)
        monkeypatch.setattr(det, "_detect_sync", slow_detect)

        async def one() -> None:
            with pytest.raises(DetectionTimeoutError):
                await det.detect([payload])

        tasks = [asyncio.create_task(one()) for _ in range(capacity)]
        for _ in range(200):
            with submit_lock:
                if submitted >= capacity:
                    break
            await asyncio.sleep(0.02)
        with submit_lock:
            assert submitted == capacity
        await asyncio.gather(*tasks)

    try:
        run_on_fresh_loop(loop_a_body)
        with submit_lock:
            assert submitted == capacity

        # Residuals still hold every slot; loop A is already closed.
        assert not release_workers.is_set()

        # Free residuals after loop A is gone — release must not require loop A.
        release_workers.set()
        time.sleep(0.2)

        # --- Loop B: full capacity recovered → capacity new submits ---
        release_workers_b = threading.Event()
        with submit_lock:
            submitted_before_b = submitted

        def slow_detect_b(image_bytes: bytes, media_id: str) -> list:
            nonlocal submitted
            with submit_lock:
                submitted += 1
            release_workers_b.wait(timeout=10.0)
            return []

        async def loop_b_body() -> None:
            det = fpa.FacePipelineFaceDetector(runtime, timeout=timeout_s)
            monkeypatch.setattr(det, "_detect_sync", slow_detect_b)

            async def one() -> None:
                with pytest.raises(DetectionTimeoutError):
                    await asyncio.wait_for(det.detect([payload]), timeout=timeout_s * 8)

            tasks = [asyncio.create_task(one()) for _ in range(capacity)]
            await asyncio.gather(*tasks)

        try:
            run_on_fresh_loop(loop_b_body)
        except RuntimeError as exc:
            pytest.fail(f"stale event-loop error on loop B: {exc}")

        with submit_lock:
            new_submits = submitted - submitted_before_b
            assert new_submits == capacity, (
                f"expected {capacity} new submits on loop B after full slot release; "
                f"got {new_submits} (0 ⇒ admission slots leaked across closed loop A)"
            )

        # No over-admission while B residuals still hold all slots.
        with submit_lock:
            submitted_mid = submitted

        async def loop_b_overflow() -> None:
            det = fpa.FacePipelineFaceDetector(runtime, timeout=timeout_s)
            monkeypatch.setattr(det, "_detect_sync", slow_detect_b)
            with pytest.raises(DetectionTimeoutError):
                await asyncio.wait_for(det.detect([payload]), timeout=timeout_s * 8)

        run_on_fresh_loop(loop_b_overflow)
        with submit_lock:
            assert submitted == submitted_mid, "must not exceed configured active workers"
    finally:
        release_workers.set()
        with contextlib.suppress(NameError):
            release_workers_b.set()  # type: ignore[name-defined]
        time.sleep(0.05)
        # RED may leak process admission slots (closed-loop release). Restore a
        # fresh gate so sibling tests using process defaults are not poisoned.
        try:
            n = int(fpa._FACE_PIPELINE_EXECUTOR._max_workers)
            rebind = getattr(fpa, "reconfigure_face_pipeline_pool_from_settings", None)
            if callable(rebind):
                rebind()
            else:
                fpa._FACE_PIPELINE_SUBMIT_SEMAPHORE = asyncio.Semaphore(n)
        except Exception:
            pass


def test_metrics_registry_exports_face_pipeline_saturation_series() -> None:
    """FIR4-BR-06 [OBS-01/05/08]: stable named saturation metrics on MetricsRegistry."""
    from prometheus_client import CollectorRegistry

    from recognition.interface_adapters.http.middleware.metrics import MetricsRegistry

    metrics = MetricsRegistry(registry=CollectorRegistry())
    assert hasattr(metrics, "face_pipeline_submit_wait_seconds"), (
        "MetricsRegistry must export face_pipeline_submit_wait_seconds histogram"
    )
    assert hasattr(metrics, "face_pipeline_admission_timeouts_total"), (
        "MetricsRegistry must export face_pipeline_admission_timeouts_total counter"
    )

    names = {sample.name for metric in metrics.registry.collect() for sample in metric.samples}
    assert "face_pipeline_submit_wait_seconds_count" in names or (
        "face_pipeline_submit_wait_seconds_bucket" in names
    )
    assert "face_pipeline_admission_timeouts_total" in names


@pytest.mark.asyncio
async def test_submit_wait_and_admission_timeout_metrics_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FIR4-BR-06: saturation is observable via metric samples, not only an info log.

    After a real admission timeout under load, the wait histogram must record an
    observation and the admission-timeout counter must increment. Labels stay
    low-cardinality (no media_id / path / raw URL labels).
    """
    isolated, registry = _install_isolated_face_pipeline_metrics(monkeypatch)

    # Registry seam must expose the series even before traffic.
    assert hasattr(isolated, "face_pipeline_submit_wait_seconds")
    assert hasattr(isolated, "face_pipeline_admission_timeouts_total")

    timeouts_before = _metric_sample_value(registry, "face_pipeline_admission_timeouts_total")
    wait_count_before = _metric_sample_value(registry, "face_pipeline_submit_wait_seconds_count")

    runtime = _mock_runtime(monkeypatch)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face_pipeline_met")
    # Inject a loop-local gate only to control saturation deterministically; metrics
    # still flow through the service MetricsRegistry seam under test.
    semaphore = asyncio.Semaphore(1)
    submitted = 0
    submit_lock = threading.Lock()
    release_workers = threading.Event()
    timeout_s = 0.05

    def slow_detect(image_bytes: bytes, media_id: str) -> list:
        nonlocal submitted
        with submit_lock:
            submitted += 1
        release_workers.wait(timeout=10.0)
        return []

    det = fpa.FacePipelineFaceDetector(
        runtime,
        timeout=timeout_s,
        executor=executor,
        submit_semaphore=semaphore,
        metrics=isolated.face_pipeline,
    )
    monkeypatch.setattr(det, "_detect_sync", slow_detect)
    payload = _png_bytes(Image.new("RGB", (4, 4), color=(41, 42, 43)))

    async def fill_and_timeout() -> None:
        with pytest.raises(DetectionTimeoutError):
            await det.detect([payload])

    try:
        t1 = asyncio.create_task(fill_and_timeout())
        for _ in range(100):
            with submit_lock:
                if submitted >= 1:
                    break
            await asyncio.sleep(0.02)
        await t1
        assert semaphore._value == 0

        # Second caller waits on admission then times out → metrics must move.
        with pytest.raises(DetectionTimeoutError):
            await asyncio.wait_for(det.detect([payload]), timeout=timeout_s * 8)

        timeouts_after = _metric_sample_value(registry, "face_pipeline_admission_timeouts_total")
        wait_count_after = _metric_sample_value(registry, "face_pipeline_submit_wait_seconds_count")

        assert timeouts_after >= timeouts_before + 1, (
            f"admission timeout counter did not increment: before={timeouts_before} after={timeouts_after}"
        )
        assert wait_count_after >= wait_count_before + 1, (
            f"submit wait histogram count did not increase: before={wait_count_before} after={wait_count_after}"
        )

        # Guard high-cardinality labels: series must not carry media_id / path labels.
        for metric in registry.collect():
            if metric.name not in {
                "face_pipeline_submit_wait_seconds",
                "face_pipeline_admission_timeouts",
            }:
                continue
            for sample in metric.samples:
                label_keys = set(sample.labels)
                assert "media_id" not in label_keys
                assert "path" not in label_keys
                assert "url" not in label_keys
    finally:
        release_workers.set()
        await asyncio.sleep(0.05)
        executor.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# CR-06 — zero-norm fail-closed prefix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_norm_embedding_drops_face(monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E-04 / CR-06: ZeroNormEmbeddingError drops the face; all-drop → []."""
    runtime = _mock_runtime(monkeypatch)
    landmarks = np.array(
        [[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]],
        dtype=np.float32,
    )
    raw = RawDetection(
        bbox=np.array([10.0, 10.0, 40.0, 50.0], dtype=np.float32),
        landmarks=landmarks,
        score=0.9,
    )
    runtime.detector.detect.return_value = [[raw]]  # type: ignore[attr-defined]
    aligned = MagicMock()
    aligned.crop = np.zeros((112, 112, 3), dtype=np.uint8)
    runtime.aligner.align.return_value = aligned  # type: ignore[attr-defined]
    runtime.embedder.embed.side_effect = ZeroNormEmbeddingError("zero vector")  # type: ignore[attr-defined]

    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    faces = await det.detect([_png_bytes(Image.new("RGB", (64, 64), color=(1, 1, 1)))])
    assert faces == []


@pytest.mark.asyncio
async def test_per_face_align_failure_keeps_sibling(monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E-04: one face with degenerate landmarks is dropped; sibling still returned."""
    runtime = _mock_runtime(monkeypatch)
    good_lm = np.array(
        [[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]],
        dtype=np.float32,
    )
    bad_lm = np.zeros((5, 2), dtype=np.float32)
    good = RawDetection(
        bbox=np.array([10.0, 10.0, 40.0, 50.0], dtype=np.float32),
        landmarks=good_lm,
        score=0.95,
    )
    bad = RawDetection(
        bbox=np.array([50.0, 10.0, 40.0, 50.0], dtype=np.float32),
        landmarks=bad_lm,
        score=0.91,
    )
    runtime.detector.detect.return_value = [[good, bad]]  # type: ignore[attr-defined]

    def _align(_bgr: object, landmarks: np.ndarray) -> MagicMock:
        if float(np.var(landmarks)) == 0.0:
            raise AlignmentError("degenerate landmarks (zero variance); cannot align")
        aligned = MagicMock()
        aligned.crop = np.zeros((112, 112, 3), dtype=np.uint8)
        return aligned

    runtime.aligner.align.side_effect = _align  # type: ignore[attr-defined]
    emb = np.ones(SFACE_EMBEDDING_DIM, dtype=np.float32)
    emb /= float(np.linalg.norm(emb))
    runtime.embedder.embed.return_value = EmbedBatchResult(vectors=np.stack([emb], axis=0), norms=np.array([2.5], dtype=np.float32))  # type: ignore[attr-defined]

    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    faces = await det.detect([_png_bytes(Image.new("RGB", (128, 128), color=(10, 20, 30)))])
    assert len(faces) == 1
    assert faces[0].confidence == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# CR-07 — degenerate bbox dropped before align/embed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_degenerate_bbox_dropped_before_align(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-07: x2<=x1 or y2<=y1 after clamp → drop; align never called for it."""
    runtime = _mock_runtime(monkeypatch)
    # Zero-size bbox (w=0,h=0) → corners equal after clamp.
    raw = RawDetection(
        bbox=np.array([5.0, 5.0, 0.0, 0.0], dtype=np.float32),
        landmarks=np.zeros((5, 2), dtype=np.float32),
        score=0.99,
    )
    runtime.detector.detect.return_value = [[raw]]  # type: ignore[attr-defined]
    det = fpa.FacePipelineFaceDetector(runtime, timeout=5.0)
    faces = await det.detect([_png_bytes(Image.new("RGB", (32, 32), color=(7, 7, 7)))])
    assert faces == []
    runtime.aligner.align.assert_not_called()  # type: ignore[attr-defined]
    runtime.embedder.embed.assert_not_called()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# CR-08 — atomic _SHARED tuple
# ---------------------------------------------------------------------------


def test_shared_is_single_tuple_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-08: module holds one _SHARED tuple, not separate key/runtime globals."""
    assert hasattr(fpa, "_SHARED")
    assert not hasattr(fpa, "_SHARED_RUNTIME") or fpa.__dict__.get("_SHARED_RUNTIME", "gone") == "gone"
    # Prefer absence of split globals.
    assert getattr(fpa, "_SHARED_KEY", "missing") == "missing" or not hasattr(fpa, "_SHARED_KEY")

    _align_dims_to_sface(monkeypatch)
    fpa.reset_shared_face_pipeline_runtime_for_tests()
    assert fpa._SHARED is None

    runtime = fpa.FacePipelineRuntime(
        detector=MagicMock(),
        aligner=MagicMock(),
        embedder=MagicMock(),
        manifest=fpa.sface_embedding_model_manifest(),
        models_dir=DEFAULT_MODELS_DIR,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )
    monkeypatch.setattr(fpa, "_load_face_pipeline_runtime", lambda **kw: runtime)
    got = fpa.get_shared_face_pipeline_runtime(profile="face_pipeline", models_dir=DEFAULT_MODELS_DIR)
    assert got is runtime
    assert fpa._SHARED is not None
    key, val = fpa._SHARED
    assert val is runtime
    assert isinstance(key, tuple)
    # Dim pair is part of memo key (CR-03/CR-09).
    assert SFACE_EMBEDDING_DIM in key


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
        # model_id carries the numeric-runtime fingerprint (CVUP-1). Assert the
        # stable contract only — the mutable cv/ort segment has its own
        # discrimination tests in test_face_pipeline_provenance.py, and pinning
        # it here just re-creates the stale literal this replaced.
        assert face.model_id.startswith("opencv-sface+")
        assert face.model_id.endswith("@128d/l2/cosine")
        # 5-point landmarks yield no pitch; yaw/roll are landmark proxies (FIR-4).
        assert face.pose_pitch is None
        assert face.pose_yaw is not None
        assert face.pose_roll is not None
        # Bound against the FIXTURE, not the formula: degrees(atan(...)) can
        # never leave (-90, 90) and degrees(atan2(...)) can never leave
        # (-180, 180], so range checks on those intervals are green by
        # construction and certify nothing (TEST-06). This canvas is a frontal,
        # upright synthetic face — measured yaw=-0.236°, roll=+0.105° — so a
        # landmark-index swap, a sign flip, or a radians/degrees confusion in
        # the proxy shows up as a violation of the ±2° envelope.
        assert abs(face.pose_yaw) <= 2.0, f"frontal fixture yaw={face.pose_yaw}"
        assert abs(face.pose_roll) <= 2.0, f"upright fixture roll={face.pose_roll}"
        # CR-01 models-present: phash + quality populated
        assert face.image_phash is not None
        assert face.landmark_quality is not None
        assert 0.0 <= face.landmark_quality <= 1.0

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

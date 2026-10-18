"""Expected configs must agree with the real verified retry runtime [TEST-15]."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from db.settings import get_database_settings
from recognition.application import health
from recognition.config import get_settings
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.face_pipeline import ort_adapters
from recognition.infrastructure.face_pipeline.model_space import ModelSpace
from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST
from recognition.tests.unit.test_face_runtime_attestation_drift import ServingSession
from recognition.tests.unit.test_face_scale_retry_contract import KNOB, _small_visible_only_at_640, bgr_image
from recognition.tests.unit.test_face_scale_retry_provenance import YuNetServing
from recognition.tests.unit.test_loaded_face_session_producer import artifact_fixture, native_ort_tripwire, sha
from recognition.worker import scan_worker

from recognition.tests.unit.test_face_scale_retry_provenance import _adapter, _verified_runtime


@pytest.mark.parametrize("knob", [0, 640])
def test_verified_runtime_retry_controls(monkeypatch, tmp_path, knob):
    runtime = _verified_runtime(monkeypatch, tmp_path, lambda _h, _w: [], knob=knob)
    detector = _adapter(monkeypatch, runtime, {})

    assert runtime.frozen_config.retry_max_side == knob
    assert detector._drift_reason(runtime.frozen_config, None) is None


@pytest.fixture
def composition(monkeypatch, tmp_path):
    """Only artifact bytes and ORT sessions are synthetic; builders stay real."""
    get_settings.cache_clear()
    get_database_settings.cache_clear()
    health.reset_face_pipeline_verify_cache_for_tests()
    monkeypatch.setattr(fpa, "_SHARED", None)
    monkeypatch.setattr(fpa, "_API_ADAPTERS", deque(maxlen=256))

    def build(profile, knob):
        detector_dir = tmp_path / "detector"
        detector_dir.mkdir()
        embedder_name = "auraface" if profile == "auraface" else "sface"
        dimension = 512 if profile == "auraface" else 128
        embedder_dir = tmp_path / "embedder" if profile == "auraface" else detector_dir
        embedder_dir.mkdir(exist_ok=True)
        artifact_fixture(detector_dir, monkeypatch, "yunet")
        artifact_fixture(embedder_dir, monkeypatch, embedder_name)
        yunet = YuNetServing(_small_visible_only_at_640(0.5, 0.5))
        embedder = ServingSession(np.ones((1, dimension), dtype=np.float32))
        constructors = []

        def constructor(source, sess_options=None, providers=None, **kwargs):
            if isinstance(source, bytes):
                names = [name for name in ("yunet", embedder_name)
                         if MODEL_MANIFEST[name].sha256 == sha(source)]
                assert len(names) == 1, "unknown synthetic verified buffer"
                name = names[0]
            else:
                name = Path(source).stem
            assert name in {"yunet", embedder_name}, "profile must not mix embedders"
            constructors.append(name)
            session = yunet if name == "yunet" else embedder
            session.options, session.providers = sess_options, providers or []
            return session

        monkeypatch.setattr(ort_adapters.ort, "InferenceSession", constructor)
        for name, value in {
            "RECOGNITION_RUNTIME_MODE": "production",
            "RECOGNITION_FACE_PIPELINE_PROFILE": profile,
            "RECOGNITION_FACE_PIPELINE_MODELS_DIR": str(detector_dir),
            "RECOGNITION_AURAFACE_MODELS_DIR": str(embedder_dir),
            "RECOGNITION_EMBEDDING_DIMENSION": str(dimension),
            "PGVECTOR_DIM": str(dimension),
            "RECOGNITION_FACE_SCORE_THRESHOLD": "0.9",
            "RECOGNITION_FACE_NMS_THRESHOLD": "0.3",
            "RECOGNITION_FACE_TOP_K": "5000",
        }.items():
            monkeypatch.setenv(name, value)
        if knob is None:
            monkeypatch.delenv(KNOB, raising=False)
        else:
            monkeypatch.setenv(KNOB, str(knob))
        get_settings.cache_clear()
        get_database_settings.cache_clear()
        return SimpleNamespace(settings=get_settings(), detector_dir=detector_dir,
                               embedder_dir=embedder_dir, dimension=dimension,
                               constructors=constructors, yunet=yunet)

    yield build
    get_settings.cache_clear()
    get_database_settings.cache_clear()
    health.reset_face_pipeline_verify_cache_for_tests()


def _probe(profile, fixture):
    if profile == "face_pipeline":
        return health.check_face_pipeline_models(fixture.detector_dir)
    return health.check_model_space(ModelSpace.AURAFACE, fixture.embedder_dir)


@pytest.mark.parametrize("profile", ["face_pipeline", "auraface"])
@pytest.mark.parametrize("knob", [None, 0, 640], ids=["unset-off", "explicit-off", "enabled"])
def test_health_expected_config_matches_real_runtime(monkeypatch, composition, profile, knob):
    fixture = composition(profile, knob)
    detector, _generator = asyncio.run(scan_worker.build_embedding_runtime(settings=fixture.settings))
    assert isinstance(detector, fpa.FacePipelineFaceDetector)
    captured = []
    observe = health._with_face_runtime_observations

    def capture(result, runtime, expected_config):
        captured.append((runtime, expected_config))
        return observe(result, runtime, expected_config)

    monkeypatch.setattr(health, "_with_face_runtime_observations", capture)
    result = _probe(profile, fixture)

    assert result.status is health.HealthStatus.OK, result.detail
    assert len(captured) == 1
    runtime, expected = captured[0]
    assert runtime is detector._runtime
    assert fixture.constructors == ["yunet", "auraface" if profile == "auraface" else "sface"]
    assert expected.profile == profile
    assert expected.models_dir == fixture.detector_dir.resolve()
    assert expected.embedder_models_dir == fixture.embedder_dir.resolve()
    assert expected.embedding_dimension == expected.pgvector_dimension == fixture.dimension
    assert expected.retry_max_side == runtime.detector.retry_max_side == (knob or 0), (
        "CAUSAL_RED: health expected config must match the loaded retry setting"
    )
    if profile == "auraface":
        assert expected == runtime.frozen_config
        serving = result.payload["face_runtime"]["api_adapters"]
        assert len(serving) == 1
        record = serving[0]["runtime_record"]
        assert record["state"] == "loaded_unexercised"
        assert record["reason_code"] is None
    else:
        # The existing SFace loader has no verified-pair receipt; do not invent one.
        assert runtime.frozen_config is None


@pytest.mark.parametrize("knob", [None, 0, 640], ids=["unset-off", "explicit-off", "enabled"])
def test_worker_expected_config_matches_real_inference_builder(monkeypatch, composition, knob):
    fixture = composition("auraface", knob)
    detector, _generator = asyncio.run(scan_worker.build_embedding_runtime(settings=fixture.settings))
    assert isinstance(detector, fpa.FacePipelineFaceDetector)
    assert fixture.constructors == ["yunet", "auraface"]
    captured = []
    observe = detector.loaded_runtime_record

    def capture(**kwargs):
        captured.append(kwargs["expected_config"])
        return observe(**kwargs)

    monkeypatch.setattr(detector, "loaded_runtime_record", capture)
    worker = object.__new__(scan_worker.ScanWorker)
    worker._detector = detector
    worker._embedding_runtime_ready = False
    record = worker._observe_embedding_runtime()

    assert len(captured) == 1
    expected = captured[0]
    assert expected.retry_max_side == detector._runtime.frozen_config.retry_max_side == (knob or 0), (
        "CAUSAL_RED: worker expected config must match the loaded retry setting"
    )
    assert expected == detector._runtime.frozen_config
    assert record.state == "loaded_unexercised"
    assert record.reason_code is None
    assert worker._embedding_runtime_ready
    monkeypatch.setattr(fpa, "decode_image_bytes", lambda _data: bgr_image(1280, 960))
    monkeypatch.setattr(fpa.InsightFaceFaceDetector, "_compute_phash", lambda _data: "synthetic-phash")
    faces = detector._detect_sync(b"synthetic", "retry-worker-fixture")
    assert len(faces) == (1 if knob == 640 else 0)
    assert len(fixture.yunet.input_shapes) == (2 if knob == 640 else 1)


@pytest.mark.parametrize("profile", ["face_pipeline", "auraface"])
@pytest.mark.parametrize("raw", ["1000", "-1", "abc"])
def test_health_invalid_retry_knob_fails_closed(composition, profile, raw):
    fixture = composition(profile, raw)
    result = _probe(profile, fixture)

    assert result.status is health.HealthStatus.UNHEALTHY
    assert "must be 0 (off) or 640" in result.detail
    assert fixture.constructors == []


@pytest.mark.parametrize("raw", ["1000", "-1", "abc"])
def test_worker_invalid_retry_knob_rejects_retained_runtime(monkeypatch, composition, raw):
    fixture = composition("auraface", 0)
    detector, _generator = asyncio.run(scan_worker.build_embedding_runtime(settings=fixture.settings))
    assert isinstance(detector, fpa.FacePipelineFaceDetector)
    monkeypatch.setenv(KNOB, raw)
    worker = object.__new__(scan_worker.ScanWorker)
    worker._detector = detector
    worker._embedding_runtime_ready = True

    with pytest.raises(ValueError, match="must be 0 \\(off\\) or 640"):
        worker._observe_embedding_runtime()
    assert not worker._embedding_runtime_ready

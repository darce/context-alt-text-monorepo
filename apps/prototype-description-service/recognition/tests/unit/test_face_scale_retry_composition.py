"""FIR scale-retry composition: adapter one-pass, runtime cache key, and golden digest.

Companion to test_face_scale_retry_contract.py. Exercises the existing public
composition (FacePipelineFaceDetector._detect_sync_impl over the real
_load_face_pipeline_runtime / get_shared_face_pipeline_runtime) with fake ORT
sessions. Nothing from the proposed retry is imported: the knob is set through
RECOGNITION_FACE_DETECTION_RETRY_MAX_SIDE only.

Knob-off digest and runtime-identity controls pass on base. Causal RED tests
must fail on assertions (missing retry), never on setup errors.

Heuristics: [TEST-15][RES-02]
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from db.settings import get_database_settings
from recognition.config import get_settings
from recognition.config import settings as detection_config
from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.infrastructure.face_pipeline import ort_adapters
from recognition.tests.unit.test_face_scale_retry_contract import (  # noqa: F401  (autouse fixture)
    BIG_FULL,
    BIG_LANDMARKS,
    KNOB,
    RETRY_MAX_SIDE,
    SMALL_LANDMARKS,
    FakeSFaceSession,
    FakeYuNetSession,
    _modelless_face_runtime,
    _small_visible_only_at_640,
    bgr_image,
    build_runtime,
)

SMALL_CORNERS = (320.0, 240.0, 480.0, 440.0)  # FaceDetection.bbox is (x1, y1, x2, y2)


def _clear_settings() -> None:
    get_settings.cache_clear()
    get_database_settings.cache_clear()


def _shared_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, knob: int | None) -> fpa.FacePipelineRuntime:
    yunet = FakeYuNetSession(lambda _h, _w: [])
    sface = FakeSFaceSession()
    monkeypatch.setattr(
        ort_adapters,
        "_ort_session",
        lambda model_source: yunet if Path(model_source).name == "yunet.onnx" else sface,
    )
    if knob is None:
        monkeypatch.delenv(KNOB, raising=False)
    else:
        monkeypatch.setenv(KNOB, str(knob))
    _clear_settings()
    return fpa.get_shared_face_pipeline_runtime(
        models_dir=tmp_path,
        embedder_models_dir=tmp_path,
        score_threshold=0.9,
        nms_threshold=0.3,
        top_k=5000,
    )


def _adapter(monkeypatch: pytest.MonkeyPatch, runtime: fpa.FacePipelineRuntime) -> fpa.FacePipelineFaceDetector:
    monkeypatch.setattr(fpa, "decode_image_bytes", lambda _data: bgr_image(1280, 960))
    monkeypatch.setattr(fpa.InsightFaceFaceDetector, "_compute_phash", lambda _data: "fixture-phash")
    return fpa.FacePipelineFaceDetector(
        runtime,
        timeout=1,
        executor=SimpleNamespace(),
        submit_semaphore=SimpleNamespace(),
        breaker=SimpleNamespace(),
    )


def _spy_align(monkeypatch: pytest.MonkeyPatch, runtime: fpa.FacePipelineRuntime) -> list[tuple[tuple[int, ...], np.ndarray]]:
    calls: list[tuple[tuple[int, ...], np.ndarray]] = []
    real_align = runtime.aligner.align

    def spy(bgr: np.ndarray, landmarks: np.ndarray):
        calls.append((tuple(int(v) for v in bgr.shape), np.array(landmarks, copy=True)))
        return real_align(bgr, landmarks)

    monkeypatch.setattr(runtime.aligner, "align", spy)
    return calls


# ---------------------------------------------------------------------------
# Causal RED: one adapter pass recovers the face and aligns original pixels.
# ---------------------------------------------------------------------------


def test_adapter_recovers_640_only_face_and_aligns_original_bgr_with_projected_landmarks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _ = build_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(0.5, 0.5), knob=RETRY_MAX_SIDE)
    calls = _spy_align(monkeypatch, runtime)
    adapter = _adapter(monkeypatch, runtime)

    faces = adapter._detect_sync_impl(b"synthetic", "media-retry-640")

    assert len(faces) == 1, "adapter must surface the retry-recovered face (base returns none)"
    assert len(calls) == 1, "aligner must be called once for the recovered face"
    shape, landmarks = calls[0]
    assert shape == (960, 1280, 3), "aligner must receive the ORIGINAL BGR, never the 640 resize"
    np.testing.assert_allclose(landmarks, np.asarray(SMALL_LANDMARKS), atol=2.0)
    np.testing.assert_allclose(faces[0].bbox, SMALL_CORNERS, atol=2.0)


def test_adapter_without_knob_returns_no_face_for_640_only_face_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _ = build_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(0.5, 0.5), knob=None)
    calls = _spy_align(monkeypatch, runtime)
    adapter = _adapter(monkeypatch, runtime)

    faces = adapter._detect_sync_impl(b"synthetic", "media-knob-off")

    assert faces == []
    assert calls == []


def test_full_resolution_face_is_aligned_on_original_pixels_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime, _ = build_runtime(monkeypatch, tmp_path, lambda _h, _w: [BIG_FULL], knob=None)
    calls = _spy_align(monkeypatch, runtime)
    adapter = _adapter(monkeypatch, runtime)

    faces = adapter._detect_sync_impl(b"synthetic", "media-full-res")

    assert len(faces) == 1
    assert len(calls) == 1
    assert calls[0][0] == (960, 1280, 3)
    np.testing.assert_allclose(calls[0][1], np.asarray(BIG_LANDMARKS), atol=1e-3)
    # Base truncates float corners with int(): 99.999985 -> 99, so allow one pixel.
    np.testing.assert_allclose(faces[0].bbox, (100.0, 100.0, 400.0, 400.0), atol=1.0)


# ---------------------------------------------------------------------------
# Causal RED: the knob is part of the shared runtime identity (cache key).
# ---------------------------------------------------------------------------


def test_shared_runtime_is_rebuilt_when_retry_knob_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    unset = _shared_runtime(monkeypatch, tmp_path, knob=None)
    enabled = _shared_runtime(monkeypatch, tmp_path, knob=RETRY_MAX_SIDE)

    assert enabled is not unset, "retry knob must participate in the shared runtime cache key"


# goldenABI digest guard intentionally absent here: _freeze_pair returns {} unless
# both adapters hold a VerifiedModelBytes artifact, so frozen_preprocessing_spec is
# None on this model-free SFace composition. Blocker, not a passing control.
# ---------------------------------------------------------------------------
# Control: the existing second floor still applies to retry-recovered faces.
# ---------------------------------------------------------------------------


@pytest.fixture
def second_floor_provider(monkeypatch: pytest.MonkeyPatch):
    provider = detection_config.IdentityDetectionSettings(default_threshold=0.97)
    seen: list[detection_config.IdentityDetectionSettings] = []

    def resolve():
        seen.append(provider)
        return provider

    monkeypatch.setattr(detection_config, "resolve_effective_detection_settings", resolve)
    return provider, seen


def _spy_embed(monkeypatch: pytest.MonkeyPatch, runtime: fpa.FacePipelineRuntime):
    batches = []
    real_embed = runtime.embedder.embed

    def spy(crops):
        batch = real_embed(crops)
        batches.append(batch)
        return batch

    monkeypatch.setattr(runtime.embedder, "embed", spy)
    return batches


def test_second_floor_still_applies_to_retry_recovered_face_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, second_floor_provider
) -> None:
    provider, seen = second_floor_provider
    emitted_counts = []
    retry_visible = _small_visible_only_at_640(0.5, 0.5)

    def visible(h, w):
        emitted = retry_visible(h, w)
        emitted_counts.append(len(emitted))
        return emitted

    runtime, yunet = build_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE)
    aligned = _spy_align(monkeypatch, runtime)
    embedded = _spy_embed(monkeypatch, runtime)
    adapter = _adapter(monkeypatch, runtime)

    faces = adapter._detect_sync_impl(b"synthetic", "media-floor")

    assert [face for face in faces if face.confidence < 0.97] == []
    assert faces == []
    assert seen == [provider]
    assert seen[0].default_threshold == 0.97
    assert emitted_counts == [0, 1], "the floor must receive a real retry-recovered face"
    assert yunet.input_shapes == [(1, 3, 960, 1280), (1, 3, 480, 640)]
    assert len(aligned) == 1
    assert len(embedded) == 1 and len(embedded[0].vectors) == 1


@pytest.mark.parametrize("knob", [None, RETRY_MAX_SIDE], ids=["full-resolution-off", "retry-recovered"])
def test_second_floor_healthy_above_threshold_face_is_not_dropped_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, second_floor_provider, knob: int | None
) -> None:
    provider, seen = second_floor_provider
    emitted_counts = []
    retry_visible = _small_visible_only_at_640(0.5, 0.5, score=0.99)

    def visible(h, w):
        emitted = [replace(BIG_FULL, score=0.99)] if knob is None else retry_visible(h, w)
        emitted_counts.append(len(emitted))
        return emitted

    runtime, yunet = build_runtime(monkeypatch, tmp_path, visible, knob=knob)
    aligned = _spy_align(monkeypatch, runtime)
    embedded = _spy_embed(monkeypatch, runtime)
    adapter = _adapter(monkeypatch, runtime)

    faces = adapter._detect_sync_impl(b"synthetic", "media-floor-healthy")

    assert len(faces) == 1, "a healthy face above the second floor must survive"
    assert faces[0].confidence == pytest.approx(0.99)
    assert faces[0].confidence >= 0.97
    assert seen == [provider]
    assert seen[0].default_threshold == 0.97
    assert len(aligned) == 1
    assert len(embedded) == 1 and len(embedded[0].vectors) == 1
    if knob is None:
        assert emitted_counts == [1]
        assert yunet.input_shapes == [(1, 3, 960, 1280)]
    else:
        assert emitted_counts == [0, 1]
        assert yunet.input_shapes == [(1, 3, 960, 1280), (1, 3, 480, 640)]

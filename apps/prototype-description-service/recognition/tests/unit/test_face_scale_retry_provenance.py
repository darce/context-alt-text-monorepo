"""FIR scale-retry provenance: frozen preprocessing digest and per-call retry lineage.

Companion to test_face_scale_retry_composition.py. The modelless composition has
no VerifiedModelBytes, so _freeze_pair returns {} and _detect_sync builds no
frozen spec. This module uses the verified AuraFace pair (artifact_fixture from
test_loaded_face_session_producer: tiny synthetic graphs in a controlled tmp
directory, no real model bytes) so that the real loader freezes a
FrozenPreprocessingSpecV1 and _detect_sync builds an ExecutionReceiptV1.

Knob-off digest and no-second-pass lineage controls pass on base. Causal RED
tests must fail on assertions (missing retry), never on setup errors.

Heuristics: [TEST-15][DATA-14]
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from recognition.infrastructure.embeddings import face_pipeline_adapter as fpa
from recognition.tests.unit.test_face_runtime_attestation_drift import ServingSession
from recognition.tests.unit.test_face_scale_retry_contract import (
    BIG_FULL,
    KNOB,
    RETRY_MAX_SIDE,
    FakeYuNetSession,
    _small_visible_only_at_640,
    bgr_image,
)
from recognition.tests.unit.test_loaded_face_session_producer import PREFIX, artifact_fixture, sha

ADAPTER = "recognition.infrastructure.embeddings.face_pipeline_adapter"

# Measured by executing the base loader with the knob unset (see RED log); not invented.
KNOB_OFF_SPEC_DIGEST = "80888b1fab47dfa39dcb2397908374cf8960b41abb988fced7894ef24b133e2d"


class YuNetServing(FakeYuNetSession):
    """Fake YuNet with the readback getters the verified session metadata uses."""

    def get_inputs(self):
        return [SimpleNamespace(name="input", shape=[1, 3, 640, 640], type="tensor(float)")]

    def get_outputs(self):
        return [SimpleNamespace(name=name, shape=[1], type="tensor(float)")
                for name in importlib.import_module(PREFIX + "ort_adapters")._YUNET_OUTPUT_NAMES]

    def get_session_options(self):
        return self.options

    def get_provider_options(self):
        return {provider: {} for provider in self.providers}

    def get_providers(self):
        return self.providers

    def get_modelmeta(self):
        return SimpleNamespace(custom_metadata_map={}, producer_name="fixture", graph_name="fixture",
                               domain="", description="", version=1)


def _clear_settings() -> None:
    importlib.import_module("recognition.config").get_settings.cache_clear()
    importlib.import_module("db.settings").get_database_settings.cache_clear()


def _verified_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, visible, *, knob: int | None):
    artifact_fixture(tmp_path, monkeypatch, "yunet")
    artifact_fixture(tmp_path, monkeypatch, "auraface")
    provenance = importlib.import_module(PREFIX + "provenance")
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    yunet = YuNetServing(visible)
    embedder = ServingSession()

    def constructor(source, sess_options=None, providers=None, **kwargs):
        if isinstance(source, bytes):
            names = [name for name in ("yunet", "auraface") if provenance.MODEL_MANIFEST[name].sha256 == sha(source)]
            assert len(names) == 1, "unknown synthetic model buffer"
            name = names[0]
        else:
            name = Path(source).stem
        session = yunet if name == "yunet" else embedder
        session.options = sess_options
        session.providers = providers or []
        return session

    monkeypatch.setattr(adapters.ort, "InferenceSession", constructor)
    if knob is None:
        monkeypatch.delenv(KNOB, raising=False)
    else:
        monkeypatch.setenv(KNOB, str(knob))
    monkeypatch.setenv("RECOGNITION_EMBEDDING_DIMENSION", "512")
    monkeypatch.setenv("PGVECTOR_DIM", "512")
    _clear_settings()
    space = importlib.import_module(PREFIX + "model_space").ModelSpace.AURAFACE
    return fpa._load_face_pipeline_runtime(space=space, models_dir=tmp_path, embedder_models_dir=tmp_path,
                                           score_threshold=0.9, nms_threshold=0.3, top_k=5000)


def _adapter(monkeypatch: pytest.MonkeyPatch, runtime, images: dict[bytes, np.ndarray]):
    monkeypatch.setattr(fpa, "decode_image_bytes", lambda data: images[data].copy())
    monkeypatch.setattr(fpa.InsightFaceFaceDetector, "_compute_phash", lambda _data: "fixture-phash")
    return fpa.FacePipelineFaceDetector(runtime, timeout=1, executor=SimpleNamespace(),
                                        submit_semaphore=SimpleNamespace(), breaker=SimpleNamespace())


# ---------------------------------------------------------------------------
# goldenABI: frozen preprocessing digest with the knob off is an absolute baseline.
# ---------------------------------------------------------------------------


def test_knob_off_frozen_preprocessing_digest_matches_measured_baseline_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, lambda _h, _w: [], knob=None)

    assert runtime.frozen_preprocessing_spec is not None, "verified AuraFace pair must freeze a spec"
    assert runtime.frozen_preprocessing_spec.digest() == KNOB_OFF_SPEC_DIGEST


def test_enabled_retry_knob_changes_frozen_preprocessing_digest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    visible = _small_visible_only_at_640(0.5, 0.5)
    off = _verified_runtime(monkeypatch, tmp_path, visible, knob=None).frozen_preprocessing_spec
    on = _verified_runtime(monkeypatch, tmp_path, visible, knob=RETRY_MAX_SIDE).frozen_preprocessing_spec

    assert off is not None and on is not None
    assert on.digest() != off.digest(), "CAUSAL_RED: enabled retry recipe must change the frozen digest"


# ---------------------------------------------------------------------------
# Retry lineage: input_lineage is present only when the second pass executed.
# ---------------------------------------------------------------------------


def test_knob_off_full_resolution_call_records_no_retry_lineage_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, lambda _h, _w: [BIG_FULL], knob=None)
    adapter = _adapter(monkeypatch, runtime, {b"synthetic": bgr_image(1280, 960)})

    faces = adapter._detect_sync(b"synthetic", "media-lineage-off")

    assert len(faces) == 1
    assert not adapter._execution_receipt.input_lineage


def test_knob_on_single_pass_at_or_below_640_records_no_retry_lineage_control(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(0.5, 0.5), knob=RETRY_MAX_SIDE)
    adapter = _adapter(monkeypatch, runtime, {b"synthetic": bgr_image(640, 480)})

    faces = adapter._detect_sync(b"synthetic", "media-lineage-single")

    assert len(faces) == 1
    assert not adapter._execution_receipt.input_lineage


def test_retry_pass_records_input_lineage_when_second_pass_executes_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(0.5, 0.5), knob=RETRY_MAX_SIDE)
    adapter = _adapter(monkeypatch, runtime, {b"synthetic": bgr_image(1280, 960)})

    faces = adapter._detect_sync(b"synthetic", "media-lineage-retry")

    assert len(faces) == 1, "CAUSAL_RED: retry pass must recover the 640-only face"
    assert adapter._execution_receipt.input_lineage, "CAUSAL_RED: executed retry pass must record input_lineage"


def test_retry_lineage_is_per_call_and_never_inherited_or_mutated_red(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime = _verified_runtime(monkeypatch, tmp_path, _small_visible_only_at_640(0.5, 0.5), knob=RETRY_MAX_SIDE)
    adapter = _adapter(monkeypatch, runtime, {b"large": bgr_image(1280, 960), b"small": bgr_image(640, 480)})

    faces = adapter._detect_sync(b"large", "media-retry-first")
    first = adapter._execution_receipt

    assert len(faces) == 1, "CAUSAL_RED: retry pass must recover the 640-only face"
    assert first.input_lineage, "CAUSAL_RED: executed retry pass must record input_lineage"
    recorded = dict(first.input_lineage)

    adapter._detect_sync(b"small", "media-single-second")
    second = adapter._execution_receipt

    assert second is not first, "each call must build its own execution receipt"
    assert not second.input_lineage, "a single-pass call must not inherit the previous retry lineage"
    assert dict(first.input_lineage) == recorded, "an earlier receipt's lineage must not be mutated later"

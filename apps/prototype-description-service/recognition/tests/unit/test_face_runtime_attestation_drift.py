"""c77 ABI-00/F03/F04: retained runtime observations, never health relabels.

The fixture uses actual adapter inference with injected tiny artifacts and
recording constructors. Configuration follows the coordinator-frozen cache-key
inputs; synthetic execution never supplies independent attestation lineage.
EMB-05: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#emb-05
"""
from __future__ import annotations

import builtins
import importlib
import os
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from recognition.tests.unit.test_loaded_face_session_producer import (
    PREFIX, RecordingSession, artifact_fixture, sha, symbol,
)
from recognition.tests.unit.test_loaded_face_preprocessing_receipts import asymmetric_crop, landmarks

ADAPTER = "recognition.infrastructure.embeddings.face_pipeline_adapter"
NOW = datetime(2026, 10, 13, tzinfo=UTC)


@pytest.fixture(autouse=True)
def native_ort_tripwire(monkeypatch):
    native = importlib.import_module("onnxruntime.capi._pybind_state")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(1)
        pytest.fail("NATIVE_ORT_TRIPWIRE: native construction forbidden", pytrace=False)

    monkeypatch.setattr(native, "InferenceSession", forbidden)
    yield calls
    database = importlib.import_module("db.settings")
    database.get_database_settings.cache_clear()
    assert len(calls) == 0, "NATIVE_ORT_CONSTRUCTIONS must remain zero"


class ServingSession(RecordingSession):
    """Readback describes the options actually supplied to the fake."""

    def get_session_options(self):
        return self.options

    def get_provider_options(self):
        return {provider: {} for provider in self.providers}

    def get_providers(self):
        return self.providers

    def get_modelmeta(self):
        return SimpleNamespace(custom_metadata_map={}, producer_name="fixture",
                               graph_name="fixture", domain="", description="", version=1)


def artifact_paths(root):
    return {str(root / name) for name in (
        "yunet.onnx", "auraface.onnx", "LICENSE.yunet", "LICENSE.auraface")}


def is_artifact(path, paths):
    if isinstance(path, int):
        return False
    return os.path.abspath(os.fsdecode(os.fspath(path))) in paths


def forbid_artifact_reads(monkeypatch, root, forbidden):
    paths = artifact_paths(root)
    for owner, name in ((Path, "open"), (Path, "read_bytes"),
                        (builtins, "open"), (os, "open")):
        original = getattr(owner, name)

        def guarded(path, *args, _original=original, **kwargs):
            if is_artifact(path, paths):
                return forbidden(path, *args, **kwargs)
            return _original(path, *args, **kwargs)

        monkeypatch.setattr(owner, name, guarded)


def loaded_record_values():
    # Incomplete producer record; no fabricated graph, execution or observed width.
    return dict(producer_abi_version=1, runtime_generation_id="retained-old",
                model_id="synthetic-auraface512", effective_profile="auraface",
                declared_embedding_dimension=512, observed_embedding_dimension=None,
                preprocessing_id="arcface-112", compatibility_sha256=sha(b"synthetic-compatibility"),
                config_sha256=sha(b"synthetic-config"), sessions={}, frozen_preprocessing_spec=None,
                execution_receipt=None, state="not_loaded", reason_code="synthetic_missing_pair",
                observed_at=NOW)


@pytest.mark.parametrize("version", [None, True, False, 0, 2, "1", 1.0])
def test_runtime_record_rejects_unknown_bool_noninteger_versions(version):
    record_type = symbol(PREFIX + "loaded_session", "LoadedRuntimeRecordV1")
    values = loaded_record_values()
    values["producer_abi_version"] = version
    with pytest.raises((ValueError, TypeError)):
        record_type(**values)


def test_runtime_record_requires_version_and_rejects_extra_fields():
    record_type = symbol(PREFIX + "loaded_session", "LoadedRuntimeRecordV1")
    values = loaded_record_values()
    del values["producer_abi_version"]
    with pytest.raises((ValueError, TypeError)):
        record_type(**values)
    with pytest.raises((ValueError, TypeError)):
        record_type(**loaded_record_values(), unsupported_extension="inert")


def test_version_one_incomplete_record_is_healthy_positive():
    record_type = symbol(PREFIX + "loaded_session", "LoadedRuntimeRecordV1")
    record = record_type(**loaded_record_values())
    assert type(record.producer_abi_version) is int
    assert record.producer_abi_version == 1
    assert record.execution_receipt is None
    assert record.observed_embedding_dimension is None
    assert record.state == "not_loaded"
    with pytest.raises(TypeError):
        record.sessions["fixture_canary"] = None


def config_for(module, root, **changes):
    """Coordinator-frozen cache-key inputs, with no inferred extra fields."""
    cls = symbol(PREFIX + "loaded_session", "FrozenFaceRuntimeConfig")
    known = dict(profile="auraface", models_dir=root, embedder_models_dir=root,
                 score_threshold=0.9, nms_threshold=0.3, top_k=5000,
                 embedding_dimension=512, pgvector_dimension=512)
    known.update(changes)
    assert {field.name for field in fields(cls)} == set(known), \
        "CAUSAL_RED: FrozenFaceRuntimeConfig must freeze exactly cache-key inputs"
    return cls(**known)


def serving_fixture(tmp_path, monkeypatch, *, no_face=False, raw_output=None,
                    second_constructor_fails=False, require_producer=True, shared=False,
                    manifest_normalized=False):
    module = importlib.import_module(ADAPTER)
    # This is a named proposed interface failure, not a fixture import error.
    if require_producer:
        symbol(ADAPTER, "observe_api_face_adapters")
        if not hasattr(module.FacePipelineFaceDetector, "loaded_runtime_record"):
            pytest.fail("CAUSAL_RED: proposed FacePipelineFaceDetector.loaded_runtime_record absent", pytrace=False)
    provenance, _, _, _ = artifact_fixture(tmp_path, monkeypatch, "yunet")
    _, aura_entry, _, _ = artifact_fixture(tmp_path, monkeypatch, "auraface")
    if manifest_normalized:
        monkeypatch.setitem(provenance.MODEL_MANIFEST, "auraface", replace(
            aura_entry, preprocessing=replace(aura_entry.preprocessing, output_l2_normalized=True)))
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    detector_session = ServingSession()
    detector_session.get_outputs = lambda: [SimpleNamespace(name=name, shape=[1], type="tensor(float)")
                                            for name in adapters._YUNET_OUTPUT_NAMES]
    detector_session.run = lambda names, feeds: record_detector_run(detector_session, feeds, adapters)
    embedder_session = ServingSession(raw_output)
    calls = []

    def constructor(source, sess_options=None, providers=None, **kwargs):
        calls.append(source)
        if len(calls) == 2 and second_constructor_fails:
            raise ValueError("synthetic_second_constructor_failure")
        if isinstance(source, bytes):
            digest = sha(source)
            names = [name for name in ("yunet", "auraface")
                     if provenance.MODEL_MANIFEST[name].sha256 == digest]
            assert len(names) == 1, "unknown synthetic model buffer"
            name = names[0]
        else:
            name = Path(source).stem
        assert name in {"yunet", "auraface"}, "unknown synthetic model path"
        session = detector_session if name == "yunet" else embedder_session
        session.options = sess_options
        session.providers = providers or []
        return session

    monkeypatch.setattr(adapters.ort, "InferenceSession", constructor)
    common = importlib.import_module(PREFIX + "_common")
    face = common.RawDetection(bbox=np.array([10., 10., 90., 90.], dtype=np.float32),
                               score=0.99, landmarks=landmarks())
    monkeypatch.setattr(adapters, "decode_yunet_outputs", lambda *args, **kwargs: [] if no_face else [face])
    monkeypatch.setenv("PGVECTOR_DIM", "512")
    module.get_database_settings.cache_clear()
    # Keep dimension guards real without consulting credential-backed providers.
    monkeypatch.setattr(module, "get_database_settings", lambda: SimpleNamespace(pgvector_dimension=512))
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(
        identity_detection=SimpleNamespace(embedding_dimension=512)))

    space = importlib.import_module(PREFIX + "model_space").ModelSpace.AURAFACE
    loader = module.get_shared_face_pipeline_runtime if shared else module._load_face_pipeline_runtime
    selection = {"profile": space} if shared else {"space": space}
    runtime = loader(models_dir=tmp_path, embedder_models_dir=tmp_path,
                score_threshold=0.9, nms_threshold=0.3, top_k=5000, **selection)
    adapter = module.FacePipelineFaceDetector(runtime, timeout=1, executor=SimpleNamespace(),
                    submit_semaphore=SimpleNamespace(), breaker=SimpleNamespace())
    image = asymmetric_crop()
    monkeypatch.setattr(module, "decode_image_bytes", lambda data: image.copy())
    monkeypatch.setattr(module.InsightFaceFaceDetector, "_compute_phash", lambda data: "fixture-phash")
    config = config_for(module, tmp_path) if require_producer else None
    return module, adapter, config, detector_session, embedder_session, calls


def record_detector_run(session, feeds, adapters):
    session.feeds.append({key: value.copy() for key, value in feeds.items()})
    return [np.zeros((1,), dtype=np.float32) for _ in adapters._YUNET_OUTPUT_NAMES]


def observe(adapter, config, active=None):
    return adapter.loaded_runtime_record(expected_config=config, active_generation_id=active, captured_at=NOW)


def test_health_singleton_new_generation_does_not_relabel_retained_adapter(tmp_path, monkeypatch):
    module, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    before = observe(adapter, config)
    retained = adapter._runtime
    monkeypatch.setattr(module, "_SHARED", (("health-only",), SimpleNamespace(runtime_generation_id="health-new")))
    after = observe(adapter, config)
    assert adapter._runtime is retained
    assert after.runtime_generation_id == before.runtime_generation_id
    assert after.sessions == before.sessions
    assert after.state == before.state == "loaded_unexercised"
    assert after.runtime_generation_id != "health-new"


def test_active_serving_generation_mismatch_refuses_but_preserves_loaded_hashes(tmp_path, monkeypatch):
    _, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    healthy = observe(adapter, config)
    same = observe(adapter, config, healthy.runtime_generation_id)
    assert same.state == "loaded_unexercised"
    wrong = observe(adapter, config, "different-role-local-serving-generation")
    assert wrong.state == "drifted"
    assert wrong.runtime_generation_id == healthy.runtime_generation_id
    assert wrong.sessions == healthy.sessions


@pytest.mark.parametrize("artifact_name", ["yunet.onnx", "auraface.onnx", "LICENSE.yunet", "LICENSE.auraface"])
@pytest.mark.parametrize("damage", ["replace", "delete"])
def test_retained_artifact_drift_refuses_observation_and_inference(tmp_path, monkeypatch, artifact_name, damage):
    _, adapter, config, detector, embedder, _ = serving_fixture(tmp_path, monkeypatch)
    healthy = observe(adapter, config)
    path = tmp_path / artifact_name
    if damage == "delete":
        path.unlink()
    else:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(b"synthetic changed identity")
        replacement.replace(path)
    drift = observe(adapter, config)
    assert drift.state == "drifted"
    assert drift.sessions == healthy.sessions
    with pytest.raises(Exception):
        adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    assert detector.feeds == embedder.feeds == []


@pytest.mark.parametrize("field, value", [("score_threshold", 0.7), ("nms_threshold", 0.2),
                                           ("top_k", 4), ("embedding_dimension", 128),
                                           ("pgvector_dimension", 128), ("profile", "face_pipeline"),
                                           ("embedder_models_dir", Path("different-synthetic-directory"))])
def test_effective_config_drift_refuses_without_rewriting_loaded_receipts(tmp_path, monkeypatch, field, value):
    module, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    healthy = observe(adapter, config)
    if field not in {f.name for f in fields(config)}:
        pytest.fail(f"FIXTURE_ABI_GAP: c76 config field not frozen: {field}", pytrace=False)
    changed = replace(config, **{field: value})
    drift = observe(adapter, changed)
    assert drift.state == "drifted"
    assert drift.sessions == healthy.sessions
    assert drift.runtime_generation_id == healthy.runtime_generation_id


def test_observation_never_constructs_runs_or_rehashes_disk(tmp_path, monkeypatch):
    module, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    before = observe(adapter, config)

    def forbidden(*args, **kwargs):
        pytest.fail("CAUSAL_RED: observation performed load/run/disk hash", pytrace=False)

    monkeypatch.setattr(module, "get_shared_face_pipeline_runtime", forbidden)
    monkeypatch.setattr(module, "_load_face_pipeline_runtime", forbidden)
    monkeypatch.setattr(importlib.import_module(PREFIX + "provenance"), "_file_sha256", forbidden)
    forbid_artifact_reads(monkeypatch, tmp_path, forbidden)
    monkeypatch.setattr(adapter._runtime.detector._session, "run", forbidden)
    monkeypatch.setattr(adapter._runtime.embedder._session, "run", forbidden)
    after = observe(adapter, config)
    assert after.sessions == before.sessions
    assert after.execution_receipt is None
    assert after.state == "loaded_unexercised"


def test_stat_collision_cannot_relabel_current_disk_bytes_as_loaded_evidence(tmp_path, monkeypatch):
    module, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    before = observe(adapter, config)
    old_stamps = {str(path): module._artifact_stat_identity(path) for path in tmp_path.iterdir()}
    path = tmp_path / "auraface.onnx"
    data = path.read_bytes()
    changed = bytes([data[0] ^ 1]) + data[1:]
    path.write_bytes(changed)
    original = module._artifact_stat_identity
    monkeypatch.setattr(module, "_artifact_stat_identity",
                        lambda path: old_stamps.get(str(path), None) or original(path))
    after = observe(adapter, config)
    assert after.sessions == before.sessions
    assert after.sessions["auraface"].observed_weight_sha256 == sha(data)
    assert after.sessions["auraface"].observed_weight_sha256 != sha(changed)
    assert after.state != "attested"
    assert after.execution_receipt is None or after.execution_receipt.completion in {"partial", "failed", "executed_unreferenced"}


def test_unknown_current_artifact_identity_remains_incomplete(tmp_path, monkeypatch):
    module, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    before = observe(adapter, config)
    paths = artifact_paths(tmp_path)
    original_stat = os.stat

    def unavailable(path, *args, **kwargs):
        if is_artifact(path, paths):
            raise PermissionError("synthetic unknown artifact identity")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", unavailable)
    after = observe(adapter, config)
    assert after.sessions == before.sessions
    assert after.state != "attested"
    assert after.state == "drifted"
    assert after.reason_code is not None and after.reason_code != before.reason_code
    assert after.execution_receipt is None or after.execution_receipt.completion in {"partial", "failed", "executed_unreferenced"}


@pytest.mark.parametrize("outcome", ["construction_only", "no_face", "empty_crops", "zero", "nonfinite", "wrong_width"])
def test_incomplete_execution_never_promotes_complete_receipt(tmp_path, monkeypatch, outcome):
    output = {"zero": np.zeros((1, 512), np.float32),
              "nonfinite": np.full((1, 512), np.nan, np.float32),
              "wrong_width": np.ones((1, 511), np.float32)}.get(outcome)
    _, adapter, config, detector, embedder, _ = serving_fixture(
        tmp_path, monkeypatch, no_face=outcome == "no_face", raw_output=output)
    if outcome == "empty_crops":
        adapter._runtime.embedder.embed([])
    elif outcome not in {"construction_only"}:
        try:
            adapter._detect_sync(b"synthetic encoded image", "fixture-media")
        except importlib.import_module(PREFIX + "_common").FacePipelineInputError:
            assert outcome == "wrong_width"
    record = observe(adapter, config)
    assert record.state != "attested"
    assert record.execution_receipt is None or record.execution_receipt.completion in {"partial", "failed", "executed_unreferenced"}
    if outcome in {"construction_only", "empty_crops", "no_face"}:
        assert record.state == "loaded_unexercised"
        assert embedder.feeds == []


def test_executed_receipt_hashes_arrays_actually_passed_to_each_run(tmp_path, monkeypatch):
    _, adapter, config, detector, embedder, _ = serving_fixture(tmp_path, monkeypatch)
    actual_alignments = []
    align = adapter._runtime.aligner.align

    def capture_alignment(image, points):
        result = align(image, points)
        actual_alignments.append((points.copy(), result))
        return result

    monkeypatch.setattr(adapter._runtime.aligner, "align", capture_alignment)
    results = adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    record = observe(adapter, config)
    receipt = record.execution_receipt
    assert receipt is not None, "CAUSAL_RED: actual inference must produce execution lineage"
    assert receipt.runtime_generation_id == record.runtime_generation_id
    assert receipt.detector_session_id == record.sessions["yunet"].session_id
    assert receipt.embedder_session_id == record.sessions["auraface"].session_id
    for observed, actual in [(receipt.detector_input, detector.feeds[0]["input"]),
                              (receipt.embedder_input, embedder.feeds[0]["input"])]:
        assert observed["sha256"] == sha(actual.tobytes())
        assert tuple(observed["shape"]) == actual.shape
        assert observed["dtype"] == str(actual.dtype)
        assert observed["contiguous"] == actual.flags.c_contiguous
    assert receipt.raw_output["norm"] == pytest.approx(5)
    assert receipt.normalized_output["norm"] == pytest.approx(1)
    assert receipt.raw_output["dimension"] == receipt.normalized_output["dimension"] == 512
    points, aligned = actual_alignments[0]
    assert receipt.alignment["landmarks_sha256"] == sha(points.tobytes())
    assert receipt.alignment["template_sha256"] == sha(adapter._runtime.aligner.dst_landmarks.tobytes())
    assert receipt.alignment["affine_sha256"] == sha(aligned.affine.tobytes())
    assert receipt.alignment["crop_sha256"] == sha(aligned.crop.tobytes())
    assert receipt.raw_output["sha256"] == sha(embedder.output.reshape(-1).tobytes())
    assert receipt.normalized_output["sha256"] == sha(results[0].embedding.tobytes())
    # Ordinary synthetic execution has no independently attested fixture/reference.
    assert record.state != "attested"
    assert receipt.completion in {"partial", "failed", "executed_unreferenced"}
    for values in (receipt.detector_input, receipt.embedder_input, receipt.alignment,
                   receipt.raw_output, receipt.normalized_output):
        with pytest.raises(TypeError):
            values["fixture_canary"] = None


def test_receipt_tensor_capture_precedes_session_run_side_effects(tmp_path, monkeypatch):
    _, adapter, config, _, embedder, _ = serving_fixture(tmp_path, monkeypatch)
    run = embedder.run

    def run_then_overwrite_input(names, feeds):
        output = run(names, feeds)
        for tensor in feeds.values():
            tensor.fill(np.float32(99))
        return output

    monkeypatch.setattr(embedder, "run", run_then_overwrite_input)
    adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    receipt = observe(adapter, config).execution_receipt
    assert receipt is not None
    actual_before_run = embedder.feeds[0]["input"]
    assert receipt.embedder_input["sha256"] == sha(actual_before_run.tobytes())
    assert receipt.embedder_input["sha256"] != sha(np.full_like(actual_before_run, 99).tobytes())


def test_api_registry_observes_serving_adapter_without_loading_health_runtime(tmp_path, monkeypatch):
    module, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch)
    adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    retained = observe(adapter, config)
    monkeypatch.setattr(module, "_SHARED", (("health",), SimpleNamespace(runtime_generation_id="health-new")))

    def forbidden(*args, **kwargs):
        pytest.fail("CAUSAL_RED: API registry constructed/probed runtime", pytrace=False)

    monkeypatch.setattr(module, "get_shared_face_pipeline_runtime", forbidden)
    monkeypatch.setattr(module, "_load_face_pipeline_runtime", forbidden)
    observations = module.observe_api_face_adapters(expected_config=config, captured_at=NOW)
    assert isinstance(observations, tuple)
    matches = [observation for observation in observations
               if observation.runtime_record.runtime_generation_id == retained.runtime_generation_id]
    assert len(matches) == 1
    assert matches[0].adapter_instance_id
    assert matches[0].usage_origin != "health_probe_only"
    assert all(observation.runtime_record.runtime_generation_id != "health-new" for observation in observations)


def test_missing_graph_analysis_cannot_be_backfilled_from_manifest_or_raw_norm(tmp_path, monkeypatch):
    _, adapter, config, _, _, _ = serving_fixture(tmp_path, monkeypatch, manifest_normalized=True)
    adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    record = observe(adapter, config)
    for session in record.sessions.values():
        analysis = session.graph_analysis
        if analysis is not None:
            assert analysis["digest"] == session.observed_weight_sha256
            assert analysis.get("output_l2_normalized") is not True
    assert record.state != "attested"
    assert record.execution_receipt is None or record.execution_receipt.completion in {
        "partial", "failed", "executed_unreferenced"}


def test_second_constructor_failure_publishes_no_successful_pair(tmp_path, monkeypatch):
    module = importlib.import_module(ADAPTER)
    monkeypatch.setattr(module, "_SHARED", None)
    with pytest.raises(module.FacePipelineRuntimeUnavailableError, match="synthetic_second_constructor_failure"):
        serving_fixture(tmp_path, monkeypatch, second_constructor_fails=True,
                        require_producer=False, shared=True)
    assert module._SHARED is None or not isinstance(module._SHARED[1], module.FacePipelineRuntime)
    observer = symbol(ADAPTER, "observe_api_face_adapters")
    observations = observer(expected_config=config_for(module, tmp_path), captured_at=NOW)
    assert not observations, "CAUSAL_RED: failed pair published an adapter/session record"


def test_control_retained_reference_is_not_replaced_by_health_singleton(tmp_path, monkeypatch):
    module, adapter, _, detector, embedder, _ = serving_fixture(
        tmp_path, monkeypatch, require_producer=False)
    retained = adapter._runtime
    monkeypatch.setattr(module, "_SHARED", (("health",), SimpleNamespace(runtime_generation_id="health-new")))
    result = adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    assert adapter._runtime is retained
    assert len(result) == len(detector.feeds) == len(embedder.feeds) == 1


@pytest.mark.parametrize("outcome", ["face", "no_face", "zero", "nonfinite", "wrong_width"])
def test_control_serving_fixture_runs_actual_adapter_without_native_load(tmp_path, monkeypatch, outcome):
    output = {"zero": np.zeros((1, 512), np.float32),
              "nonfinite": np.full((1, 512), np.nan, np.float32),
              "wrong_width": np.ones((1, 511), np.float32)}.get(outcome)
    _, adapter, _, detector, embedder, calls = serving_fixture(
        tmp_path, monkeypatch, no_face=outcome == "no_face", raw_output=output,
        require_producer=False)
    assert len(calls) == 2
    if outcome == "wrong_width":
        with pytest.raises(importlib.import_module(PREFIX + "_common").FacePipelineInputError):
            adapter._detect_sync(b"synthetic encoded image", "fixture-media")
    else:
        result = adapter._detect_sync(b"synthetic encoded image", "fixture-media")
        assert len(result) == (1 if outcome == "face" else 0)
    assert len(detector.feeds) == 1
    assert len(embedder.feeds) == (0 if outcome == "no_face" else 1)


def test_control_second_constructor_failure_is_injected_without_native_load(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="synthetic_second_constructor_failure"):
        serving_fixture(tmp_path, monkeypatch, second_constructor_fails=True, require_producer=False)

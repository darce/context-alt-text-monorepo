"""c77 F04/F05: real builders/aligner/embed_batch, recording session fakes.

Asymmetric independent pixel/landmark oracles catch channel/template mutation.
No synthetic graph result is promoted to live universal graph evidence.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
"""
from __future__ import annotations

import importlib
import inspect
from dataclasses import fields, replace

import numpy as np
import pytest

from recognition.tests.unit.test_loaded_face_session_producer import (
    PREFIX, acquire, artifact_fixture, install_constructor, sha, symbol,
)


def asymmetric_crop():
    y, x = np.indices((112, 112))
    return np.stack(((x + 3 * y) % 251, (2 * x + y + 17) % 253,
                     (5 * x + 7 * y + 41) % 255), axis=-1).astype(np.uint8)


def independent_aura_tensor(crop):
    # Explicit channels: independent of production's slice/transpose builder.
    result = np.empty((1, 3, 112, 112), dtype=np.float32)
    for output_channel, source_channel in enumerate((2, 1, 0)):
        result[0, output_channel] = (crop[:, :, source_channel].astype(np.float32)
                                      - np.float32(127.5)) * np.float32(1 / 127.5)
    return result


@pytest.fixture(autouse=True)
def native_ort_tripwire(monkeypatch):
    """Catch native aliases as well as the public recording-constructor seam."""
    native = importlib.import_module("onnxruntime.capi._pybind_state")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        pytest.fail("FIXTURE_ERROR: native ORT construction attempted", pytrace=False)

    monkeypatch.setattr(native, "InferenceSession", forbidden)
    yield calls
    assert len(calls) == 0


def executing_embedder(tmp_path, monkeypatch, output=None):
    artifact_fixture(tmp_path, monkeypatch)
    adapters, _, _ = install_constructor(monkeypatch, output)
    # Exercise the preserved legacy constructor, verification and metadata path.
    return adapters.OrtSFaceEmbedder(model_name="auraface", models_dir=tmp_path)


def test_control_actual_session_feed_matches_independent_aura_tensor(tmp_path, monkeypatch):
    crop = asymmetric_crop()
    embedder = executing_embedder(tmp_path, monkeypatch)
    result = embedder.embed([crop])
    tensor = embedder._session.feeds[0]["input"]
    np.testing.assert_array_equal(tensor, independent_aura_tensor(crop))
    assert tensor.dtype == np.float32 and tensor.flags.c_contiguous
    assert tensor.shape == (1, 3, 112, 112)
    assert result.norms.tolist() == [5.0]
    np.testing.assert_allclose(result.vectors[0, :2], [0.6, 0.8], atol=1e-7)
    np.testing.assert_allclose(np.linalg.norm(result.vectors[0]), 1, atol=1e-7)


@pytest.mark.parametrize("mutation", ["channel", "mean", "scale"])
def test_control_independent_tensor_oracle_detects_each_mutation(tmp_path, monkeypatch, mutation):
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    crop = asymmetric_crop()
    kwargs = dict(channel_order="RGB", input_mean=127.5, input_scale=1 / 127.5)
    kwargs.update({"channel": dict(channel_order="BGR"), "mean": dict(input_mean=0),
                   "scale": dict(input_scale=1)}[mutation])
    mutated = adapters._bgr_to_declared_blob(crop, **kwargs)
    assert not np.array_equal(mutated, independent_aura_tensor(crop))
    # Prove the exact healthy run assertion goes red under an executing-builder
    # mutation. All changes are in-process and restored by monkeypatch.
    test_control_actual_session_feed_matches_independent_aura_tensor(tmp_path, monkeypatch)
    monkeypatch.setattr(adapters, "_blob_builder_for_model", lambda name, **unused:
                        lambda crop: adapters._bgr_to_declared_blob(crop, **kwargs))
    with pytest.raises(AssertionError):
        test_control_actual_session_feed_matches_independent_aura_tensor(tmp_path, monkeypatch)


def test_control_normalization_mutation_turns_healthy_run_assertion_red(tmp_path, monkeypatch):
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    common = importlib.import_module(PREFIX + "_common")
    test_control_actual_session_feed_matches_independent_aura_tensor(tmp_path, monkeypatch)
    original = adapters.embed_batch

    def omit_normalization(*args, **kwargs):
        result = original(*args, **kwargs)
        return common.EmbedBatchResult(vectors=result.vectors * result.norms[:, None], norms=result.norms)

    monkeypatch.setattr(adapters, "embed_batch", omit_normalization)
    with pytest.raises(AssertionError):
        test_control_actual_session_feed_matches_independent_aura_tensor(tmp_path, monkeypatch)


@pytest.mark.parametrize("failure", ["empty", "zero", "nan", "infinity", "wrong_width"])
def test_control_normalization_gate_and_empty_batch(tmp_path, monkeypatch, failure):
    common = importlib.import_module(PREFIX + "_common")
    outputs = {"zero": np.zeros((1, 512), np.float32),
               "nan": np.full((1, 512), np.nan, np.float32),
               "infinity": np.full((1, 512), np.inf, np.float32),
               "wrong_width": np.ones((1, 511), np.float32)}
    embedder = executing_embedder(tmp_path, monkeypatch, outputs.get(failure))
    if failure == "empty":
        result = embedder.embed([])
        assert result.vectors.shape == (0, 512)
        assert result.norms.shape == (0,)
        assert embedder._session.feeds == []
    else:
        error = common.FacePipelineInputError if failure == "wrong_width" else common.ZeroNormEmbeddingError
        with pytest.raises(error):
            embedder.embed([asymmetric_crop()])
        assert len(embedder._session.feeds) == 1


def test_candidate_builder_reads_explicit_frozen_manifest_entry(monkeypatch):
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    provenance = importlib.import_module(PREFIX + "provenance")
    frozen = provenance.MODEL_MANIFEST["auraface"]
    changed = replace(frozen, preprocessing=replace(frozen.preprocessing, channel_order="BGR", input_mean=0))
    # Change the ambient entry BEFORE construction: ignoring the snapshot must fail.
    monkeypatch.setitem(provenance.MODEL_MANIFEST, "auraface", changed)
    try:
        builder = adapters._blob_builder_for_model("auraface", entry=frozen)
    except TypeError as exc:
        pytest.fail(f"CAUSAL_RED: ABI-04 frozen entry unsupported: {type(exc).__name__}", pytrace=False)
    np.testing.assert_array_equal(builder(asymmetric_crop()), independent_aura_tensor(asymmetric_crop()))


def test_control_sface_recipe_and_alignment_dtype_preserved():
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    aligner = importlib.import_module(PREFIX + "aligner")
    crop = asymmetric_crop()
    tensor = adapters._blob_builder_for_model("sface")(crop)
    for output_channel, source_channel in enumerate((2, 1, 0)):
        np.testing.assert_array_equal(tensor[0, output_channel], crop[:, :, source_channel].astype(np.float32))
    assert aligner.SFACE_CANONICAL_LANDMARKS_112.dtype == np.float64
    assert aligner.ARCFACE_CANONICAL_LANDMARKS_112.dtype == np.float32


def landmarks():
    # Independent pinned ArcFace coordinates; no import of production template.
    return np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                     [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float32)


def test_control_arcface_identity_fixture():
    aligner = importlib.import_module(PREFIX + "aligner")
    affine = aligner.arcface_similarity_transform_matrix(landmarks())
    np.testing.assert_allclose(affine, [[1, 0, 0], [0, 1, 0]], atol=1e-5)


def test_arcface_estimator_reads_supplied_frozen_destination(monkeypatch):
    aligner = importlib.import_module(PREFIX + "aligner")
    frozen = landmarks()
    frozen.setflags(write=False)
    assert "dst_landmarks" in inspect.signature(aligner.arcface_similarity_transform_matrix).parameters, \
        "CAUSAL_RED: ABI-04 executing destination keyword absent"
    monkeypatch.setattr(aligner, "ARCFACE_CANONICAL_LANDMARKS_112", landmarks() + np.float32(9))
    affine = aligner.arcface_similarity_transform_matrix(landmarks(), dst_landmarks=frozen)
    np.testing.assert_allclose(affine, [[1, 0, 0], [0, 1, 0]], atol=1e-5)


def test_retained_aligner_does_not_execute_mutable_global_template(monkeypatch):
    module = importlib.import_module(PREFIX + "aligner")
    space = importlib.import_module(PREFIX + "model_space").ModelSpace.AURAFACE
    aligner = module.FivePointAligner(space=space)
    crop = asymmetric_crop()
    before = aligner.align(crop, landmarks())
    # Leave the recorded destination correct; change only what current execution reads.
    monkeypatch.setattr(module, "ARCFACE_CANONICAL_LANDMARKS_112", landmarks() + np.float32(9))
    after = aligner.align(crop, landmarks())
    np.testing.assert_array_equal(after.affine, before.affine,
                                  err_msg="CAUSAL_RED: executing estimator read mutable global")
    np.testing.assert_array_equal(after.crop, before.crop)


def test_frozen_alignment_template_is_not_a_mutable_global_alias():
    module = importlib.import_module(PREFIX + "aligner")
    space = importlib.import_module(PREFIX + "model_space").ModelSpace.AURAFACE
    aligner = module.FivePointAligner(space=space)
    assert not np.shares_memory(aligner.dst_landmarks, module.ARCFACE_CANONICAL_LANDMARKS_112), \
        "CAUSAL_RED: candidate executing destination must own an immutable copy"
    assert not aligner.dst_landmarks.flags.writeable
    assert aligner.dst_landmarks.dtype == np.float32


@pytest.mark.parametrize("receipt_name, required", [
    ("SessionReceiptV1", {"session_id", "runtime_generation_id", "observed_weight_sha256",
                           "observed_license_sha256", "graph_analysis", "actual_providers",
                           "actual_input_metadata", "actual_output_metadata", "actual_session_options"}),
    ("ExecutionReceiptV1", {"execution_id", "runtime_generation_id", "detector_session_id",
                             "embedder_session_id", "input_lineage", "detector_input", "alignment",
                             "embedder_input", "raw_output", "normalized_output",
                             "graph_analysis_sha256", "completion"}),
])
def test_receipt_fields_distinguish_construction_execution_and_graph(receipt_name, required):
    receipt = symbol(PREFIX + "loaded_session", receipt_name)
    assert required <= {field.name for field in fields(receipt)}


def test_verified_embedder_executes_frozen_recipe_at_run_boundary(tmp_path, monkeypatch):
    provenance, entry, _, _ = artifact_fixture(tmp_path, monkeypatch)
    # Deliberately false graph declaration: the fixture emits raw norm 5.
    # It cannot replace observed execution or digest-bound graph evidence (C6).
    entry = replace(entry, preprocessing=replace(entry.preprocessing, output_l2_normalized=True))
    monkeypatch.setitem(provenance.MODEL_MANIFEST, "auraface", entry)
    artifact = acquire(provenance, entry, tmp_path)
    adapters, calls, session = install_constructor(monkeypatch)
    monkeypatch.setitem(provenance.MODEL_MANIFEST, "auraface", replace(
        entry, preprocessing=replace(entry.preprocessing, channel_order="BGR", input_mean=0)))
    # A changed manifest may be refused explicitly, or the acquired recipe used.
    try:
        embedder = adapters.OrtSFaceEmbedder(model_name="auraface", models_dir=tmp_path, verified_artifact=artifact)
    except provenance.ModelIntegrityError:
        assert calls == []
        return
    crop = asymmetric_crop()
    result = embedder.embed([crop])
    assert result.norms.tolist() == [5.0]
    np.testing.assert_allclose(np.linalg.norm(result.vectors[0]), 1, atol=1e-7)
    assert calls[0][0] is artifact.model_bytes
    np.testing.assert_array_equal(session.feeds[0]["input"], independent_aura_tensor(crop))
    assert sha(session.feeds[0]["input"].tobytes()) == sha(independent_aura_tensor(crop).tobytes())

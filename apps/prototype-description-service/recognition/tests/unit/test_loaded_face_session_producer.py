"""c77 ABI-01/02: same-buffer producer tests, never native ONNX loads.

Missing c76 proposed symbols fail with CAUSAL_RED, never skip/xfail. Other
import errors remain fixture errors. Run with --noconftest: the service's
unrelated DB/application fixture tree is deliberately outside this unit lane.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
TEST-15: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#test-15
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import time
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

PREFIX = "recognition.infrastructure.face_pipeline."


def symbol(module, name):
    """Only the specifically missing proposed interface is an intended RED."""
    try:
        loaded = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name == module:
            pytest.fail(f"CAUSAL_RED: proposed module absent: {module}", pytrace=False)
        raise
    if not hasattr(loaded, name):
        pytest.fail(f"CAUSAL_RED: proposed symbol absent: {module}.{name}", pytrace=False)
    return getattr(loaded, name)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tiny_graph(label="standalone"):
    """Self-contained ONNX Constant graph; protobuf encoded without ONNX SDK.

    512 float32 values, no external-data tensors. The recording constructor
    never parses/loads this model; this is synthetic graph data, not live proof.
    """
    def varint(n):
        out = bytearray()
        while n >= 128:
            out.append((n & 127) | 128)
            n >>= 7
        return bytes(out) + bytes([n])

    def integer(field, value):
        return varint(field << 3) + varint(value)

    def blob(field, value):
        return varint((field << 3) | 2) + varint(len(value)) + value

    # TensorProto dims=[1,512], FLOAT; named initializer exposed as output.
    raw = np.zeros((1, 512), dtype='<f4')
    raw[0, :2] = [3, 4]
    tensor = integer(1, 1) + integer(1, 512) + integer(2, 1)
    tensor += blob(8, b'output') + blob(9, raw.tobytes())
    shape = blob(1, integer(1, 1)) + blob(1, integer(1, 512))
    tensor_type = integer(1, 1) + blob(2, shape)
    output = blob(1, b'output') + blob(2, blob(1, tensor_type))
    graph = blob(2, ("c77-synthetic-" + label).encode("ascii")) + blob(5, tensor) + blob(12, output)
    return integer(1, 8) + blob(2, b'c77-unit-fixture') + blob(7, graph) + blob(8, integer(2, 13))


def artifact_fixture(tmp_path, monkeypatch, name="auraface"):
    provenance = importlib.import_module(PREFIX + "provenance")
    model = tiny_graph(name)
    license_bytes = ("c77 synthetic fixture license " + name + "\n").encode("ascii")
    entry = replace(provenance.MODEL_MANIFEST[name], file_name=f"{name}.onnx",
                    license_file=f"LICENSE.{name}", sha256=sha(model),
                    size_bytes=len(model), license_sha256=sha(license_bytes))
    monkeypatch.setitem(provenance.MODEL_MANIFEST, name, entry)
    (tmp_path / entry.file_name).write_bytes(model)
    (tmp_path / entry.license_file).write_bytes(license_bytes)
    return provenance, entry, model, license_bytes


def acquire(provenance, entry, root, name="auraface", **overrides):
    fn = symbol(PREFIX + "provenance", "acquire_verified_model_bytes")
    args = dict(models_dir=root, expected=entry, max_model_bytes=4096,
                max_license_bytes=256, deadline_monotonic=time.monotonic() + 5)
    args.update(overrides)
    return fn(name, **args)


class RecordingSession:
    """Copies feeds at the run boundary; never native ORT or graph analysis."""
    def __init__(self, output=None):
        self.feeds = []
        self.output = np.zeros((1, 512), dtype=np.float32) if output is None else output
        if output is None:
            self.output[0, :2] = [3, 4]

    def get_inputs(self):
        return [SimpleNamespace(name="input", shape=[1, 3, 112, 112], type="tensor(float)")]

    def get_outputs(self):
        return [SimpleNamespace(name="output", shape=[1, 512], type="tensor(float)")]

    def get_providers(self):
        return ["CPUExecutionProvider"]

    def run(self, names, feeds):
        self.feeds.append({key: value.copy() for key, value in feeds.items()})
        return [self.output.copy()]


def install_constructor(monkeypatch, output=None):
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    calls = []
    session = RecordingSession(output)

    def constructor(source, *, sess_options, providers):
        calls.append((source, sess_options, providers))
        return session

    monkeypatch.setattr(adapters.ort, "InferenceSession", constructor)
    return adapters, calls, session


def test_control_legacy_verified_loader_preserves_path_abi(tmp_path, monkeypatch):
    provenance, entry, model, _ = artifact_fixture(tmp_path, monkeypatch)
    result = provenance.load_verified_model("auraface", models_dir=tmp_path)
    assert isinstance(result, Path)
    assert result == tmp_path / entry.file_name
    assert sha(result.read_bytes()) == sha(model)
    assert inspect.signature(provenance.load_verified_model).parameters["models_dir"].default is None


@pytest.mark.parametrize("factor", ["model", "license"])
def test_control_legacy_loader_rejects_tampering(tmp_path, monkeypatch, factor):
    provenance, entry, _, _ = artifact_fixture(tmp_path, monkeypatch)
    name = entry.file_name if factor == "model" else entry.license_file
    path = tmp_path / name
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
    with pytest.raises(provenance.ModelIntegrityError):
        provenance.load_verified_model("auraface", models_dir=tmp_path)


def test_control_recording_constructor_legacy_path_and_numeric_options(monkeypatch):
    adapters, calls, session = install_constructor(monkeypatch)
    assert adapters._ort_session(Path("inert.onnx")) is session
    source, options, providers = calls[0]
    assert source == "inert.onnx"
    assert providers == ["CPUExecutionProvider"]
    assert options.inter_op_num_threads == options.intra_op_num_threads == 1
    assert options.execution_mode == adapters.ort.ExecutionMode.ORT_SEQUENTIAL
    assert options.graph_optimization_level == adapters.ort.GraphOptimizationLevel.ORT_ENABLE_ALL


def test_bytes_dispatch_passes_identical_immutable_object(monkeypatch):
    adapters, calls, _ = install_constructor(monkeypatch)
    model = tiny_graph()
    adapters._ort_session(model)
    assert calls[0][0] is model, "CAUSAL_RED: _ort_session must pass bytes unchanged, not str(bytes)"


def test_acquisition_hashes_same_buffer_consumed_by_constructor(tmp_path, monkeypatch):
    provenance, entry, model, license_bytes = artifact_fixture(tmp_path, monkeypatch)
    # Observe the actual argument to hashing during acquisition, before any
    # oracle hash calls. Equality alone would miss hashing a different buffer.
    real_sha256 = hashlib.sha256
    hashed_buffers = []

    class HashSpy:
        def __init__(self, data=b"", **kwargs):
            hashed_buffers.append(data)
            self.inner = real_sha256(data, **kwargs)

        def update(self, data):
            hashed_buffers.append(data)
            self.inner.update(data)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    with monkeypatch.context() as hashing_patch:
        hashing_patch.setattr(provenance.hashlib, "sha256", HashSpy)
        artifact = acquire(provenance, entry, tmp_path)
    assert any(buffer is artifact.model_bytes for buffer in hashed_buffers), \
        "CAUSAL_RED: hash the acquired immutable buffer itself, not a separate disk read/copy"
    verified_type = symbol(PREFIX + "loaded_session", "VerifiedModelBytes")
    assert isinstance(artifact, verified_type)
    assert type(artifact.model_bytes) is bytes
    assert artifact.model_bytes == model
    assert artifact.model_sha256 == sha(artifact.model_bytes)
    assert artifact.model_size_bytes == len(model)
    assert artifact.license_sha256 == sha(license_bytes)
    assert artifact.license_size_bytes == len(license_bytes)
    assert artifact.manifest_snapshot == entry
    assert artifact.manifest_expectation_sha256
    assert artifact.observed_model_file_identity is not None
    assert artifact.observed_license_file_identity is not None
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)):
        artifact.model_bytes = b"replacement"
    adapters, calls, _ = install_constructor(monkeypatch)
    adapters._ort_session(artifact.model_bytes)
    assert calls[0][0] is artifact.model_bytes
    assert sha(calls[0][0]) == artifact.model_sha256


@pytest.mark.parametrize("after_verification", ["replace_model", "delete_model", "replace_license", "delete_license"])
def test_verified_artifact_never_reopens_or_rehashes_disk(tmp_path, monkeypatch, after_verification):
    provenance, entry, model, _ = artifact_fixture(tmp_path, monkeypatch)
    artifact = acquire(provenance, entry, tmp_path)
    path = tmp_path / (entry.license_file if "license" in after_verification else entry.file_name)
    if after_verification.startswith("delete"):
        path.unlink()
    else:
        path.write_bytes(b"changed after verification")
    adapters, calls, _ = install_constructor(monkeypatch)

    def forbidden(*args, **kwargs):
        pytest.fail("CAUSAL_RED: disk reopened/rehash after verification", pytrace=False)

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(provenance, "_file_sha256", forbidden)
    adapters.OrtSFaceEmbedder(model_name="auraface", models_dir=tmp_path, verified_artifact=artifact)
    assert len(calls) == 1
    assert calls[0][0] is artifact.model_bytes
    assert sha(calls[0][0]) == sha(model)


@pytest.mark.parametrize("name", ["yunet", "auraface"])
@pytest.mark.parametrize("factor", ["model", "license"])
@pytest.mark.parametrize("damage", ["corrupt", "missing"])
def test_acquisition_rejects_each_artifact_factor(tmp_path, monkeypatch, name, factor, damage):
    provenance, entry, _, _ = artifact_fixture(tmp_path, monkeypatch, name)
    fn = symbol(PREFIX + "provenance", "acquire_verified_model_bytes")
    path = tmp_path / (entry.file_name if factor == "model" else entry.license_file)
    if damage == "missing":
        path.unlink()
        error = provenance.ModelMissingError
    else:
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        error = provenance.ModelIntegrityError
    with pytest.raises(error):
        fn(name, models_dir=tmp_path, expected=entry, max_model_bytes=4096,
           max_license_bytes=256, deadline_monotonic=time.monotonic() + 5)


@pytest.mark.parametrize("limit", ["model_cap", "license_cap", "deadline"])
def test_acquisition_bounds_are_enforced(tmp_path, monkeypatch, limit):
    provenance, entry, _, _ = artifact_fixture(tmp_path, monkeypatch)
    symbol(PREFIX + "provenance", "acquire_verified_model_bytes")
    overrides = {"model_cap": dict(max_model_bytes=1), "license_cap": dict(max_license_bytes=1),
                 "deadline": dict(deadline_monotonic=time.monotonic() - 1)}[limit]
    with pytest.raises((provenance.ModelIntegrityError, ValueError, TimeoutError)):
        acquire(provenance, entry, tmp_path, **overrides)


@pytest.mark.parametrize("type_name", ["SessionReceiptV1", "ExecutionReceiptV1", "LoadedRuntimeRecordV1"])
def test_receipt_contract_types_exist_and_are_immutable(type_name):
    receipt = symbol(PREFIX + "loaded_session", type_name)
    assert receipt.__dataclass_params__.frozen, f"CAUSAL_RED: {type_name} must be immutable"

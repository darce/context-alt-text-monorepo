"""c77 ABI-01/02: same-buffer producer tests, never native ONNX loads.

Missing c76 proposed symbols fail with CAUSAL_RED, never skip/xfail. Other
import errors remain fixture errors. Run with --noconftest: the service's
unrelated DB/application fixture tree is deliberately outside this unit lane.
PROV-01: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
TEST-15: https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/engineering.md#test-15
"""
from __future__ import annotations

import builtins
import hashlib
import importlib
import inspect
import io
import os
import time
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

PREFIX = "recognition.infrastructure.face_pipeline."


@pytest.fixture(autouse=True)
def native_ort_tripwire(monkeypatch):
    """C12: protect the native seam even if a wrapper was imported earlier."""
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    native = importlib.import_module("onnxruntime.capi._pybind_state")
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(1)
        pytest.fail("CAUSAL_RED: native ORT construction forbidden in fixture-only lane", pytrace=False)

    monkeypatch.setattr(native, "InferenceSession", forbidden)
    # GTMC-C78G1T-04: direct imports of the binding bypass the wrapper alias.
    binding = importlib.import_module("onnxruntime.capi.onnxruntime_pybind11_state")
    monkeypatch.setattr(binding, "InferenceSession", forbidden)
    yield attempts
    assert not attempts, "NATIVE_ORT_CONSTRUCTIONS must be 0"


def guard_artifact_io(monkeypatch, root, entry, *, max_opens, swap_on_close=False):
    """Scope guards to the two artifact paths; delegate all unrelated I/O.

    Path.read_bytes -> Path.open nesting is one logical open, not two.
    The same applies to custom openers delegating builtins.open to os.open.
    """
    paths = {os.path.abspath(root / entry.file_name),
             os.path.abspath(root / entry.license_file)}
    opens = dict.fromkeys(paths, 0)
    depth = dict.fromkeys(paths, 0)
    directory_fds = {}
    artifact_fds = {}
    swapped = set()
    raw_file = io.FileIO

    def swap(key):
        if swap_on_close and key not in swapped:
            swapped.add(key)
            # R02: a later uninstrumented/native read sees different content.
            with raw_file(key, "wb") as stream:
                stream.write(b"content changed after acquisition closed its handle")

    class ClosingTrap:
        def __init__(self, stream, key):
            self.stream, self.key = stream, key

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def close(self):
            self.stream.close()
            swap(self.key)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            result = self.stream.__exit__(*exc)
            swap(self.key)
            return result

    def wrap(original, *, tracks_fd=False):
        def guarded(path, *args, **kwargs):
            if isinstance(path, int):
                return original(path, *args, **kwargs)
            decoded = os.fsdecode(path)
            parent = directory_fds.get(kwargs.get("dir_fd")) if tracks_fd else None
            key = os.path.abspath(os.path.join(parent, decoded) if parent is not None else decoded)
            targeted = key in paths
            if targeted and depth[key] == 0:
                opens[key] += 1
                assert opens[key] <= max_opens, \
                    "CAUSAL_RED: artifact reopened/rehash after acquisition"
            if targeted:
                depth[key] += 1
            try:
                result = original(path, *args, **kwargs)
                flags = args[0] if args else kwargs.get("flags", 0)
                if tracks_fd and flags & os.O_DIRECTORY:
                    directory_fds[result] = key
                if tracks_fd and targeted:
                    artifact_fds[result] = key
                elif targeted and swap_on_close and hasattr(result, "close"):
                    result = ClosingTrap(result, key)
                return result
            finally:
                if targeted:
                    depth[key] -= 1
        return guarded

    for owner, name in ((Path, "open"), (Path, "read_bytes"),
                        (builtins, "open"), (io, "open")):
        monkeypatch.setattr(owner, name, wrap(getattr(owner, name)))
    monkeypatch.setattr(os, "open", wrap(os.open, tracks_fd=True))
    class GuardedFileIO(raw_file):
        def __init__(self, path, *args, **kwargs):
            if not isinstance(path, int):
                key = os.path.abspath(os.fsdecode(path))
                if key in paths and depth[key] == 0:
                    opens[key] += 1
                    assert opens[key] <= max_opens, "CAUSAL_RED: raw artifact reopened/rehash"
                self.artifact_key = key if key in paths else None
            else:
                self.artifact_key = None
            super().__init__(path, *args, **kwargs)

        def close(self):
            super().close()
            key = getattr(self, "artifact_key", None)
            if key is not None:
                swap(key)

    monkeypatch.setattr(io, "FileIO", GuardedFileIO)
    original_close = os.close

    def close(fd):
        directory_fds.pop(fd, None)
        key = artifact_fds.pop(fd, None)
        result = original_close(fd)
        if key is not None:
            swap(key)
        return result

    monkeypatch.setattr(os, "close", close)
    return opens


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
        return self.providers

    def get_session_options(self):
        return getattr(self, "sess_options", None)

    def get_provider_options(self):
        return {provider: {} for provider in self.get_providers()}

    def get_modelmeta(self):
        return SimpleNamespace(custom_metadata_map={}, graph_name="synthetic")

    def run(self, names, feeds):
        self.feeds.append({key: value.copy() for key, value in feeds.items()})
        return [self.output.copy()]


def install_constructor(monkeypatch, output=None):
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    calls = []
    session = RecordingSession(output)

    def constructor(source, sess_options=None, providers=None, **kwargs):
        calls.append((source, sess_options, providers))
        session.sess_options = sess_options
        session.providers = providers
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
    _, options, providers = calls[0]
    assert providers == ["CPUExecutionProvider"], "CAUSAL_RED: bytes dispatch must pin the CPU provider"
    assert options is not None, "CAUSAL_RED: bytes dispatch must pass session options"
    assert options.inter_op_num_threads == options.intra_op_num_threads == 1, \
        "CAUSAL_RED: bytes dispatch must retain single-thread options"
    assert options.execution_mode == adapters.ort.ExecutionMode.ORT_SEQUENTIAL, \
        "CAUSAL_RED: bytes dispatch must retain sequential execution"
    assert options.graph_optimization_level == adapters.ort.GraphOptimizationLevel.ORT_ENABLE_ALL, \
        "CAUSAL_RED: bytes dispatch must retain graph optimization"


def test_acquisition_hashes_same_buffer_consumed_by_constructor(tmp_path, monkeypatch):
    provenance, entry, model, license_bytes = artifact_fixture(tmp_path, monkeypatch)
    # C3: one acquisition per artifact, independent of hash implementation.
    # Counting opens catches verify-then-reopen without requiring sha256(data)
    # rather than hashlib.new/update/memoryview on the acquired buffer.
    with monkeypatch.context() as acquisition_patch:
        opens = guard_artifact_io(acquisition_patch, tmp_path, entry, max_opens=1,
                                  swap_on_close=True)
        artifact = acquire(provenance, entry, tmp_path)
    assert all(count == 1 for count in opens.values()), \
        "CAUSAL_RED: acquire each model/license once, then consume retained bytes"
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

    # C2: constructor metadata/fingerprint I/O is legal; artifact I/O is not.
    opens = guard_artifact_io(monkeypatch, tmp_path, entry, max_opens=0)
    adapters.OrtSFaceEmbedder(model_name="auraface", models_dir=tmp_path, verified_artifact=artifact)
    assert not any(opens.values()), "CAUSAL_RED: constructor attempted artifact reopen/rehash"
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
    # C15: documented existing integrity taxonomy or deadline timeout;
    # arbitrary ValueError is not evidence that the requested bound was checked.
    with pytest.raises((provenance.ModelIntegrityError, TimeoutError)):
        acquire(provenance, entry, tmp_path, **overrides)


@pytest.mark.parametrize("type_name", ["SessionReceiptV1", "ExecutionReceiptV1", "LoadedRuntimeRecordV1"])
def test_receipt_contract_types_exist_and_are_immutable(type_name):
    receipt = symbol(PREFIX + "loaded_session", type_name)
    assert receipt.__dataclass_params__.frozen, f"CAUSAL_RED: {type_name} must be immutable"


@pytest.mark.parametrize("type_name, mapping_field", [
    ("SessionReceiptV1", "actual_session_options"),
    ("ExecutionReceiptV1", "input_lineage"),
    ("ExecutionReceiptV1", "detector_input"),
    ("ExecutionReceiptV1", "alignment"),
    ("ExecutionReceiptV1", "embedder_input"),
    ("ExecutionReceiptV1", "raw_output"),
    ("ExecutionReceiptV1", "normalized_output"),
    ("LoadedRuntimeRecordV1", "sessions"),
])
def test_receipt_mappings_reject_mutation_and_detach_input_aliases(type_name, mapping_field):
    """C16: frozen record attributes must also retain immutable evidence maps."""
    receipt = symbol(PREFIX + "loaded_session", type_name)
    now = datetime(2026, 10, 13, tzinfo=UTC)
    digest = sha(b"synthetic receipt fixture")
    if type_name == "SessionReceiptV1":
        provenance = importlib.import_module(PREFIX + "provenance")
        numeric_fixture = provenance.NumericRuntimeFingerprint(
            opencv_version="0.fixture", opencv_major=0, onnxruntime_version="0.fixture",
            numpy_version="0.fixture", scipy_version="0.fixture", pillow_version="0.fixture",
            hdbscan_version="0.fixture", pgvector_version="0.fixture")
        values = dict(session_id="fixture-session", runtime_generation_id="fixture-generation",
                      logical_model_name="auraface", constructed_at=now,
                      observed_weight_sha256=digest, observed_weight_size_bytes=1,
                      observed_license_sha256=digest, observed_license_size_bytes=1,
                      manifest_expectation_sha256=digest, frozen_preprocessing_sha256=digest,
                      numeric_runtime_fingerprint=numeric_fixture, actual_providers=("CPUExecutionProvider",),
                      actual_input_metadata=(), actual_output_metadata=(),
                      actual_session_options={"intra_op_num_threads": 1}, graph_analysis=None)
    elif type_name == "ExecutionReceiptV1":
        values = dict(execution_id="fixture-execution", runtime_generation_id="fixture-generation",
                      detector_session_id="fixture-detector", embedder_session_id="fixture-embedder",
                      captured_at=now, input_lineage={}, detector_input={}, detections_sha256=None,
                      alignment={}, embedder_input={"sha256": digest}, raw_output={},
                      normalized_output={}, graph_analysis_sha256=None, completion="partial")
    else:
        values = dict(producer_abi_version=1, runtime_generation_id="fixture-generation",
                      model_id="fixture-auraface512", effective_profile="auraface",
                      declared_embedding_dimension=512, observed_embedding_dimension=None,
                      preprocessing_id="arcface-112", compatibility_sha256=digest, config_sha256=digest,
                      sessions={}, frozen_preprocessing_spec=None, execution_receipt=None,
                      state="not_loaded", reason_code="synthetic_missing_pair", observed_at=now)
    incoming = values[mapping_field]
    before = dict(incoming)
    record = receipt(**values)
    retained = getattr(record, mapping_field)
    assert dict(retained) == before
    incoming["fixture_alias_mutation"] = "changed"
    assert dict(retained) == before, "CAUSAL_RED: caller can rewrite retained receipt evidence"
    with pytest.raises(TypeError):
        retained["fixture_direct_mutation"] = "changed"


def test_frozen_preprocessing_contract_is_immutable():
    spec = symbol(PREFIX + "loaded_session", "FrozenPreprocessingSpecV1")
    assert spec.__dataclass_params__.frozen, "CAUSAL_RED: preprocessing spec must be immutable"


def test_native_tripwire_covers_direct_binding_import():
    from onnxruntime.capi.onnxruntime_pybind11_state import InferenceSession
    wrapper = importlib.import_module("onnxruntime.capi._pybind_state")
    assert InferenceSession is wrapper.InferenceSession, \
        "CAUSAL_RED: direct native binding import bypasses the fixture tripwire"


@pytest.fixture(params=[
    ("SessionReceiptV1", "actual_session_options"),
    ("ExecutionReceiptV1", "input_lineage"),
    ("ExecutionReceiptV1", "detector_input"),
    ("ExecutionReceiptV1", "alignment"),
    ("ExecutionReceiptV1", "embedder_input"),
    ("ExecutionReceiptV1", "raw_output"),
    ("ExecutionReceiptV1", "normalized_output"),
    ("LoadedRuntimeRecordV1", "sessions"),
], ids=lambda pair: ".".join(pair))
def nested_receipt_mapping(request):
    type_name, mapping_field = request.param
    receipt = symbol(PREFIX + "loaded_session", type_name)
    now = datetime(2026, 10, 13, tzinfo=UTC)
    digest = sha(b"synthetic nested receipt fixture")
    if type_name == "SessionReceiptV1":
        values = dict(
            session_id="fixture-session", runtime_generation_id="fixture-generation",
            logical_model_name="auraface", constructed_at=now,
            observed_weight_sha256=digest, observed_weight_size_bytes=1,
            observed_license_sha256=digest, observed_license_size_bytes=1,
            manifest_expectation_sha256=digest, frozen_preprocessing_sha256=digest,
            numeric_runtime_fingerprint={}, actual_providers=("CPUExecutionProvider",),
            actual_input_metadata=(), actual_output_metadata=(),
            actual_session_options={}, graph_analysis=None,
        )
    elif type_name == "ExecutionReceiptV1":
        values = dict(
            execution_id="fixture-execution", runtime_generation_id="fixture-generation",
            detector_session_id="fixture-detector", embedder_session_id="fixture-embedder",
            captured_at=now, input_lineage={}, detector_input={}, detections_sha256=None,
            alignment={}, embedder_input={}, raw_output={}, normalized_output={},
            graph_analysis_sha256=None, completion="partial",
        )
    else:
        values = dict(
            producer_abi_version=1, runtime_generation_id="fixture-generation",
            model_id="fixture-auraface512", effective_profile="auraface",
            declared_embedding_dimension=512, observed_embedding_dimension=None,
            preprocessing_id="arcface-112", compatibility_sha256=digest,
            config_sha256=digest, sessions={}, frozen_preprocessing_spec=None,
            execution_receipt=None, state="not_loaded",
            reason_code="synthetic_missing_pair", observed_at=now,
        )
    incoming = {"nested": {"items": [{"value": "original"}], "shape": [1, 2]}}
    values[mapping_field] = incoming
    record = receipt(**values)
    return incoming, getattr(record, mapping_field)


def test_receipt_nested_input_aliases_are_detached(nested_receipt_mapping):
    incoming, retained = nested_receipt_mapping
    incoming["nested"]["items"][0]["value"] = "changed"
    incoming["nested"]["items"].append({"value": "added"})
    incoming["nested"]["shape"][0] = 99
    incoming["nested"]["new_key"] = "added"
    assert retained["nested"]["items"][0]["value"] == "original", \
        "CAUSAL_RED: nested caller alias rewrote retained receipt evidence"
    assert len(retained["nested"]["items"]) == 1
    assert tuple(retained["nested"]["shape"]) == (1, 2)
    assert "new_key" not in retained["nested"]


def test_receipt_nested_values_reject_direct_mutation(nested_receipt_mapping):
    _, retained = nested_receipt_mapping
    with pytest.raises(TypeError):
        retained["nested"]["new_key"] = "changed"
    with pytest.raises(TypeError):
        retained["nested"]["items"][0]["value"] = "changed"
    with pytest.raises(TypeError):
        retained["nested"]["items"][0] = {"value": "changed"}
    with pytest.raises(TypeError):
        retained["nested"]["shape"][0] = 99

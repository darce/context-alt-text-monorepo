"""C82R-HFACEG1-F4: independent verification oracles, fixture-only.

Each negative has matching unrelated pins and a positive control. Native ORT
is forbidden even when a constructor's verification is deliberately omitted.
"""
from __future__ import annotations

import hashlib
import importlib
import struct
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from recognition.tests.unit.test_loaded_face_session_producer import tiny_graph

PREFIX = "recognition.infrastructure.face_pipeline."


@pytest.fixture(autouse=True)
def native_ort_tripwire(monkeypatch):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append(1)
        pytest.fail("CAUSAL_RED: native ORT construction forbidden", pytrace=False)

    for module in ("onnxruntime.capi._pybind_state",
                   "onnxruntime.capi.onnxruntime_pybind11_state"):
        monkeypatch.setattr(importlib.import_module(module), "InferenceSession", forbidden)
    yield
    assert not attempts, "NATIVE_ORT_CONSTRUCTIONS must be 0"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def external_graph():
    # Same protobuf encoding as tiny_graph; TensorProto.data_location=EXTERNAL
    # and external_data={key: location, value: weights.bin}. No file is read.
    def blob(field, payload):
        assert len(payload) < 128
        return bytes([(field << 3) | 2, len(payload)]) + payload

    location = blob(1, b"location") + blob(2, b"weights.bin")
    tensor = b"\x08\x01\x10\x01" + blob(8, b"output")
    tensor += blob(13, location) + b"\x70\x01"
    graph = blob(2, b"external-fixture") + blob(5, tensor)
    return b"\x08\x08" + blob(7, graph)


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    provenance = importlib.import_module(PREFIX + "provenance")
    original = tiny_graph("verification-guards")
    license_bytes = b"synthetic verification guard license\n"
    entry = replace(provenance.MODEL_MANIFEST["auraface"],
                    file_name="fixture.onnx", license_file="fixture.LICENSE",
                    sha256=digest(original), size_bytes=len(original),
                    license_sha256=digest(license_bytes))
    (tmp_path / entry.file_name).write_bytes(original)
    (tmp_path / entry.license_file).write_bytes(license_bytes)
    monkeypatch.setitem(provenance.MODEL_MANIFEST, "auraface", entry)
    return provenance, entry, original, tmp_path


def acquire(artifacts, *, data=None, expected=None):
    provenance, entry, original, root = artifacts
    if data is not None:
        (root / entry.file_name).write_bytes(data)
    return provenance.acquire_verified_model_bytes(
        "auraface", models_dir=root, expected=entry if expected is None else expected,
        max_model_bytes=4096, max_license_bytes=256,
        deadline_monotonic=time.monotonic() + 5,
    )


def changed_tensor(original):
    # Change a float in raw_data, preserving every protobuf tag/length and size.
    before, after = struct.pack("<ff", 3, 4), struct.pack("<ff", 5, 4)
    assert original.count(before) == 1
    changed = original.replace(before, after, 1)
    assert len(changed) == len(original) and digest(changed) != digest(original)
    return changed


def test_hash_rejects_valid_wire_tensor_change(artifacts):
    provenance, entry, original, root = artifacts
    changed = changed_tensor(original)
    # Explicitly establish that parsing cannot mask an omitted digest guard.
    provenance._validate_self_contained_onnx(
        changed, deadline_monotonic=time.monotonic() + 5)
    with pytest.raises(provenance.ModelIntegrityError, match="size or digest mismatch"):
        acquire(artifacts, data=changed)


def test_size_rejects_wrong_declaration_with_matching_digest(artifacts):
    provenance, entry, original, root = artifacts
    assert entry.sha256 == digest(original)
    with pytest.raises(provenance.ModelIntegrityError, match="size or digest mismatch"):
        acquire(artifacts, expected=replace(entry, size_bytes=len(original) + 1))


@pytest.mark.parametrize("kind", ["external", "missing_graph"])
def test_graph_rejects_invalid_structure_with_matching_pins(artifacts, kind):
    provenance, entry, original, root = artifacts
    data = external_graph() if kind == "external" else b"\x08\x08"
    expected = replace(entry, sha256=digest(data), size_bytes=len(data))
    reason = "external ONNX tensor" if kind == "external" else "one graph and IR version"
    with pytest.raises(provenance.ModelIntegrityError, match=reason):
        acquire(artifacts, data=data, expected=expected)


def legacy_constructor(artifacts, monkeypatch):
    provenance, entry, original, root = artifacts
    adapters = importlib.import_module(PREFIX + "ort_adapters")
    calls = []

    def recording_session(model):
        calls.append(model)
        return SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="input")])

    monkeypatch.setattr(adapters, "_ort_session", recording_session)
    return adapters, calls


def test_legacy_constructor_rejects_tampered_input(artifacts, monkeypatch):
    provenance, entry, original, root = artifacts
    adapters, calls = legacy_constructor(artifacts, monkeypatch)
    (root / entry.file_name).write_bytes(changed_tensor(original))
    with pytest.raises(provenance.ModelIntegrityError, match="sha256 mismatch"):
        adapters.OrtSFaceEmbedder(model_name="auraface", models_dir=root)
    assert calls == [], "verification must reject before session construction"


@pytest.mark.parametrize("guard", ["hash", "size", "graph", "legacy"])
def test_valid_input_accepted_for_guard(artifacts, monkeypatch, guard):
    provenance, entry, original, root = artifacts
    if guard == "legacy":
        adapters, calls = legacy_constructor(artifacts, monkeypatch)
        embedder = adapters.OrtSFaceEmbedder(model_name="auraface", models_dir=root)
        assert embedder.embedding_dim == entry.embedding_dim
        assert calls == [root / entry.file_name]
    else:
        verified = acquire(artifacts)
        assert verified.model_bytes == original
        assert verified.model_sha256 == entry.sha256
        assert verified.model_size_bytes == entry.size_bytes

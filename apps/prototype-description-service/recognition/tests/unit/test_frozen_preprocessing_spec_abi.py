"""ABI-04: compare the retained recipe with actual fake-session execution."""
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, replace
import hashlib
import importlib
import json

import numpy as np
import pytest

from recognition.infrastructure.face_pipeline import loaded_session
from recognition.tests.unit.test_face_runtime_attestation_drift import (
    native_ort_tripwire, observe, serving_fixture,
)
from recognition.tests.unit.test_loaded_face_preprocessing_receipts import asymmetric_crop


def plain(value):
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


@pytest.fixture
def executing_pair(tmp_path, monkeypatch):
    _, adapter, config, detector_session, embedder_session, _ = serving_fixture(tmp_path, monkeypatch)
    return adapter, config, detector_session, embedder_session


def test_spec_equals_execution_values(executing_pair, monkeypatch):
    adapter, config, detector_session, embedder_session = executing_pair
    runtime = adapter._runtime
    spec = observe(adapter, config).frozen_preprocessing_spec
    assert isinstance(spec, loaded_session.FrozenPreprocessingSpecV1)
    assert set(spec.detector) == {"channel_order", "layout", "dtype", "pad_divisor", "pad_value",
                                 "score_threshold", "nms_threshold", "top_k"}
    assert spec.detector == dict(channel_order="BGR", layout="NCHW", dtype="float32",
                                pad_divisor=32, pad_value=0, score_threshold=runtime.detector.score_threshold,
                                nms_threshold=runtime.detector.nms_threshold, top_k=runtime.detector.top_k)
    recipe = runtime.embedder._verified_artifact.manifest_snapshot.preprocessing
    for field in fields(recipe):
        assert spec.embedding[field.name] == getattr(recipe, field.name)
    assert spec.embedding["layout"] == "NCHW"
    assert spec.embedding["dtype"] == "float32"
    alignment = importlib.import_module("recognition.infrastructure.face_pipeline.aligner")
    calls = {}
    original_transform = alignment.arcface_similarity_transform_matrix
    original_warp = alignment.cv2.warpAffine

    def transform(src, *, dst_landmarks=None):
        calls["destination"] = dst_landmarks.copy()
        return original_transform(src, dst_landmarks=dst_landmarks)

    def warp(image, affine, size, **kwargs):
        calls.update(size=size, warp=kwargs)
        crop = original_warp(image, affine, size, **kwargs)
        calls["crop"] = crop.copy()
        return crop

    monkeypatch.setattr(alignment, "arcface_similarity_transform_matrix", transform)
    monkeypatch.setattr(alignment.cv2, "warpAffine", warp)
    # A changed ambient template must not change the retained execution.
    monkeypatch.setattr(alignment, "ARCFACE_CANONICAL_LANDMARKS_112", np.zeros((5, 2), np.float32))
    result = adapter._detect_sync(b"fixture", "abi-fixture")
    assert len(result) == 1 and len(embedder_session.feeds) == 1
    np.testing.assert_array_equal(spec.alignment["template"], calls["destination"])
    np.testing.assert_array_equal(spec.alignment["template"], runtime.aligner.dst_landmarks)
    assert spec.alignment["dtype"] == str(calls["destination"].dtype)
    from recognition.infrastructure.face_pipeline.ort_adapters import tensor_record
    assert spec.alignment["template_sha256"] == tensor_record(calls["destination"])["sha256"]
    assert spec.alignment["estimator"] == "umeyama"
    assert spec.alignment["landmark_order"] == alignment.YUNET_LANDMARK_NAMES
    assert spec.alignment["output_size"] == calls["size"] == spec.embedding["input_size"]
    assert spec.alignment["interpolation"] == "INTER_LINEAR"
    assert spec.alignment["border"] == "BORDER_CONSTANT"
    assert calls["warp"] == dict(flags=alignment.cv2.INTER_LINEAR,
                                 borderMode=alignment.cv2.BORDER_CONSTANT, borderValue=spec.alignment["border_value"])
    detector_feed = detector_session.feeds[0]["input"]
    expected_detector = np.zeros((1, 3, 128, 128), np.float32)
    expected_detector[0, :, :112, :112] = asymmetric_crop().transpose(2, 0, 1)
    np.testing.assert_array_equal(detector_feed, expected_detector)
    assert detector_feed.dtype == np.dtype(spec.detector["dtype"])
    crop = calls["crop"]
    channel_indices = (2, 1, 0) if spec.embedding["channel_order"] == "RGB" else (0, 1, 2)
    expected = np.empty((1, 3, *spec.embedding["input_size"]), dtype=spec.embedding["dtype"])
    for channel, source in enumerate(channel_indices):
        expected[0, channel] = (crop[:, :, source].astype(np.float32) - np.float32(spec.embedding["input_mean"])) * np.float32(spec.embedding["input_scale"])
    np.testing.assert_array_equal(embedder_session.feeds[0]["input"], expected)
    assert spec.graph_analysis is None  # No fabricated graph evidence.
    assert spec.pipeline_normalization == "l2"
    assert np.linalg.norm(result[0].embedding) == pytest.approx(1)


def test_spec_deep_immutability(executing_pair):
    adapter, config, _, _ = executing_pair
    spec = observe(adapter, config).frozen_preprocessing_spec
    assert spec.__dataclass_params__.frozen
    with pytest.raises(FrozenInstanceError):
        spec.pipeline_normalization = "none"
    with pytest.raises(TypeError):
        spec.detector["pad_value"] = 255
    with pytest.raises(TypeError):
        spec.embedding["input_size"][0] = 224
    with pytest.raises(TypeError):
        spec.alignment["template"][0][0] = 0
    with pytest.raises(ValueError):
        adapter._runtime.aligner.dst_landmarks.setflags(write=True)
    values = {field.name: plain(getattr(spec, field.name)) for field in fields(spec)}
    values["graph_analysis"] = {"ops": ["fixture"], "details": {"normalized": False}}
    copied = loaded_session.FrozenPreprocessingSpecV1(**values)
    before = copied.digest()
    values["alignment"]["template"][0][0] += 1
    values["graph_analysis"]["ops"].append("changed")
    assert copied.digest() == before
    with pytest.raises(TypeError):
        copied.graph_analysis["details"]["normalized"] = True


def test_digest_covers_every_abi_field(executing_pair):
    adapter, config, _, _ = executing_pair
    record = observe(adapter, config)
    spec = record.frozen_preprocessing_spec
    values = {field.name: plain(getattr(spec, field.name)) for field in fields(spec)}
    expected = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    baseline_digest = spec.digest()
    assert all(receipt.frozen_preprocessing_sha256 == baseline_digest for receipt in record.sessions.values())
    assert set(values) == {"detector", "embedding", "alignment", "graph_analysis", "pipeline_normalization"}
    # Mutate every emitted leaf, including each template coordinate and size element.
    def leaves(value, path=()):
        if isinstance(value, dict):
            for key, item in value.items():
                yield from leaves(item, (*path, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from leaves(item, (*path, index))
        else:
            yield path, value
    paths = list(leaves(values))
    assert len(paths) >= 40
    for path, value in paths:
        changed = {field.name: plain(getattr(spec, field.name)) for field in fields(spec)}
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = (not value if isinstance(value, bool) else value + 1 if isinstance(value, (float, int))
                            else value + "-changed" if isinstance(value, str) else {"digest": "fixture"})
        mutated = loaded_session.FrozenPreprocessingSpecV1(**changed)
        assert mutated.digest() != baseline_digest, f"digest omitted ABI field {path}"
    assert baseline_digest == expected
    reordered = {key: values[key] for key in reversed(values)}
    assert loaded_session.FrozenPreprocessingSpecV1(**reordered).digest() == expected


def test_runtime_rejects_mapping_spec(executing_pair):
    adapter, config, _, _ = executing_pair
    record = observe(adapter, config)
    with pytest.raises(TypeError, match="FrozenPreprocessingSpecV1"):
        replace(record, frozen_preprocessing_spec={})
    assert replace(record, frozen_preprocessing_spec=None).frozen_preprocessing_spec is None

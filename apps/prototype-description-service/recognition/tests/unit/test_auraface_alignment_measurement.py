"""FIR512-2: validate AuraFace alignment/preprocessing measurement evidence.

The JSON is the measurement record. This module does not require the 261 MiB
ONNX artifact for schema/hash checks. Live file hashing runs only when the
read-only VM path exists. External geometry must stay unsupported unless the
JSON itself carries graph evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from recognition.infrastructure.face_pipeline import provenance
from recognition.infrastructure.face_pipeline.provenance import AURAFACE_REVISION, MODEL_MANIFEST

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "face_pipeline"
_EVIDENCE_PATH = _FIXTURE_DIR / "auraface_alignment_measurement.json"
_CROP_PATH = _FIXTURE_DIR / "synthetic_112_crop.npy"
_LIVE_MODEL = Path("/opt/acx-backend/data/dev-models/face_pipeline/glintr100.onnx")
_LIVE_LICENSE = Path("/opt/acx-backend/data/dev-models/face_pipeline/LICENSE.auraface.md")

_REQUIRED_TOP = frozenset(
    {
        "schema_version",
        "kind",
        "task_ref",
        "lane_id",
        "measured_at",
        "artifact",
        "commands",
        "graph",
        "input_scale",
        "input_offset",
        "channel_order",
        "alignment",
        "raw_output_normalization",
        "composed_parity",
        "upstream_documented_contract",
        "evidence_limits",
        "unresolved_questions",
        "production_unverified_markers_flipped",
    }
)
_SHA256_LEN = 64
_ABSENT_OPS = ("Sub", "Mul", "Div", "ReduceL2", "LpNormalization", "Transpose", "Sqrt")
_COMPOSED_FIELDS = ("input_scale", "input_offset", "channel_order", "alignment")
_ARCFACE_DST = [
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
]
_COMPOSED_DIR = _FIXTURE_DIR / "auraface_composed"


def _load_evidence() -> dict[str, Any]:
    payload = json.loads(_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _assert_sha256(value: object) -> str:
    assert isinstance(value, str)
    assert len(value) == _SHA256_LEN
    assert value == value.lower()
    assert all(character in "0123456789abcdef" for character in value)
    return value


def test_evidence_schema_is_complete() -> None:
    evidence = _load_evidence()
    missing = sorted(_REQUIRED_TOP - evidence.keys())
    assert missing == [], f"measurement JSON missing keys: {missing}"
    assert evidence["schema_version"] == 1
    assert evidence["kind"] == "auraface_alignment_measurement"
    assert evidence["task_ref"] == "FIR512-2"
    assert evidence["lane_id"] == "measure"
    assert evidence["production_unverified_markers_flipped"] is True
    assert isinstance(evidence["measured_at"], str) and evidence["measured_at"].strip()
    assert isinstance(evidence["commands"], list) and evidence["commands"]
    assert all(isinstance(command, str) and command.strip() for command in evidence["commands"])
    assert isinstance(evidence["evidence_limits"], list) and evidence["evidence_limits"]
    assert isinstance(evidence["unresolved_questions"], list) and evidence["unresolved_questions"]


def test_artifact_hashes_match_manifest() -> None:
    evidence = _load_evidence()
    artifact = evidence["artifact"]
    entry = MODEL_MANIFEST["auraface"]

    assert artifact["file_name"] == entry.file_name == "glintr100.onnx"
    assert artifact["license_file"] == entry.license_file == "LICENSE.auraface.md"
    assert artifact["size_bytes"] == entry.size_bytes == 260_694_151
    assert _assert_sha256(artifact["sha256"]) == entry.sha256
    assert _assert_sha256(artifact["license_sha256"]) == entry.license_sha256
    assert artifact["matches_manifest_pins"] is True


@pytest.mark.skipif(not _LIVE_MODEL.is_file() or not _LIVE_LICENSE.is_file(), reason="AuraFace VM artifact is absent")
def test_live_artifact_hashes_match_evidence() -> None:
    evidence = _load_evidence()
    artifact = evidence["artifact"]
    assert _sha256(_LIVE_MODEL) == artifact["sha256"]
    assert _LIVE_MODEL.stat().st_size == artifact["size_bytes"]
    assert _sha256(_LIVE_LICENSE) == artifact["license_sha256"]


def test_graph_properties_are_measured_and_exclude_external_geometry() -> None:
    graph = _load_evidence()["graph"]
    assert graph["status"] == "measured"
    assert graph["independently_supported"] is True
    assert graph["preprocessing_ops_present"] is False
    assert graph["l2_ops_present"] is False
    assert graph["alignment_ops_present"] is False
    assert graph["channel_swap_ops_present"] is False
    assert tuple(graph["absent_op_types"]) == _ABSENT_OPS
    for op_type in _ABSENT_OPS:
        assert graph["op_counts"].get(op_type, 0) == 0

    assert graph["input"]["name"] == "data"
    assert graph["input"]["shape"] == [None, 3, 112, 112]
    assert graph["input"]["elem_type"] == "float32"
    assert graph["output"]["name"] == "1333"
    assert graph["output"]["shape"] == [1, 512]
    assert graph["first_node"]["op_type"] == "Conv"
    assert graph["first_node"]["inputs"][0] == "data"
    assert graph["first_node"]["weight_dims"] == [64, 3, 3, 3]
    assert graph["last_node"]["op_type"] == "BatchNormalization"
    assert graph["last_node"]["outputs"] == ["1333"]
    assert graph["input_size"]["independently_supported"] is True
    assert graph["input_size"]["value"] == [112, 112]


def test_external_geometry_stays_absent_from_graph_but_composed_reference_supports_it() -> None:
    evidence = _load_evidence()
    expected_values = {
        "input_scale": 1.0 / 127.5,
        "input_offset": 127.5,
        "channel_order": "RGB",
        "alignment": "arcface-112",
    }
    for field_name in _COMPOSED_FIELDS:
        record = evidence[field_name]
        assert record["graph_status"] == "not_in_graph", field_name
        assert record["independently_supported"] is True, field_name
        assert record["blocked_reason"] is None, field_name
        assert isinstance(record["graph_blocked_reason"], str) and record["graph_blocked_reason"].strip()
        if field_name in {"input_scale", "input_offset"}:
            assert record["value"] == pytest.approx(expected_values[field_name])
        else:
            assert record["value"] == expected_values[field_name]

    alignment = evidence["alignment"]
    assert alignment["template_id"] == "arcface-112"
    assert alignment["coordinates"] == _ARCFACE_DST


def test_raw_output_is_measured_not_l2_normalized_in_graph() -> None:
    record = _load_evidence()["raw_output_normalization"]
    assert record["graph_status"] == "measured"
    assert record["independently_supported"] is True
    assert record["l2_in_graph"] is False
    assert record["last_op_type"] == "BatchNormalization"
    fixture = record["fixture_inference"]
    assert fixture["status"] == "measured"
    assert fixture["fixture"] == "synthetic_112_crop.npy"
    _assert_sha256(fixture["fixture_sha256"])
    assert fixture["unit_l2_for_any_tried_convention"] is False
    l2_by_convention = fixture["l2_by_convention"]
    assert isinstance(l2_by_convention, dict) and l2_by_convention
    for label, value in l2_by_convention.items():
        assert isinstance(value, (int, float)), label
        assert value > 1.0, label


def test_raw_output_fixture_digest_matches_saved_measurement() -> None:
    fixture = _load_evidence()["raw_output_normalization"]["fixture_inference"]
    assert fixture["fixture"] == _CROP_PATH.name
    assert _sha256(_CROP_PATH) == _assert_sha256(fixture["fixture_sha256"])


def test_composed_sface_golden_is_not_auraface_proof() -> None:
    composed = _load_evidence()["composed_parity"]["sface_composed_golden"]
    assert composed["status"] == "not_auraface_proof"
    assert composed["independently_supported"] is False
    assert composed["model"] == "face_recognition_sface_2021dec.onnx"
    assert composed["embedding_dim"] == 128
    assert "not AuraFace proof" in composed["reason"]

    meta_path = _FIXTURE_DIR / "aligner_composed_embedding_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["model"] == composed["model"]
    assert meta["embedding_dim"] == 128


def test_documented_contract_is_not_treated_as_insightface_runtime_measurement() -> None:
    contract = _load_evidence()["upstream_documented_contract"]
    assert contract["status"] == "recorded_not_verified"
    assert contract["independently_supported"] is False
    assert contract["insightface_runtime"]["status"] == "blocked"
    assumption = contract["local_manifest_assumption"]
    entry = MODEL_MANIFEST["auraface"]
    preprocessing = entry.preprocessing
    assert preprocessing is not None
    assert assumption["status"] == "verified_by_composed_independent_reference"
    history = assumption["historical_unverified"]
    assert history["declared_unverified_alignment_template_id"] == "arcface-112-unverified"
    assert history["declared_unverified_output_l2_normalized"] is True
    scale_expression = assumption["declared_input_scale"]
    numerator, separator, denominator = scale_expression.partition("/")
    assert separator == "/"
    assert float(numerator) / float(denominator) == pytest.approx(preprocessing.input_scale)
    assert assumption["declared_input_mean"] == pytest.approx(preprocessing.input_mean)
    assert assumption["declared_alignment_template_id"] == preprocessing.alignment_template_id == "arcface-112"
    assert assumption["declared_channel_order"] == preprocessing.channel_order == "RGB"
    assert assumption["declared_output_l2_normalized"] is preprocessing.output_l2_normalized is False
    assert contract["publisher_model_card"]["revision"] == AURAFACE_REVISION == entry.source_ref
    assert contract["publisher_model_card"]["example_uses_insightface_faceanalysis"] is True
    assert contract["publisher_model_card"]["example_reads_normed_embedding"] is True

    provenance_source = Path(provenance.__file__).read_text(encoding="utf-8")
    assert 'alignment_template_id="arcface-112"' in provenance_source
    assert "output_l2_normalized=False" in provenance_source
    assert "arcface-112-unverified" in provenance_source
    assert "UNVERIFIED" in provenance_source


def test_upstream_reference_and_composed_parity_are_distinguished() -> None:
    evidence = _load_evidence()
    reference = evidence["upstream_documented_contract"]["insightface_reference"]
    assert reference["status"] == "reference_supported_not_independently_verified"
    assert reference["independently_supported"] is False
    assert reference["source_commit"] == "1480e705287bc5d59f923b46c260ec6e3e4150f6"
    assert reference["arcface_onnx_url"].endswith("/python-package/insightface/model_zoo/arcface_onnx.py")
    assert reference["face_align_url"].endswith("/python-package/insightface/utils/face_align.py")
    assert reference["recipe"]["input_scale"] == "1.0/127.5"
    assert reference["recipe"]["input_offset"] == "127.5"
    assert reference["recipe"]["channel_order"].startswith("swapRB=True")
    assert reference["recipe"]["alignment_template_id"] == "arcface-112"
    assert reference["recipe"]["alignment_coordinates"] == [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ]
    composed = evidence["composed_parity"]["auraface_ort_composed_parity"]
    assert composed["status"] == "measured"
    assert composed["independently_supported"] is True
    assert composed["embedding_dim"] == 512
    assert composed["crops_bit_identical"] is True
    assert composed["raw_output_normalized"] is False
    assert composed["pipeline_l2_applied"] is True
    assert composed["insightface_runtime_imported"] is False
    assert composed["composed_cosine"] >= composed["cosine_min"] == pytest.approx(0.9999999)
    assert composed["crop_sha256"] == _assert_sha256(composed["crop_sha256"])
    assert composed["ort_session"]["graph_optimization_level"] == "ORT_DISABLE_ALL"
    assert composed["ort_session"]["intra_op_num_threads"] == 1


def _normalise_ort_shape(shape: list[object]) -> list[int | None]:
    return [None if dimension in (None, "None") else int(dimension) for dimension in shape]


@pytest.mark.skipif(
    not _LIVE_MODEL.is_file() or not _LIVE_LICENSE.is_file(),
    reason="AuraFace VM artifact is absent",
)
def test_live_artifact_replays_ort_io_and_saved_raw_norm_conventions() -> None:
    np = pytest.importorskip("numpy")
    ort = pytest.importorskip("onnxruntime")
    evidence = _load_evidence()
    graph = evidence["graph"]
    fixture = evidence["raw_output_normalization"]["fixture_inference"]
    crop = np.load(_CROP_PATH, allow_pickle=False)
    assert crop.shape == (112, 112, 3)
    assert crop.dtype == np.uint8

    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(_LIVE_MODEL),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )

    input_meta = session.get_inputs()[0]
    output_meta = session.get_outputs()[0]
    assert input_meta.name == graph["input"]["name"] == "data"
    assert _normalise_ort_shape(input_meta.shape) == graph["input"]["shape"]
    assert input_meta.type == graph["input"]["ort_type"]
    assert output_meta.name == graph["output"]["name"] == "1333"
    assert _normalise_ort_shape(output_meta.shape) == graph["output"]["shape"]
    assert output_meta.type == graph["output"]["ort_type"]
    assert session.get_providers() == ["CPUExecutionProvider"]

    def nchw(value: Any) -> Any:
        return np.ascontiguousarray(value.astype(np.float32).transpose(2, 0, 1)[None, ...])

    conventions = {
        "hwc_as_float_0_255": nchw(crop),
        "swap_channels_float_0_255": nchw(crop[..., ::-1]),
        "arcface_minus_127p5_div_127p5_as_is": nchw((crop.astype(np.float32) - 127.5) / 127.5),
        "arcface_minus_127p5_div_127p5_swapped": nchw((crop[..., ::-1].astype(np.float32) - 127.5) / 127.5),
        "div_255_as_is": nchw(crop.astype(np.float32) / 255.0),
    }
    expected_l2 = fixture["l2_by_convention"]
    assert set(conventions) == set(expected_l2)
    for label, blob in conventions.items():
        output = session.run([output_meta.name], {input_meta.name: blob})[0]
        assert output.shape == (1, 512)
        actual_l2 = float(np.linalg.norm(output[0]))
        assert actual_l2 == pytest.approx(expected_l2[label], rel=0.0, abs=1e-5)
        assert actual_l2 > 1.0


def test_auraface_aligner_crop_stays_bgr_not_rgb_swapped() -> None:
    np = pytest.importorskip("numpy")
    from recognition.infrastructure.face_pipeline.aligner import FivePointAligner
    from recognition.infrastructure.face_pipeline.model_space import ModelSpace

    image = np.load(_FIXTURE_DIR / "aligner_source_image.npy", allow_pickle=False)
    landmarks = np.load(_FIXTURE_DIR / "aligner_landmarks.npy", allow_pickle=False)
    sface_crop = FivePointAligner(space=ModelSpace.FACE_PIPELINE).align(image, landmarks).crop
    aura_crop = FivePointAligner(space=ModelSpace.AURAFACE).align(image, landmarks).crop
    assert not np.array_equal(aura_crop, sface_crop[..., ::-1])
    expected = np.load(_COMPOSED_DIR / "inhouse_crop.npy", allow_pickle=False)
    np.testing.assert_array_equal(aura_crop, expected)
    aligner = FivePointAligner(space=ModelSpace.AURAFACE)
    assert aligner.channel_order == "RGB"
    assert aligner.template_id == "arcface-112"


def test_composed_goldens_match_evidence_and_manifest() -> None:
    np = pytest.importorskip("numpy")
    evidence = _load_evidence()
    composed = evidence["composed_parity"]["auraface_ort_composed_parity"]
    meta_path = _COMPOSED_DIR / "aligner_composed_embedding_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    entry = MODEL_MANIFEST["auraface"]
    preprocessing = entry.preprocessing
    assert preprocessing is not None

    assert meta["kind"] == "auraface_composed_embedding_golden"
    assert meta["model"] == entry.file_name == "glintr100.onnx"
    assert meta["model_sha256"] == entry.sha256
    assert meta["embedding_dim"] == 512
    assert meta["preprocessing"]["alignment_template_id"] == preprocessing.alignment_template_id == "arcface-112"
    assert meta["preprocessing"]["channel_order"] == "RGB"
    assert meta["preprocessing"]["input_mean"] == pytest.approx(preprocessing.input_mean)
    assert meta["preprocessing"]["output_l2_normalized"] is False
    assert meta["reference"]["source_commit"] == "1480e705287bc5d59f923b46c260ec6e3e4150f6"
    assert meta["reference"]["insightface_runtime_imported"] is False
    assert meta["inhouse_crop_sha256"] == meta["reference_crop_sha256"] == composed["crop_sha256"]

    def array_sha(path: Path) -> str:
        return hashlib.sha256(np.load(path, allow_pickle=False).tobytes()).hexdigest()

    assert array_sha(_COMPOSED_DIR / "inhouse_crop.npy") == composed["crop_sha256"]
    assert array_sha(_COMPOSED_DIR / "reference_crop.npy") == composed["crop_sha256"]
    np.testing.assert_array_equal(
        np.load(_COMPOSED_DIR / "source_image.npy", allow_pickle=False),
        np.load(_FIXTURE_DIR / "aligner_source_image.npy", allow_pickle=False),
    )
    np.testing.assert_array_equal(
        np.load(_COMPOSED_DIR / "landmarks.npy", allow_pickle=False),
        np.load(_FIXTURE_DIR / "aligner_landmarks.npy", allow_pickle=False),
    )

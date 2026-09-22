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

from recognition.infrastructure.face_pipeline.provenance import MODEL_MANIFEST

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "face_pipeline"
_EVIDENCE_PATH = _FIXTURE_DIR / "auraface_alignment_measurement.json"
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
_UNSUPPORTED_FIELDS = ("input_scale", "input_offset", "channel_order", "alignment")


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
    assert evidence["production_unverified_markers_flipped"] is False
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


def test_external_geometry_is_unsupported_without_graph_evidence() -> None:
    evidence = _load_evidence()
    for field_name in _UNSUPPORTED_FIELDS:
        record = evidence[field_name]
        assert record["graph_status"] == "not_in_graph", field_name
        assert record["independently_supported"] is False, field_name
        assert record["value"] is None, field_name
        assert isinstance(record["blocked_reason"], str) and record["blocked_reason"].strip()

    alignment = evidence["alignment"]
    assert alignment["template_id"] is None
    assert alignment["coordinates"] is None


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


def test_documented_contract_is_not_treated_as_measurement() -> None:
    contract = _load_evidence()["upstream_documented_contract"]
    assert contract["status"] == "recorded_not_verified"
    assert contract["independently_supported"] is False
    assert contract["insightface_runtime"]["status"] == "blocked"
    assumption = contract["local_manifest_assumption"]
    assert assumption["status"] == "unverified"
    assert assumption["declared_unverified_alignment_template_id"] == "arcface-112-unverified"
    assert "UNVERIFIED" in assumption["note"]

"""Bounded custody/unknown-state checks; no model, answer or journal access."""
import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

BASE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("dataset_candidates", BASE / "import_candidates.py")
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)
INPUTS = Path(os.environ.get("EVALOPS_DATASET_INPUT_DIR",
                            "/home/gate/workbay-sandbox/evalops3-inputs-20261029"))


@pytest.fixture(scope="module")
def generated():
    return IMPORTER.build(INPUTS)


def test_deterministic_conservation_and_unknowns(generated):
    assert IMPORTER.build(INPUTS) == generated
    records = [json.loads(line) for line in generated["candidates.jsonl"].splitlines()]
    source = IMPORTER.json_file(INPUTS / "agent-errors.json")
    coded = [json.loads(line) for line in
             (BASE.parent / "analysis-v1/open-coded.jsonl").read_text().splitlines()]
    originals = {r["id"]: r for r in source}
    analysis = {r["source_id"]: r for r in coded}
    assert len(records) == len({r["candidate_id"] for r in records}) == 240
    assert sum(r["source"]["occurrence_count"] for r in records) == 400
    assert [r["source"]["source_id"] for r in records] == sorted(originals)
    for record in records:
        sid = record["source"]["source_id"]
        assert record["source"]["task_ref"] == originals[sid]["task_ref"]
        assert record["coding"]["original_open_codes"] == analysis[sid]["open_codes"]
        assert record["source"]["analysis_record_group_id"] == analysis[sid]["record_group_id"]
        assert record["content_sha256"] == IMPORTER.content_hash(record)
        assert record["input"] is record["expected_output_or_rubric"] is None
        assert record["independent_label"] is record["sealed_split"] is None
        assert record["grouping"]["group_id"] is None
        assert record["annotation"]["provenance"]["kind"] == "unknown"
        assert record["exposure"]["system_under_test"] == "unknown"
        assert all(value is None for value in record["execution_pins"].values())
        assert "summary" not in record["source"]  # refs/hashes, no raw restricted text
    report = json.loads(generated["coverage.json"])
    assert report["actual"]["independent_episodes"] is None
    assert report["actual"]["admitted_cases"] == 0
    assert report["actual"]["candidate_strata"] == {"unknown": 240}
    assert report["actual"]["sealed_split_assignments"] == {"train": 0, "dev": 0, "test": 0}
    assert report["actual"]["unknown_task_ref_records"] == 87
    assert all(v["null_records"] == 240 for v in report["missingness"].values())


@pytest.mark.parametrize("mutation", ["duplicate_id", "row_change", "summary_change", "analysis_change"])
def test_source_and_analysis_corruption_is_rejected(monkeypatch, mutation):
    original_loader = IMPORTER.json_file
    original_load = IMPORTER.load

    def corrupt_file(path):
        value = original_loader(path)
        if path.name == "agent-errors.json":
            if mutation == "duplicate_id":
                value[1]["id"] = value[0]["id"]
            elif mutation == "row_change":
                value[0]["occurrence_count"] += 1
            elif mutation == "summary_change":
                value[0]["summary"] = "synthetic tampered value"
        return value

    def corrupt_line(data):
        value = original_load(data)
        if mutation == "analysis_change" and isinstance(value, dict) and "source_row_sha256" in value:
            value["source_row_sha256"] = "0" * 64
        return value

    monkeypatch.setattr(IMPORTER, "json_file", corrupt_file)
    monkeypatch.setattr(IMPORTER, "load", corrupt_line)
    with pytest.raises(ValueError):
        IMPORTER.build(INPUTS)


def test_changed_frozen_file_rejected(tmp_path):
    (tmp_path / "manifest.json").write_bytes((INPUTS / "manifest.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="frozen input hash mismatch"):
        IMPORTER.build(tmp_path)


@pytest.mark.parametrize("field,value", [
    ("sealed_split", "test"), ("independent_label", "not_defect"),
    ("status", "admitted"), ("input", {"ref": "fake", "sha256": "bad", "version": None}),
    ("protocol_sha256", "not-a-hash"),
])
def test_schema_rejects_false_admission_and_malformed_pins(generated, field, value):
    record = json.loads(generated["candidates.jsonl"].splitlines()[0])
    record[field] = value
    validator = Draft202012Validator(IMPORTER.json_file(BASE / "schema.json"))
    assert not validator.is_valid(record)


def test_native_validity_disposition_and_exposure_constraints(generated):
    record = json.loads(generated["candidates.jsonl"].splitlines()[0])
    validator = Draft202012Validator(IMPORTER.json_file(BASE / "schema.json"))
    for kind, exposure, attestation in [
        ("independent_expert", "unknown", "ref"),
        ("independent_expert", "unexposed", None),
        ("post_review", "unexposed", None),
    ]:
        changed = copy.deepcopy(record)
        changed["annotation"]["provenance"].update(
            kind=kind, exposure=exposure, attestation_ref=attestation)
        assert not validator.is_valid(changed)
    # Validity alone never implies blocking; known blocking needs action+reason.
    changed = copy.deepcopy(record)
    changed["annotation"].update(disposition="blocks")
    assert not validator.is_valid(changed)
    changed["annotation"]["disposition"] = "nonblocking"
    assert not validator.is_valid(changed)


def test_check_rejects_invented_split_even_with_rehashed_row(generated, tmp_path):
    for name, value in generated.items():
        (tmp_path / name).write_bytes(value)
    IMPORTER.verify_outputs(generated, tmp_path)
    records = [json.loads(line) for line in generated["candidates.jsonl"].splitlines()]
    records[0]["sealed_split"] = "train"
    records[0]["content_sha256"] = IMPORTER.content_hash(records[0])
    (tmp_path / "candidates.jsonl").write_bytes(
        b"".join(IMPORTER.canonical(r) + b"\n" for r in records))
    with pytest.raises(ValueError, match="candidate artifact differs"):
        IMPORTER.verify_outputs(generated, tmp_path)


def test_duplicate_keys_and_nonfinite_json_rejected():
    for value in [b'{"id":1,"id":2}', b'{"weight":NaN}', b'{"weight":Infinity}']:
        with pytest.raises(ValueError):
            IMPORTER.load(value)

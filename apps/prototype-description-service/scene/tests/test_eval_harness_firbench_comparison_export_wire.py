"""Public writer wire regressions; all report and SQLite inputs are synthetic."""

from __future__ import annotations

import copy
import json

import pytest

from scripts.eval_harness import firbench_comparison_export as export
from scripts.eval_harness import firbench_evidence as evidence
from scene.tests.test_eval_harness_firbench_comparison_export import (
    ARTIFACT_ID,
    MANIFEST_BYTES,
    _bytes,
    _legacy,
    _sha,
    _tree_state,
    _v0_db,
    _write,
    scratch,
)


@pytest.fixture
def wire_case(scratch):
    db = _v0_db(scratch)
    report = _write(scratch, "wire-source.json", _bytes(_legacy()))
    source_sha = "ecf6f55230f3430b1d46e80365c321da253afa23"
    evidence.register_artifact(
        db,
        ARTIFACT_ID,
        kind="report-json",
        path=report,
        source_sha=source_sha,
        manifest_sha256=_sha(MANIFEST_BYTES),
        manifest_hash_kind="raw-sha256",
    )
    db_hash, report_hash = _sha(db.read_bytes()), _sha(report.read_bytes())
    payload = export.export_comparison(db, [ARTIFACT_ID])
    assert payload["sources"][0]["source_sha"] == source_sha
    assert payload["sources"][0]["manifest_sha256"] == _sha(MANIFEST_BYTES)
    assert payload["sources"][0]["file_sha256"] == report_hash
    assert payload["dedup"] == [{"file_sha256": report_hash, "artifact_ids": [ARTIFACT_ID]}]
    assert payload["reports"][0]["file_sha256"] == report_hash
    clustering = payload["reports"][0]["clustering"]
    assert (clustering["algorithm"], clustering["metric"]) == (None, None)
    assert (clustering["p_same"], clustering["p_diff"], clustering["m_co_clustered"]) == (10, 20, 3)
    output = scratch / "exports"
    output.mkdir()
    control = output / "control.json"
    assert export.write_export(payload, control) == control
    assert json.loads(control.read_bytes()) == payload
    assert (_sha(db.read_bytes()), _sha(report.read_bytes())) == (db_hash, report_hash)
    return payload, db, report, output, db_hash, report_hash


@pytest.mark.parametrize("field", ["sources", "dedup", "reports"])
@pytest.mark.parametrize("invalid", ["", {}, ()], ids=["empty-string", "empty-dict", "empty-tuple"])
def test_public_writer_refuses_non_list_collections_without_publication(wire_case, field, invalid):
    payload, db, report, output, db_hash, report_hash = wire_case
    malformed = copy.deepcopy(payload)
    malformed[field] = invalid
    before = _tree_state(output)

    with pytest.raises(export.ComparisonExportError, match="^export payload failed validation$"):
        export.write_export(malformed, output / "refused.json")

    assert _tree_state(output) == before
    assert (_sha(db.read_bytes()), _sha(report.read_bytes())) == (db_hash, report_hash)


@pytest.mark.parametrize("field", ["algorithm", "metric"])
def test_public_writer_requires_explicit_null_clustering_keys(wire_case, field):
    payload, db, report, output, db_hash, report_hash = wire_case
    malformed = copy.deepcopy(payload)
    del malformed["reports"][0]["clustering"][field]
    before = _tree_state(output)

    with pytest.raises(export.ComparisonExportError, match="^export payload failed validation$"):
        export.write_export(malformed, output / "refused.json")

    assert _tree_state(output) == before
    assert (_sha(db.read_bytes()), _sha(report.read_bytes())) == (db_hash, report_hash)


def test_public_writer_refuses_extra_clustering_key(wire_case):
    payload, db, report, output, db_hash, report_hash = wire_case
    malformed = copy.deepcopy(payload)
    malformed["reports"][0]["clustering"]["extra"] = None
    before = _tree_state(output)

    with pytest.raises(export.ComparisonExportError, match="^export payload failed validation$"):
        export.write_export(malformed, output / "refused.json")

    assert _tree_state(output) == before
    assert (_sha(db.read_bytes()), _sha(report.read_bytes())) == (db_hash, report_hash)


@pytest.mark.parametrize("empty", [False, True], ids=["normal", "empty-lists"])
def test_public_writer_publishes_valid_wire_payload(wire_case, empty):
    payload, db, report, output, db_hash, report_hash = wire_case
    valid = copy.deepcopy(payload)
    if empty:
        for field in ("sources", "dedup", "reports"):
            valid[field] = []
    out = output / "valid.json"

    assert export.write_export(valid, out) == out

    assert json.loads(out.read_bytes()) == valid
    assert sorted(path.name for path in output.iterdir()) == ["control.json", "valid.json"]
    assert (_sha(db.read_bytes()), _sha(report.read_bytes())) == (db_hash, report_hash)

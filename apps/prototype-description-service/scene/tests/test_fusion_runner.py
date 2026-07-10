"""E20-FUSION Slice 4: fusion_runner emits acx-eval/v1 records; deterministic re-score."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness.fusion_runner import (
    build_typed_context_pack,
    main as fusion_main,
    manifest_entries_as_dicts,
    run_fusion_eval,
    score_misattachments,
)
from scripts.eval_harness.manifest import load_manifest
from scripts.eval_harness.report import build_reports
from scripts.eval_harness.schema import SCHEMA, DocKind

BAKEOFF = Path(__file__).parent / "seed" / "bakeoff_golden.json"


@pytest.fixture(scope="module")
def manifest():
    return load_manifest(str(BAKEOFF))


def test_bakeoff_labels_include_expected_attachments(manifest):
    assert any(e.expected_attachments for e in manifest.entries)
    plane = next(e for e in manifest.entries if e.path.endswith("mcm-planecrash.jpg"))
    by_src = {a.fact_source: a for a in plane.expected_attachments}
    assert by_src["identity"].decision == "dropped"
    assert by_src["identity"].review_reason == "face_not_detected"
    assert by_src["event"].decision == "caption"
    assert by_src["event"].visible is False
    assert by_src["place"].altitude == "caption"


def test_staged_run_record_is_acx_eval_v1(manifest):
    record = run_fusion_eval(
        manifest, mode="staged", head_sha="a" * 40, started_at="2026-07-09T00:00:00Z"
    )
    assert record["schema"] == SCHEMA
    assert record["kind"] == DocKind.RUN_RECORD.value
    assert record["provenance"]["fusion_mode"] == "staged"
    assert len(record["items"]) == len(manifest.entries)
    assert all(item.get("error") is None for item in record["items"])
    for item in record["items"]:
        describe = item["describe"]
        assert "alt_text_draft" in describe
        assert "attachment_provenance" in describe


def test_build_reports_deterministic_on_fusion_records(manifest):
    record = run_fusion_eval(
        manifest, mode="staged", head_sha="b" * 40, started_at="2026-07-09T12:00:00Z"
    )
    entries = manifest_entries_as_dicts(manifest)
    json_a, md_a = build_reports(record, entries)
    json_b, md_b = build_reports(record, entries)
    assert json_a == json_b
    assert md_a == md_b
    parsed = json.loads(json_a)
    assert parsed["schema"] == SCHEMA
    assert parsed["kind"] == DocKind.REPORT.value
    assert parsed["counts"]["failed"] == 0


def test_staged_zero_misattachments_on_labeled_corpus(manifest):
    record = run_fusion_eval(
        manifest, mode="staged", head_sha="c" * 40, started_at="2026-07-09T00:00:00Z"
    )
    mis = score_misattachments(record, manifest)
    assert mis["labeled_facts"] >= 10
    assert mis["misattachments"] == 0, mis["hits"]


def test_adhoc_has_more_misattachments_than_staged(manifest):
    staged = run_fusion_eval(
        manifest, mode="staged", head_sha="d" * 40, started_at="2026-07-09T00:00:00Z"
    )
    adhoc = run_fusion_eval(
        manifest, mode="adhoc", head_sha="d" * 40, started_at="2026-07-09T00:00:00Z"
    )
    s_mis = score_misattachments(staged, manifest)["misattachments"]
    a_mis = score_misattachments(adhoc, manifest)["misattachments"]
    assert a_mis > s_mis
    assert s_mis == 0


def test_mcm_planecrash_success_criterion(manifest):
    """Unconfirmed face not object-attached + garden picnic caption-level non-visible."""
    record = run_fusion_eval(
        manifest, mode="staged", head_sha="e" * 40, started_at="2026-07-09T00:00:00Z"
    )
    item = next(i for i in record["items"] if i["path"].endswith("mcm-planecrash.jpg"))
    facts = {f["fact_id"]: f for f in item["describe"]["attachment_provenance"]["facts"]}
    identity = facts["identity:cluster:cluster-maria-correonero"]
    assert identity["decision"] == "dropped"
    assert identity["altitude"] == "none"
    assert identity["visible"] is False
    assert identity["review_reason"] == "face_not_detected"

    event = facts["event:garden-picnic"]
    assert event["decision"] == "caption"
    assert event["altitude"] == "caption"
    assert event["visible"] is False
    assert event["fact_source"] == "event"

    place = facts["place:summer-garden"]
    assert place["decision"] == "caption"
    assert place["visible"] is False


def test_degrade_missing_labels_and_empty_context(manifest):
    """Degrade paths: empty ContextPack / no expected labels → empty provenance."""
    empty = next(e for e in manifest.entries if e.path.endswith("nina-machiavelli.jpeg"))
    assert empty.expected_attachments == []
    assert build_typed_context_pack(empty) is None

    record = run_fusion_eval(
        manifest, mode="staged", head_sha="f" * 40, started_at="2026-07-09T00:00:00Z", limit=None
    )
    item = next(i for i in record["items"] if i["path"] == empty.path)
    assert item["error"] is None
    assert item["describe"]["attachment_provenance"]["facts"] == []


def test_policy_disabled_pool_yields_no_typed_pack(manifest):
    pool = next(e for e in manifest.entries if e.path.endswith("maria-pool.jpg"))
    assert pool.policy.recognition_enabled is False
    assert build_typed_context_pack(pool) is None


def test_cli_writes_reports(tmp_path, manifest):
    code = fusion_main(
        [
            "--manifest",
            str(BAKEOFF),
            "--mode",
            "both",
            "--out-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    for mode in ("staged", "adhoc"):
        assert (tmp_path / f"E20-FUSION-{mode}-run-record.json").is_file()
        assert (tmp_path / f"E20-FUSION-{mode}-report.json").is_file()
        assert (tmp_path / f"E20-FUSION-{mode}-report.md").is_file()
        assert (tmp_path / f"E20-FUSION-{mode}-misattachment.json").is_file()
    staged_mis = json.loads((tmp_path / "E20-FUSION-staged-misattachment.json").read_text())
    adhoc_mis = json.loads((tmp_path / "E20-FUSION-adhoc-misattachment.json").read_text())
    assert staged_mis["misattachments"] == 0
    assert adhoc_mis["misattachments"] > 0

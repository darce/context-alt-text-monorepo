"""Public synthetic numeric-null semantics through the actual producer and renderer.

The retained typed fixture supplies nonnull clustering with parameters.d_cut.
Native SQLite registration/composition remains a separate final validation gate.
No task-state files or private inputs are read by these tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scene.tests.test_eval_harness_firbench_explorer_presentation import _Page
from scene.tests.test_eval_harness_firbench_explorer_wire import _legacy_bytes
from scripts.eval_harness.firbench_comparison_export import summarize_legacy_report, write_export
from scripts.eval_harness.firbench_explorer import render_explorer


def _project(state: str) -> dict:
    source = json.loads(_legacy_bytes())
    block = source["slices"]["unknown_rejection"]
    if state == "refused":
        # These recorded source numbers must be suppressed by the real _live projection.
        block.update(refused=True, status="refused", directional=True,
                     sampling_frame="public-synthetic-frame", reasons=["public-synthetic-reason"])
    elif state == "absent":
        del source["slices"]["unknown_rejection"]
    elif state == "zero":
        block.update(correct_rejects=0, false_accepts=0, n=0, rate=0,
                     rate_numerator=0, rate_denominator=0)
    elif state == "sparse":
        source["slices"]["unknown_rejection"] = {"correct_rejects": 7}
    else:
        assert state == "nonnull"
    return summarize_legacy_report(json.dumps(source).encode("ascii"), artifact_id=f"public-null-{state}")


def _render(tmp_path: Path, report: dict):
    artifact_id, digest = report["artifact_id"], report["file_sha256"]
    payload = {
        "schema": "firbench/comparison-explorer-export-v1", "schema_version": 1,
        "sources": [{"artifact_id": artifact_id, "file_sha256": digest, "kind": "report-json",
                     "qualification": "unqualified", "source_sha": None, "manifest_sha256": None,
                     "manifest_hash_kind": None}],
        "reports": [report],
        "dedup": [{"file_sha256": digest, "artifact_ids": [artifact_id]}],
    }
    assert set(payload) == {"schema", "schema_version", "sources", "reports", "dedup"}
    assert report["clustering"]["parameters"] == {"d_cut": 0.6}
    assert "d_cut" not in report["clustering"]
    data = write_export(payload, tmp_path / "comparison.json")
    before = data.read_bytes()
    page = _Page(render_explorer(data, tmp_path / "explorer").read_text(encoding="utf-8")).root
    assert data.read_bytes() == before
    return page


def _cell(page, metric: str):
    return page.find("tr", **{"data-metric": metric}).find("span", **{"data-pipeline": "sface"})


def test_actual_producer_loses_absent_vs_refused_numeric_source_status() -> None:
    absent, refused = _project("absent"), _project("refused")
    assert absent["unknown_rejection"] == refused["unknown_rejection"]
    assert all(value is None for value in refused["unknown_rejection"].values())
    # Section names can differ, but no per-section refusal/status/reason survives.
    assert "unknown_rejection" not in absent["slice_sections"]
    assert "unknown_rejection" in refused["slice_sections"]
    assert set(refused["unknown_rejection"]) == {
        "correct_rejects", "false_accepts", "n", "n_floor", "rate", "rate_numerator", "rate_denominator",
    }


@pytest.mark.parametrize("state", ["refused", "absent"])
def test_numeric_null_does_not_claim_original_source_absence(tmp_path: Path, state: str) -> None:
    page = _render(tmp_path, _project(state))
    cell = _cell(page, "strangers-rejected")
    assert cell.text.strip().lower().startswith("unavailable in this export"), (
        "numeric null must say unavailable in this export; original source absence/refusal is not exported"
    )
    assert not any(char.isdigit() for char in cell.text)
    definition = page.find("article", id="term-not-recorded").find("p").text.lower()
    caption = page.find("caption").text.lower()
    for description in (definition, caption):
        assert "source status is not exported" in description
        assert "original source may omit or refuse" in description
        assert "the file does not contain" not in description
    assert "not recorded in this export" in caption
    assert "zero" in definition
    # Metadata absence is a distinct exported-field fact and retains its labels.
    assert "not recorded" in page.find("table", **{"class": "source-table"}).text.lower()
    assert _cell(page, "images-failed").text.strip() == "0"
    assert _cell(page, "images-scored").text.split()[0] == "150"


@pytest.mark.parametrize("state, expected, rate", [
    ("zero", "0 of 0", "rate 0.0%"),
    ("nonnull", "80 of 89", "rate 90.0%"),
    ("sparse", "7", "rate not recorded"),
])
def test_recorded_zero_nonnull_and_sparse_counts_survive(tmp_path: Path, state: str, expected: str, rate: str) -> None:
    report = _project(state)
    page = _render(tmp_path, report)
    text = " ".join(_cell(page, "strangers-rejected").text.split())
    assert text.startswith(expected)
    assert rate in text
    assert "unavailable in this export" not in text
    if state == "sparse":
        assert report["unknown_rejection"]["n"] is None
        assert report["unknown_rejection"]["rate"] is None
        assert "denominator not recorded" in text
        assert "0%" not in text and "None" not in text

"""Reported-waterfall summaries: software specimens, never full-inventory claims.

Canon v0.26.2 INT-22 and VIZ-23: name the result, its pool and source evidence.
"""

from __future__ import annotations

import copy
import csv
import html
import json
import re
from types import SimpleNamespace

import pytest

from scene.tests import test_eval_harness_firbench_cli_integration as native
from scene.tests.test_eval_harness_firbench_cli_report_integration import _run_and_score
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_report as report


SFACE = "sface__native__fake__cv4__ort1"
FUSED = "insightface__native__fake__cv4__ort1"


@pytest.fixture
def native_files(tmp_path, monkeypatch):
    # Reuse only the actual fixture's fake kernels/assets and settings. Restore
    # its git-head seam so the persisted manifest uses this checkout's real SHA.
    head_sha = cli._head_sha
    request = SimpleNamespace(node=SimpleNamespace(name="test_default_run_and_actual_score"))
    source = native.runtime_files.__wrapped__(tmp_path, monkeypatch, request)
    files = next(source)
    monkeypatch.setattr(cli, "_head_sha", head_sha)
    try:
        yield files
    finally:
        source.close()


def _scores(counts, *, leg=SFACE):
    # The actual S3 wire is sparse: one row per observed SearchStage, native
    # test-fold mated records only, challenge under a separate leg label.
    return {
        "legs": [{"leg_key": leg}],
        "waterfall": [
            {"leg_key": leg, "arm": "native", "stage": stage, "count": count}
            for stage, count in counts
        ],
        "joint_gaps": [],
    }


def _summary(scores):
    text = report._stages_html(scores)
    return text.split("<table", 1)[0]


@pytest.mark.parametrize("counts,expected", [
    ([("missed", 5), ("detected", 2), ("unaligned", 1), ("embedded", 20)],
     "Dominant reported upstream stage: missed (5 of 8 reported upstream failures)"),
    ([("detected", 4), ("embedded", 2)],
     "Dominant reported upstream stage: detected (4 of 4 reported upstream failures)"),
    ([("unaligned", 4), ("embedded", 2)],
     "Dominant reported upstream stage: unaligned (4 of 4 reported upstream failures)"),
    ([("unaligned", 3), ("missed", 3), ("detected", 1), ("embedded", 20)],
     "Tied dominant reported upstream stages: missed, unaligned (3 each of 7 reported upstream failures)"),
    ([("embedded", 9)], "No reported upstream failure among these reported rows; all 9 records reached embedded"),
    ([("missed", 0), ("detected", 0), ("unaligned", 0), ("embedded", 9)],
     "No reported upstream failure among these reported rows; all 9 records reached embedded"),
    ([], "Unavailable: no positive-count reported waterfall evidence"),
    ([("embedded", 0)], "Unavailable: no positive-count reported waterfall evidence"),
    ([("missed", 0), ("detected", 0), ("unaligned", 0)],
     "Unavailable: no positive-count reported waterfall evidence"),
])
def test_reported_stage_states(counts, expected):
    scores = _scores(counts)
    before = copy.deepcopy(scores)
    summary = html.unescape(_summary(scores))
    assert expected in summary
    assert SFACE in summary and "native" in summary
    assert "reported waterfall records" in summary
    assert "accepted or correct identity" in summary
    assert "full GT inventory" in summary
    assert scores == before
    for index in range(len(counts)):
        assert f'scores.json#/waterfall/{index}' in summary


def test_missing_waterfall_is_unavailable():
    scores = _scores([])
    del scores["waterfall"]
    assert "Unavailable: no positive-count reported waterfall evidence" in _summary(scores)


def test_leg_arm_and_challenge_scopes_do_not_pool_or_use_outcomes():
    scores = _scores([("missed", 2), ("embedded", 8)])
    challenge = SFACE + "::sampling=challenge"
    scores["waterfall"] += [
        {"leg_key": challenge, "arm": "native", "stage": "detected", "count": 11},
        {"leg_key": SFACE, "arm": "gt_crop_redetect", "stage": "unaligned", "count": 7},
    ]
    scores["legs"].append({"leg_key": FUSED})  # declared native, no evidence
    scores["face_outcomes"] = [{"outcome": "wrong_identity"}] * 50
    summary = html.unescape(_summary(scores))
    assert "missed (2 of 2 reported upstream failures)" in summary
    assert "detected (11 of 11 reported upstream failures)" in summary
    assert "unaligned (7 of 7 reported upstream failures)" in summary
    assert challenge in summary and "gt_crop_redetect" in summary
    assert "Unavailable: no positive-count reported waterfall evidence" in summary
    assert "Count pool: 10 reported waterfall records" in summary
    assert "Count pool: 11 reported waterfall records" in summary
    assert "Count pool: 7 reported waterfall records" in summary
    assert "wrong_identity" not in summary


def test_fused_availability_stays_separate_and_ledger_paths_are_preserved():
    scores = _scores([("detected", 2), ("embedded", 7)], leg=FUSED)
    scores["joint_gaps"] = [{
        "leg_key": FUSED, "arm": "gt_crop_redetect", "scored": False,
        "reason": "attribution_arm_not_run", "n_pairs": 0, "delta": None, "interval": None,
        "unavailable_counts": {"native": 0, "attribution": 270},
    }]
    summary = _summary(scores)
    assert "detected (2 of 2 reported upstream failures)" in summary
    assert "270" not in summary and "unaligned (" not in summary
    text = report._stages_html(scores)
    assert "attribution unavailable: 270; native unavailable: 0" in text
    assert 'data-source="scores.json#/joint_gaps/0"' in text
    # Keep the waterfall as the first table: its existing CSV alias depends on it.
    tables, _ = report._binding_table_exports([("stages", text)])
    rows = list(csv.DictReader(tables["table-stages-01.csv"].splitlines()))
    assert [row["Stage"] for row in rows] == ["detected", "embedded"]
    assert [row["Count"] for row in rows] == ["2", "7"]
    scores["waterfall"].append({"leg_key": FUSED, "arm": "native", "stage": "unaligned", "count": 1})
    with pytest.raises(fc.FrameContractError, match="writes no unaligned stage"):
        report._stages_html(scores)


def test_actual_producer_render_keeps_reported_pool_and_frozen_sources(native_files):
    directory = _run_and_score(native_files)
    before = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    scores = json.loads(before[directory / "scores.json"])
    frame = json.loads(before[directory / "frame.json"])
    manifest = json.loads(before[directory / "manifest.json"])
    assert manifest["firbench"]["head_sha"] == cli._head_sha(native_files.repo)
    assert len(scores["face_outcomes"]) == 270
    assert len(scores["waterfall"]) == 3
    assert sum(row["count"] for row in scores["waterfall"]) == 9
    report.render_report(directory, out_dir=directory / "report")
    assert {p: p.read_bytes() for p in before} == before
    page = (directory / "report/index.html").read_text()
    section = re.search(r'<section\b[^>]*id="stages".*?</section>', page, re.S).group()
    summary = html.unescape(section.split("<table", 1)[0])
    for leg in scores["legs"]:
        rows = [r for r in scores["waterfall"] if r["leg_key"] == leg["leg_key"]]
        count = sum(r["count"] for r in rows)
        assert all(r["stage"] == "embedded" and r["arm"] == "native" for r in rows)
        assert f"all {count} records reached embedded" in summary
        assert count < len(frame["faces"])
    assert "full GT inventory" in summary
    with (directory / "report/waterfall.csv").open() as handle:
        ledger = list(csv.DictReader(handle))
    assert len(ledger) == len(scores["waterfall"])
    result = json.loads((directory / "report/report.json").read_bytes())
    assert result["verdict"] == scores["verdict"]
    assert len(result["failures"]["rows"]) == 270
    frozen = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    report.render_report(directory, out_dir=directory / "report")
    assert {p: p.read_bytes() for p in frozen} == frozen

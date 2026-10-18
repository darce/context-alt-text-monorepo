"""Review 1296, RV-EVAL-QUERY-01: earlier refusals must retire both reports.

TEST-15, Prove the green can go red (The Pragmatic Programmer, ch. 9):
healthy score -> earlier refusal -> nonnumerical reports -> healthy recovery.
These causal regressions intentionally leave production and existing tests alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.bench.export_map import export_leg, load_leg_exports
from scripts.bench.score_report import compute_accepted_set, score_head_to_head
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.test_gtmr_refused_rescore import _assert_healthy, _refresh_query
from scripts.bench.tests.test_gtmr_unknown_query import MEDIA_IDS, TARGET, _run
from scripts.bench.tests.test_score_head_to_head import A_STACK, B_STACK, _pred, _write_leg

STACKS = (A_STACK, B_STACK)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_retired(run_dir: Path, code: str, healthy_frames: dict, healthy_html: str) -> None:
    # Evaluate both artifacts before asserting, so a stale JSON report cannot
    # mask stale HTML (or a missing publication). This executes as soon as the
    # original scorer exception reaches the caller, before recovery writes.
    failures = []
    score = run_dir / "score"
    frames_path = score / "frames.json"
    if not frames_path.is_file():
        failures.append("frames.json refusal missing")
    else:
        frames = _json(frames_path)
        if not (
            frames.get("pr_cells_emitted") is False
            and frames.get("cells") == []
            and frames.get("error_code") == code
        ):
            failures.append("frames.json retains numerical cells or lacks original refusal code")
    html_path = score / "report.html"
    if not html_path.is_file():
        failures.append("report.html refusal missing")
    else:
        html = html_path.read_text(encoding="utf-8")
        metric_names = {cell["cell"] for cell in healthy_frames["cells"]}
        numeric_rows = [
            row for row in re.findall(r"<tr\b[^>]*>.*?</tr>", html, re.I | re.S)
            if any(name in row for name in metric_names)
            and re.search(r"<td\b[^>]*>\s*[+-]?\d+(?:\.\d+)?\s*</td>", row, re.I)
        ]
        if html == healthy_html or "refus" not in html.lower() or numeric_rows:
            failures.append("report.html retains numerical metrics or lacks refusal output")
    assert not failures, "; ".join(failures)


def _recover(run_dir: Path, healthy_frames: dict, preflights: dict[str, bytes]) -> None:
    for stack in STACKS:
        _write_leg(run_dir, stack, [_pred(mid) for mid in MEDIA_IDS], MEDIA_IDS)
        assert (run_dir / "legs" / stack / "preflight.json").read_bytes() == preflights[stack]
    recovered, _ = _assert_healthy(run_dir)
    # Preserve every valid population cell, including native-frame metrics,
    # rather than checking only the selected recall endpoints.
    assert recovered["cells"] == healthy_frames["cells"]


@pytest.mark.parametrize("stack", STACKS)
@pytest.mark.parametrize("state", ["failed_query", "unqueried"])
@pytest.mark.parametrize(
    ("gate", "code"),
    [
        ("preflight", "preflight_invalid"),
        ("cluster", "cluster_gate_refused"),
        ("attrition", "differential_attrition_exceeded"),
    ],
)
def test_earlier_refusal_retires_both_reports_and_recovers(
    tmp_path: Path, stack: str, state: str, gate: str, code: str
) -> None:
    run_dir = _run(tmp_path, (), "successful_empty")
    # A ten-item fixture needs a stricter skew bound for one terminal failure
    # to trigger this independent gate; set it before the healthy baseline.
    pair_path = run_dir / "stack_pair.json"
    if gate == "attrition":
        pair = _json(pair_path)
        pair["max_differential_attrition"] = 0.05
        pair_path.write_text(json.dumps(pair), encoding="utf-8")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    preflights = {
        s: (run_dir / "legs" / s / "preflight.json").read_bytes() for s in STACKS
    }
    lineage = {name: (run_dir / name).read_bytes() for name in ("manifest.json", "stack_pair.json")}
    try:
        _refresh_query(run_dir, stack, state)  # Digest-valid unknown observation.
        opposite = next(s for s in STACKS if s != stack)
        if gate == "preflight":
            (run_dir / "legs" / opposite / "preflight.json").write_text("{}", encoding="utf-8")
        elif gate == "cluster":
            (run_dir / "legs" / opposite / "cluster_job.json").write_text(
                json.dumps({"status": "failed"}), encoding="utf-8"
            )
        else:
            # A terminal analyze failure has no corresponding identity row.
            # Reuse the fixture writer so raw identities, membership and
            # digests stay consistent instead of tripping the roster guard.
            _write_leg(run_dir, opposite, [_pred(mid) for mid in MEDIA_IDS if mid != TARGET], MEDIA_IDS)
            items_path = run_dir / "legs" / opposite / "items.jsonl"
            records = [json.loads(line) for line in items_path.read_text().splitlines()]
            analyze = next(
                row for row in records
                if row["manifest_media_id"] == TARGET and row["phase"] == "analyze"
            )
            analyze.update(stack_media_id=None, outcome="failed", attempt=2, error_code="analyze_failed")
            items_path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")

        accepted = compute_accepted_set(run_dir)
        assert accepted.accepted_set_size == accepted.resolved_floor_count == 9
        assert TARGET not in accepted.manifest_media_ids
        assert accepted.attrition_failures_by_media[TARGET][stack] == ["identity_query"]
        assert accepted.attrition_failures_by_media[TARGET][opposite] == (
            ["analyze"] if gate == "attrition" else []
        )
        assert accepted.attrition_join == int(gate != "attrition")
        assert accepted.attrition_ingest_analyze == int(gate == "attrition")
        assert accepted.zero_detection_media_count == 0

        with pytest.raises(BenchError) as refusal:
            score_head_to_head(run_dir)
        assert type(refusal.value) is BenchError
        assert refusal.value.code == code  # Earlier gate wins over query refusal.
        diagnostic = _json(run_dir / "score" / "accepted_set.json")
        attrition = _json(run_dir / "score" / "attrition.json")
        assert diagnostic["accepted_set_size"] == 9
        assert diagnostic["manifest_media_ids"] == accepted.manifest_media_ids
        assert attrition["attrition_join"] == accepted.attrition_join
        assert attrition["attrition_ingest_analyze"] == accepted.attrition_ingest_analyze
        assert attrition["missing"] == [{
            "manifest_media_id": TARGET,
            "phase": "analyze" if gate == "attrition" else "join",
            "failed_conditions_by_stack": accepted.attrition_failures_by_media[TARGET],
        }]
        _assert_retired(run_dir, code, healthy_frames, healthy_html)
    finally:
        _recover(run_dir, healthy_frames, preflights)
        for name, payload in lineage.items():
            assert (run_dir / name).read_bytes() == payload


@pytest.mark.parametrize("stack", STACKS)
def test_real_partial_export_digest_refusal_retires_both_reports_and_recovers(
    tmp_path: Path, stack: str
) -> None:
    run_dir = _run(tmp_path, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    preflights = {
        s: (run_dir / "legs" / s / "preflight.json").read_bytes() for s in STACKS
    }
    exports = run_dir / "legs" / stack / "exports"
    preserved = {
        path.name: path.read_bytes() for path in exports.iterdir()
        if path.name != "media_identity_results.json"
    }
    # compute_accepted_set fails before publishing fresh diagnostics here.
    diagnostics = {
        name: (run_dir / "score" / name).read_bytes()
        for name in ("accepted_set.json", "attrition.json")
    }
    upstream_error = RuntimeError("batch identity query failed")
    queried = []

    class FailedQueryClient:
        def media_identities(self, media_ids: list[int]) -> None:
            queried.append(list(media_ids))
            raise upstream_error

    try:
        with pytest.raises(RuntimeError) as query_failure:
            export_leg(FailedQueryClient(), run_dir, stack)
        assert query_failure.value is upstream_error
        assert queried == [MEDIA_IDS]
        results_path = exports / "media_identity_results.json"
        assert json.loads(results_path.read_text()) == [
            {"media_id": mid, "query_succeeded": False, "rows": []} for mid in MEDIA_IDS
        ]
        for name, payload in preserved.items():
            assert (exports / name).read_bytes() == payload
        assert hashlib.sha256(results_path.read_bytes()).hexdigest() != _json(
            exports / "export_sha256.json"
        )[results_path.name]
        with pytest.raises(BenchError) as digest_failure:
            load_leg_exports(run_dir, stack)
        assert digest_failure.value.code == "export_digest_mismatch"
        with pytest.raises(BenchError) as refusal:
            score_head_to_head(run_dir)
        assert type(refusal.value) is BenchError
        assert refusal.value.code == "export_digest_mismatch"
        assert results_path.name in str(refusal.value)
        for name, payload in diagnostics.items():
            assert (run_dir / "score" / name).read_bytes() == payload
        _assert_retired(run_dir, refusal.value.code, healthy_frames, healthy_html)
    finally:
        _recover(run_dir, healthy_frames, preflights)

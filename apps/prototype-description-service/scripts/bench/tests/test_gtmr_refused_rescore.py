"""RV-EVAL-QUERY-01: refused rescoring must retire prior numerical reports.

Exercise healthy -> digest-valid unknown query -> refusal -> healthy recovery
in the same run directory, without changing the scorer or scoring population.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from scripts.bench.export_map import load_leg_exports
from scripts.bench.score_report import compute_accepted_set, score_head_to_head
from scripts.bench.stack_pair import BenchError
from scripts.bench.tests.test_gtmr_unknown_query import (
    AFFECTED,
    E2E_RECALL,
    MEDIA_IDS,
    TARGET,
    _run,
)
from scripts.bench.tests.test_score_head_to_head import (
    A_STACK,
    B_STACK,
    _cells,
    _pred,
    _write_leg,
)


def _refresh_query(run_dir: Path, stack: str, state: str) -> None:
    # Regenerate consistent flat identities, cluster membership and per-media
    # observations first; successful analyze/ingest receipts remain intact.
    _write_leg(run_dir, stack, [_pred(mid) for mid in MEDIA_IDS if mid != TARGET], MEDIA_IDS)
    exports = run_dir / "legs" / stack / "exports"
    results_path = exports / "media_identity_results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    target = next(row for row in results if row["media_id"] == TARGET)
    assert target == {"media_id": TARGET, "query_succeeded": True, "rows": []}
    if state == "failed_query":
        target["query_succeeded"] = False
    else:
        assert state == "unqueried"
        results.remove(target)
    results_path.write_text(json.dumps(results), encoding="utf-8")
    digest_path = exports / "export_sha256.json"
    digests = json.loads(digest_path.read_text(encoding="utf-8"))
    digests[results_path.name] = hashlib.sha256(results_path.read_bytes()).hexdigest()
    digest_path.write_text(json.dumps(digests), encoding="utf-8")
    load_leg_exports(run_dir, stack)


def _assert_healthy(run_dir: Path) -> tuple[dict, str]:
    for stack in (A_STACK, B_STACK):
        load_leg_exports(run_dir, stack)
    score_head_to_head(run_dir)
    score = run_dir / "score"
    frames = json.loads((score / "frames.json").read_text(encoding="utf-8"))
    html = (score / "report.html").read_text(encoding="utf-8")
    assert frames["pr_cells_emitted"] is True
    assert frames["accepted_set_size"] == len(MEDIA_IDS)
    for endpoint in E2E_RECALL:
        cells = _cells(run_dir, endpoint)
        assert {cell["stack_id"] for cell in cells} == {A_STACK, B_STACK}
        for cell in cells:
            assert not cell.get("refused", False)
            assert cell["value"] == 1.0
            assert cell["true_positives"] == len(MEDIA_IDS)
            assert cell["false_positives"] == cell["false_negatives"] == 0
        assert endpoint in html
    assert "<td>1.0</td>" in html
    accepted = json.loads((score / "accepted_set.json").read_text(encoding="utf-8"))
    attrition = json.loads((score / "attrition.json").read_text(encoding="utf-8"))
    assert accepted["accepted_set_size"] == len(MEDIA_IDS)
    assert attrition["missing"] == []
    assert attrition["attrition_join"] == attrition["attrition_ingest_analyze"] == 0
    return frames, html


@pytest.mark.parametrize("affected", AFFECTED, ids=["one_leg", "both_legs"])
@pytest.mark.parametrize("state", ["failed_query", "unqueried"])
def test_refused_rescore_retires_numerical_artifacts_and_recovers(
    tmp_path: Path, affected: tuple[str, ...], state: str
) -> None:
    run_dir = _run(tmp_path, (), "successful_empty")
    healthy_frames, healthy_html = _assert_healthy(run_dir)
    for stack in affected:
        _refresh_query(run_dir, stack, state)

    accepted = compute_accepted_set(run_dir)
    assert accepted.accepted_set_size == accepted.resolved_floor_count == 9
    assert TARGET not in accepted.manifest_media_ids
    assert accepted.attrition_join == 1
    assert accepted.attrition_ingest_analyze == accepted.zero_detection_media_count == 0
    for stack in affected:
        assert TARGET in accepted.join_by_stack[stack]
        assert accepted.attrition_failures_by_media[TARGET][stack] == ["identity_query"]

    with pytest.raises(BenchError) as refusal:
        score_head_to_head(run_dir)
    assert refusal.value.code == "identity_query_unknown"
    assert "query" in str(refusal.value).lower()

    score = run_dir / "score"
    diagnostic = json.loads((score / "accepted_set.json").read_text(encoding="utf-8"))
    attrition = json.loads((score / "attrition.json").read_text(encoding="utf-8"))
    assert diagnostic["accepted_set_size"] == 9
    assert diagnostic["manifest_media_ids"] == accepted.manifest_media_ids
    assert attrition["attrition_join"] == 1
    assert attrition["attrition_ingest_analyze"] == 0
    assert attrition["missing"] == [{
        "manifest_media_id": TARGET,
        "phase": "join",
        "failed_conditions_by_stack": {
            stack: ["identity_query"] if stack in affected else []
            for stack in (A_STACK, B_STACK)
        },
    }]

    # Collect both artifact failures before recovery so the current bug proves
    # JSON and HTML exposure, and the recovery path executes even on RED.
    stale = []
    frames_path = score / "frames.json"
    if frames_path.exists():
        refused_frames = json.loads(frames_path.read_text(encoding="utf-8"))
        if not (
            refused_frames.get("pr_cells_emitted") is False
            and refused_frames.get("cells") == []
            and refused_frames.get("error_code") == refusal.value.code
        ):
            stale.append("frames.json retains numerical cells instead of a current refusal header")
    html_path = score / "report.html"
    if html_path.exists():
        refused_html = html_path.read_text(encoding="utf-8")
        metric_names = {cell["cell"] for cell in healthy_frames["cells"]}
        numeric_metric_rows = [
            row for row in re.findall(r"<tr\b[^>]*>.*?</tr>", refused_html, re.I | re.S)
            if any(name in row for name in metric_names)
            and re.search(r"<td\b[^>]*>\s*[+-]?\d+(?:\.\d+)?\s*</td>", row, re.I)
        ]
        if (
            refused_html == healthy_html
            or "refus" not in refused_html.lower()
            or "query" not in refused_html.lower()
            or numeric_metric_rows
        ):
            stale.append("report.html retains numerical metrics instead of current query refusal output")

    for stack in affected:
        _write_leg(run_dir, stack, [_pred(mid) for mid in MEDIA_IDS], MEDIA_IDS)
    _assert_healthy(run_dir)
    assert not stale, "; ".join(stale)

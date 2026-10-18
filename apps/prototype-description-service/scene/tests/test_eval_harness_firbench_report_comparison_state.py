"""S6 displays recorded input comparability separately from contrast scoring."""

import copy
import html
import json
import subprocess
from pathlib import Path

import pytest

from scene.tests import test_eval_harness_firbench_cli_integration as native
from scene.tests.test_eval_harness_firbench_cli_integration import runtime_files
from scripts.eval_harness import firbench_cli as cli
from scripts.eval_harness import firbench_contract as fc
from scripts.eval_harness import firbench_report as report


FIXTURE = Path(__file__).parent / "fixtures/firbench_interchange_v1/comparison-v1.json"
_REAL_HEAD_SHA = cli._head_sha


def assert_state(content, state):
    glyph = {"comparable": "↔", "exploratory": "△"}[state]
    assert f'Input comparability:</strong> <span class="st">{glyph} {state}</span>' in content
    assert 'data-source="comparison.json#/comparison_state"' in content
    assert "Input compatibility does not establish inferential scoring eligibility" in content
    assert "recorded per-leg status and reason below" in content
    assert "Descriptive contrasts only; no posthoc winner." in content


@pytest.mark.parametrize(
    "state,treatment,primary",
    [
        ("comparable", None, {}),
        ("comparable", "fpir_target", {"fpir_target": 0.05}),
        ("exploratory", "arm", {"fpir_target": 0.05, "estimand": "alternative estimand"}),
    ],
)
def test_actual_cli_comparison_state_is_independent_of_unscored_contrasts(
    runtime_files, monkeypatch, state, treatment, primary
):
    files = runtime_files
    # Replace the existing asset fixture's HEAD stub with actual Git resolution.
    # This isolated input repository needs no remote, transfer or staged assets.
    monkeypatch.setattr(cli, "_head_sha", _REAL_HEAD_SHA)
    subprocess.run(["git", "-C", str(files.repo), "init", "-q"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(files.repo), "-c", "user.name=FIRBENCH fixture",
         "-c", "user.email=firbench@example.invalid", "-c", "commit.gpgsign=false",
         "commit", "--allow-empty", "-qm", "Initialize isolated comparison inputs"],
        check=True, capture_output=True,
    )
    head = cli._head_sha(files.repo)
    app = Path(__file__).resolve().parents[2]
    assert Path(cli.__file__).resolve().is_relative_to(app)
    assert Path(report.__file__).resolve().is_relative_to(app)
    monkeypatch.setattr(native, "ARMS", (fc.Arm.native,))
    monkeypatch.setattr(cli, "_repo_root", lambda: files.repo)
    runs = []
    for name, changes in (("a", {}), ("b", primary)):
        raw = json.loads(files.decision.read_bytes())
        raw["primary"].update(changes)
        decision = files.decision.with_name(f"decision-{name}.json")
        native.write_json(decision, raw)
        run = native.run(files, decision_path=decision)
        assert json.loads((run / "manifest.json").read_bytes())["firbench"]["head_sha"] == head
        assert cli.main(["score", str(run)]) == 0
        destination = files.private / name
        run.rename(destination)
        runs.append(destination)
    path = cli.compare_runs(*runs, out_dir=runs[0], treatment=treatment, repo_root=files.repo)
    comparison = json.loads(path.read_bytes())
    report._binding_comparison(comparison)
    assert comparison["comparison_state"] == state
    assert comparison["delta"] is None
    assert comparison["paired_deltas"]
    assert all(row["status"] == "not_scored" and row["reason"] for row in comparison["paired_deltas"])
    assert comparison["treatment"] == {"name": treatment, "fields": [treatment] if treatment else []}
    assert set(comparison["differences"]) == set(primary)
    if state == "exploratory":
        assert comparison["label"] == "exploratory: multi-factor, no verdict"
        assert comparison["verdicts"] is None
    # The report must work from receipts after the existing fake assets are removed.
    for image in files.private.glob("*.png"):
        image.unlink()
    files.source.unlink()
    files.templates.unlink()
    files.binding_path.unlink()
    originals = {p: p.read_bytes() for run in runs for p in run.rglob("*") if p.is_file()}
    report.render_report(runs[0], out_dir=runs[0] / "report")
    content = (runs[0] / "report/index.html").read_text().split('id="compare"')[1].split("</section>")[0]
    assert_state(content, state)
    assert "Declared treatment name: " + (treatment or "none") in content
    assert "Declared treatment fields: " + (treatment or "none") in content
    for field in ("treatment/name", "treatment/fields", "differences"):
        assert f'data-source="comparison.json#/{field}"' in content
    for row in comparison["paired_deltas"]:
        assert html.escape(row["reason"], quote=True) in content
    if state == "exploratory":
        assert comparison["label"] in content
        assert "superior" not in content
    result = json.loads((runs[0] / "report/report.json").read_bytes())
    assert result["comparison"] == comparison
    assert {p: p.read_bytes() for p in originals} == originals


def test_real_shape_fixture_preserves_all_tables_and_source_paths():
    comparison = json.loads(FIXTURE.read_bytes())
    report._binding_comparison(comparison)
    before = copy.deepcopy(comparison)
    content = report._comparison_html(comparison)
    assert_state(content, "comparable")
    for caption in (
        "Recorded per-leg contrasts", "Supplied history (no interpolation)",
        "Recorded tau spread (absence stays unavailable)", "Leg contract changes",
    ):
        assert f"<caption>{caption}</caption>" in content
    for field in ("paired_deltas", "tau_spread", "leg_changes"):
        for index, row in enumerate(comparison[field]):
            assert f'data-source="comparison.json#/{field}/{index}"' in content
            for value in row.values():
                if isinstance(value, str):
                    assert html.escape(value, quote=True) in content
    for index, row in enumerate(comparison["history"]):
        for point in range(len(row["points"])):
            assert f'data-source="comparison.json#/history/{index}/points/{point}"' in content
    assert comparison == before


def test_comparison_absence_stays_unavailable():
    assert report._comparison_html(None) == "<p>comparison.json unavailable: no run-local comparison supplied.</p>"


def test_comparison_summary_escapes_supplied_text():
    comparison = json.loads(FIXTURE.read_bytes())
    hostile = '<img src=x onerror="bad()">&'
    comparison["label"] = hostile
    comparison["run_a"]["run_id"] = hostile
    comparison["treatment"] = {"name": hostile, "fields": [hostile]}
    comparison["differences"] = [hostile]
    comparison["paired_deltas"][0]["reason"] = hostile
    report._binding_comparison(comparison)
    content = report._comparison_html(comparison)
    assert hostile not in content
    assert "Declared treatment name: " + html.escape(hostile, quote=True) in content
    assert "Declared treatment fields: " + html.escape(hostile, quote=True) in content
    assert "differences: " + html.escape(hostile, quote=True) in content
    assert_state(content, "comparable")

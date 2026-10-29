"""EVALOPS-1-JUDGE: synthetic human truth only; never load the prelabels seed.

Predictions JSON: {"predictions": [{"id": "fnd-1", "label": "defect"}],
"protocol": {"model": "version", "prompt": "sha", "rubric": "sha",
"decoding": {"temperature": 0}, "seed": 7, "order_handling": "shuffled:7"}}.
QC JSON: {"decisions": [{"decision_id": "d1", "item_id": "gold-1",
"annotator": "a", "field": "human_label", "label": "defect",
"gold_label": "defect", "repeat_of": null}]}.
Only real, explicit known answers and identity-linked repeats supply QC evidence.
"""

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "benchmarks/tools/evalops/score_judge.py"
SPEC = importlib.util.spec_from_file_location("evalops_score_judge", SCRIPT)
judge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(judge)
PROTOCOL = {
    "model": "fixture-v1",
    "prompt": "sha256:prompt",
    "rubric": "sha256:rubric",
    "decoding": {"temperature": 0},
    "seed": 0,
    "order_handling": "randomized:0",
}


def findings(labels, *, severity="high", population=None, offset=0):
    n = len(labels)
    population = population or n
    return [
        {
            "id": f"fnd-{i + offset}",
            "finding_db_id": i + offset,
            "finding_id": f"TEST-{i + offset}",
            "task_ref": "EVALOPS-1",
            "severity": severity,
            "review_mode": "branch",
            "stratum": f"{severity}|branch",
            "stratum_population": population,
            "stratum_sample": n,
            "weight": round(population / n, 4),
            "human_label": label,
            "human_note": None,
        }
        for i, label in enumerate(labels)
    ]


def qc_decisions(n=200, gold=20, repeats=20, gold_errors=0, repeat_errors=0):
    """All decisions have distinct event IDs; repeats reuse actual item identity."""
    rows = []
    for i in range(n):
        row = {
            "decision_id": f"d{i}",
            "item_id": f"item-{i}",
            "annotator": "alice",
            "field": "human_label",
            "label": "defect" if i % 2 else "not_defect",
        }
        if i < gold:
            row["gold_label"] = row["label"] if i >= gold_errors else "unclear"
        if gold <= i < gold + repeats:
            original = rows[i - gold]
            row.update(item_id=original["item_id"], repeat_of=original["decision_id"])
            row["label"] = original["label"] if i - gold >= repeat_errors else "unclear"
        rows.append(row)
    return {"decisions": rows}


def test_wilson_hand_calculated_and_boundaries():
    # z=1.959963984540054, x=5,n=10: center=.5, half width=.2634069095.
    assert judge.wilson_interval(5, 10) == pytest.approx([0.2365930905, 0.7634069095])
    assert judge.wilson_interval(0, 10) == pytest.approx([0, 0.2775327999])
    assert judge.wilson_interval(10, 10) == pytest.approx([0.7224672001, 1])
    assert judge.wilson_interval(0, 0) is None


@pytest.mark.parametrize("x,n", [(-1, 2), (3, 2), (1, 0), (1.5, 2), (True, 2)])
def test_wilson_invalid_counts(x, n):
    with pytest.raises(ValueError):
        judge.wilson_interval(x, n)


def test_strata_and_weighted_ratio_are_not_pooled_wilson():
    rows = findings(["defect", "not_defect"], population=100)
    rows += findings(["defect"] * 8, severity="low", population=8, offset=2)
    report = judge.score(rows)
    high = report["strata"]["high|branch"]
    assert (high["numerator"], high["denominator"], high["rate"]) == (1, 2, 0.5)
    assert high["wilson_95"] == pytest.approx([0.0945312057, 0.9054687943])
    assert report["aggregate"]["rate"] == pytest.approx(58 / 108)
    assert report["aggregate"]["weighted_numerator"] == 58
    assert report["aggregate"]["weighted_denominator"] == 108
    assert report["aggregate"]["interval_95"] is None
    assert "ratio" in report["aggregate"]["method"]
    assert report["status"] == "scored"
    assert report["quality_acceptance"] == "not_evaluated"


def test_explicit_predictions_define_positive_denominator_and_categorical_agreement():
    rows = findings(["defect", "not_defect", "defect", "not_defect"])
    predictions = [{"id": r["id"], "label": label} for r, label in zip(rows, ["defect"] * 2 + ["not_defect"] * 2)]
    report = judge.score(rows, predictions=predictions, protocol=PROTOCOL)
    assert report["strata"]["high|branch"]["rate"] == 0.5
    assert report["agreement"]["kappa"] == 0
    assert report["protocol"]["values"] == PROTOCOL
    assert report["protocol"]["unknown_fields"] == []
    assert report["prediction_source"] == "explicit"


@pytest.mark.parametrize("unknown", [None, "unclear"])
def test_missing_human_labels_do_not_become_negatives(unknown):
    report = judge.score(findings(["defect", unknown]))
    assert report["status"] == "needs_labels"
    assert report["strata"]["high|branch"]["rate"] is None
    assert report["strata"]["high|branch"]["wilson_95"] is None
    assert report["aggregate"]["rate"] is None
    assert report["coverage"]["unresolved_human"] == 1
    assert report["qc"]["status"] == "not_provided"


def test_blind_seed_exports_without_qc_or_pretended_answers():
    source = ROOT / "benchmarks/experiments/evalops/findings-v0.jsonl"
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    assert len(rows) == 100
    before = copy.deepcopy(rows)
    report = judge.score(rows)
    assert rows == before
    assert report["status"] == "needs_labels"
    assert report["coverage"]["unresolved_human"] == 100
    assert all(s["rate"] is None for s in report["strata"].values())
    assert set(report["protocol"]["unknown_fields"]) == set(PROTOCOL)
    assert report["agreement"]["status"] == "missing"


@pytest.mark.parametrize("predictions", [[], [{"id": "fnd-0", "label": None}], [{"id": "fnd-0", "label": "unclear"}]])
def test_explicit_unknown_predictions_cannot_silently_drop_cases(predictions):
    report = judge.score(findings(["defect"]), predictions=predictions)
    assert report["status"] == "needs_predictions"
    assert report["aggregate"]["rate"] is None


def test_no_predicted_positives_is_undefined_not_perfect():
    report = judge.score(findings(["not_defect"]), predictions=[{"id": "fnd-0", "label": "not_defect"}])
    assert report["strata"]["high|branch"]["status"] == "no_positives"
    assert report["aggregate"]["rate"] is None


@pytest.mark.parametrize(
    "left,right,observed,chance,kappa,status",
    [
        (["defect", "not_defect"], ["defect", "not_defect"], 1, 0.5, 1, "ok"),
        (["defect", "not_defect"], ["not_defect", "defect"], 0, 0.5, -1, "ok"),
        (["defect"] * 10, ["defect"] * 9 + ["not_defect"], 0.9, 0.9, 0, "ok"),
        (["defect"], ["defect"], 1, 1, None, "degenerate"),
        ([None], ["defect"], None, None, None, "missing"),
        (["unclear"], ["unclear"], 1, 1, None, "degenerate"),
    ],
)
def test_shared_cohen_kappa(left, right, observed, chance, kappa, status):
    result = judge.cohen_kappa(left, right)
    for key, expected in (("observed_agreement", observed), ("chance_agreement", chance), ("kappa", kappa)):
        assert result[key] == (pytest.approx(expected) if expected is not None else None)
    assert result["status"] == status
    assert result["diagnostic_only"] is True


def test_kappa_counts_missing_pairs_and_rejects_misalignment():
    assert judge.cohen_kappa([None, "defect"], ["not_defect", "defect"])["missing_pairs"] == 1
    with pytest.raises(ValueError):
        judge.cohen_kappa(["defect"], [])


def test_qc_floors_and_support_are_separate_from_quality_acceptance():
    qc = qc_decisions(gold_errors=2, repeat_errors=2)
    report = judge.score(findings(["defect"]), qc=qc)
    assert report["qc"]["status"] == "passed"
    group = report["qc"]["groups"][0]
    assert group["gold_fraction"] == group["repeat_fraction"] == 0.1
    assert group["gold_accuracy"] == group["repeat_agreement"] == 0.9
    assert group["repeat_diagnostic"]["diagnostic_only"] is True
    assert report["quality_acceptance"] == "not_evaluated"
    assert report["qc"]["decisions"] == qc["decisions"]  # pre-adjudication preserved


@pytest.mark.parametrize("kwargs", [{"gold_errors": 3}, {"repeat_errors": 3}, {"n": 201}])
def test_qc_accuracy_and_ten_percent_floors(kwargs):
    report = judge.score(findings(["defect"]), qc=qc_decisions(**kwargs))
    assert report["qc"]["status"] == "failed"


def test_small_perfect_qc_cannot_be_accepted():
    report = judge.score(findings(["defect"]), qc=qc_decisions(n=10, gold=1, repeats=1))
    assert report["qc"]["status"] == "insufficient_support"


def test_gold_truth_must_be_consistent_for_the_same_item_and_field():
    qc = qc_decisions()
    other = dict(qc["decisions"][0], decision_id="bob-gold", annotator="bob", gold_label="unclear")
    qc["decisions"].append(other)
    with pytest.raises(ValueError, match="conflicting gold"):
        judge.score(findings(["defect"]), qc=qc)


def test_qc_not_pooled_across_annotators_or_fields():
    qc = qc_decisions()
    qc["decisions"][-1]["annotator"] = "bob"
    assert judge.score(findings(["defect"]), qc=qc)["qc"]["status"] != "passed"
    qc = qc_decisions()
    qc["decisions"][-1]["field"] = "another_field"
    assert judge.score(findings(["defect"]), qc=qc)["qc"]["status"] != "passed"


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate", "foreign_repeat", "wrong_item", "wrong_annotator", "wrong_field",
        "repeat_chain", "self_repeat", "missing_label", "invalid_gold",
    ],
)
def test_invalid_qc_identity_or_schema(mutation):
    qc = qc_decisions()
    rows = qc["decisions"]
    if mutation == "duplicate":
        rows.append(rows[0].copy())
    elif mutation == "foreign_repeat":
        rows[20]["repeat_of"] = "not-found"
    elif mutation == "wrong_item":
        rows[20]["item_id"] = "different"
    elif mutation == "wrong_annotator":
        rows[20]["annotator"] = "bob"
    elif mutation == "wrong_field":
        rows[20]["field"] = "other"
    elif mutation == "repeat_chain":
        rows[21].update(item_id=rows[20]["item_id"], repeat_of=rows[20]["decision_id"])
    elif mutation == "self_repeat":
        rows[20]["repeat_of"] = rows[20]["decision_id"]
    elif mutation == "missing_label":
        rows[0]["label"] = None
    else:
        rows[0]["gold_label"] = "invented"
    with pytest.raises(ValueError):
        judge.score(findings(["defect"]), qc=qc)


@pytest.mark.parametrize(
    "mutation", ["duplicate", "label", "weight", "count", "population", "stratum", "missing", "bool", "nan", "prelabel"]
)
def test_invalid_findings(mutation):
    rows = findings(["defect", "not_defect"])
    if mutation == "duplicate":
        rows[1]["id"] = rows[0]["id"]
    elif mutation == "label":
        rows[0]["human_label"] = "resolved"
    elif mutation == "weight":
        rows[0]["weight"] = 100
    elif mutation == "count":
        rows.pop()
    elif mutation == "population":
        rows[0]["stratum_population"] = 0
    elif mutation == "stratum":
        rows[0]["stratum"] = "low|branch"
    elif mutation == "missing":
        del rows[0]["human_label"]
    elif mutation == "bool":
        rows[0]["stratum_sample"] = True
    elif mutation == "nan":
        rows[0]["weight"] = float("nan")
    else:
        rows[0]["pre_label"] = "defect"
    with pytest.raises(ValueError):
        judge.score(rows)


@pytest.mark.parametrize(
    "predictions",
    [
        [{"id": "foreign", "label": "defect"}],
        [{"id": "fnd-0", "label": "yes"}],
        [{"id": "fnd-0", "label": "defect"}] * 2,
    ],
)
def test_invalid_predictions(predictions):
    with pytest.raises(ValueError):
        judge.score(findings(["defect"]), predictions=predictions)


def test_empty_and_invalid_protocol():
    with pytest.raises(ValueError):
        judge.score([])
    with pytest.raises(ValueError):
        judge.score(findings(["defect"]), protocol={"seed": True})


def test_cli_jsonl_predictions_qc_output_and_no_optional_imports(tmp_path):
    source = tmp_path / "findings.jsonl"
    source.write_text(json.dumps(findings(["defect"])[0]) + "\n")
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({"predictions": [{"id": "fnd-0", "label": "defect"}], "protocol": PROTOCOL}))
    qc = tmp_path / "qc.json"
    qc.write_text(json.dumps(qc_decisions(n=10, gold=1, repeats=1)))
    output = tmp_path / "output.json"
    # -I -S removes site packages; the scoring tool must remain stdlib-only.
    result = subprocess.run(
        [
            sys.executable, "-I", "-S", str(SCRIPT), "--findings", str(source),
            "--predictions", str(predictions), "--qc", str(qc), "--output", str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report["protocol"]["values"] == PROTOCOL
    assert report["qc"]["status"] == "insufficient_support"
    assert result.stdout == ""


@pytest.mark.parametrize(
    "failure",
    [
        "findings_missing", "predictions_missing", "qc_missing", "malformed", "bad_utf8",
        "bad_output", "bad_prediction_shape", "bad_qc_shape",
    ],
)
def test_cli_optional_io_and_schema_failures_are_structured(tmp_path, failure):
    source = tmp_path / "findings.jsonl"
    source.write_text(json.dumps(findings([None])[0]) + "\n")
    args = ["--findings", str(source)]
    if failure == "findings_missing":
        source.unlink()
    elif failure in ("predictions_missing", "qc_missing"):
        args += ["--" + failure.split("_")[0], str(tmp_path / "missing.json")]
    elif failure == "malformed":
        source.write_text("{broken\n")
    elif failure == "bad_utf8":
        source.write_bytes(b"\xff")
    elif failure == "bad_output":
        args += ["--output", str(tmp_path)]
    else:
        option = "predictions" if failure == "bad_prediction_shape" else "qc"
        path = tmp_path / "invalid.json"
        path.write_text("[]")
        args += ["--" + option, str(path)]
    result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["status"] == "error"
    assert "Traceback" not in result.stderr


def test_cli_unlabeled_export_is_not_an_error_or_pass(tmp_path):
    source = tmp_path / "findings.jsonl"
    source.write_text(json.dumps(findings([None])[0]) + "\n")
    result = subprocess.run([sys.executable, str(SCRIPT), "--findings", str(source)], capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "needs_labels"


@pytest.mark.parametrize("input_kind", ["findings", "predictions", "qc"])
def test_cli_cannot_clobber_operator_inputs(tmp_path, input_kind):
    source = tmp_path / "findings.jsonl"
    source.write_text(json.dumps(findings(["defect"])[0]) + "\n")
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({"predictions": [{"id": "fnd-0", "label": "defect"}]}))
    qc = tmp_path / "qc.json"
    qc.write_text(json.dumps(qc_decisions(n=10, gold=1, repeats=1)))
    inputs = {"findings": source, "predictions": predictions, "qc": qc}
    before = {key: path.read_bytes() for key, path in inputs.items()}
    # A symlink exercises path identity, beyond simple string equality.
    output = tmp_path / "alias.json"
    output.symlink_to(inputs[input_kind])
    args = [sys.executable, str(SCRIPT)]
    for key, path in inputs.items():
        args += ["--" + key, str(path)]
    result = subprocess.run([*args, "--output", str(output)], capture_output=True, text=True)
    assert result.returncode == 2
    assert json.loads(result.stderr)["status"] == "error"
    assert before == {key: path.read_bytes() for key, path in inputs.items()}


def cli_texts():
    """Valid disposable operator inputs; each strict-input case mutates exactly one of them."""
    predictions = [{"id": "fnd-0", "label": "defect"}, {"id": "fnd-1", "label": "not_defect"}]
    decision = {"decision_id": "d0", "item_id": "item-0", "annotator": "alice", "field": "human_label"}
    return {
        "findings": [json.dumps(row) for row in findings(["defect", "not_defect"])],
        "predictions": json.dumps({"predictions": predictions, "protocol": PROTOCOL}),
        "qc": json.dumps({"decisions": [dict(decision, label="defect", gold_label="defect")]}),
    }


def write_cli_inputs(tmp_path, texts):
    paths = {
        "findings": tmp_path / "findings.jsonl",
        "predictions": tmp_path / "predictions.json",
        "qc": tmp_path / "qc.json",
    }
    # The blank line puts the second finding on physical line 3.
    paths["findings"].write_text("\n\n".join(texts["findings"]) + "\n")
    paths["predictions"].write_text(texts["predictions"])
    paths["qc"].write_text(texts["qc"])
    return paths


def run_cli(paths, output):
    args = [sys.executable, str(SCRIPT)]
    for key, path in paths.items():
        args += ["--" + key, str(path)]
    return subprocess.run([*args, "--output", str(output)], capture_output=True, text=True)


@pytest.mark.parametrize("input_kind", ["findings", "predictions", "qc"])
def test_cli_rejects_output_hard_linked_to_operator_input(tmp_path, input_kind):
    paths = write_cli_inputs(tmp_path, cli_texts())
    before = {key: path.read_bytes() for key, path in paths.items()}
    output = tmp_path / "report.json"
    os.link(paths[input_kind], output)  # a second directory entry for the same inode
    assert output.resolve() != paths[input_kind].resolve() and output.samefile(paths[input_kind])
    result = run_cli(paths, output)
    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert "must not overwrite input" in error["error"]
    assert {key: path.read_bytes() for key, path in paths.items()} == before
    assert output.read_bytes() == before[input_kind]


def test_cli_replaces_an_existing_unlinked_report(tmp_path):
    paths = write_cli_inputs(tmp_path, cli_texts())
    before = {key: path.read_bytes() for key, path in paths.items()}
    output = tmp_path / "report.json"
    output.write_text("stale report\n")
    for _ in range(2):  # a stale regular file, then this tool's own previous report
        result = run_cli(paths, output)
        assert result.returncode == 0, result.stderr
        report = json.loads(output.read_text())
        assert (report["schema_version"], report["status"]) == ("evalops-score-judge/v1", "scored")
    assert {key: path.read_bytes() for key, path in paths.items()} == before


def with_duplicate(text, member, earlier):
    """Precede the single member starting with `member` by a conflicting earlier copy of its key."""
    assert text.count(member) == 1
    key = member.split(":", 1)[0]
    duplicated = text.replace(member, f"{key}: {json.dumps(earlier)}, {member}")
    assert json.loads(duplicated) == json.loads(text)  # plain JSON silently keeps the last value
    return duplicated


def assert_rejected_before_write(tmp_path, texts, match):
    paths = write_cli_inputs(tmp_path, texts)
    before = {key: path.read_bytes() for key, path in paths.items()}
    output = tmp_path / "report.json"
    result = run_cli(paths, output)
    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert re.search(match, error["error"]), error
    assert not output.exists()
    assert {key: path.read_bytes() for key, path in paths.items()} == before


@pytest.mark.parametrize(
    "kind,member,earlier,match",
    [
        ("findings", '"human_label": "not_defect"', None, r"findings\.jsonl:3: duplicate JSON key 'human_label'"),
        ("predictions", '"predictions": [', [], r"predictions\.json: duplicate JSON key 'predictions'"),
        ("predictions", '"label": "not_defect"', "defect", r"predictions\.json: duplicate JSON key 'label'"),
        ("predictions", '"seed": 0', 7, r"predictions\.json: duplicate JSON key 'seed'"),
        ("qc", '"label": "defect"', "not_defect", r"qc\.json: duplicate JSON key 'label'"),
    ],
    ids=["finding-label", "predictions-top-level", "prediction-label", "protocol-seed", "qc-label"],
)
def test_cli_rejects_duplicate_json_keys_in_every_input(tmp_path, kind, member, earlier, match):
    texts = cli_texts()
    if kind == "findings":
        texts["findings"][1] = with_duplicate(texts["findings"][1], member, earlier)
    else:
        texts[kind] = with_duplicate(texts[kind], member, earlier)
    assert_rejected_before_write(tmp_path, texts, match)


@pytest.mark.parametrize(
    "kind,constant,match",
    [
        ("findings", "NaN", r"findings\.jsonl:3: invalid JSON constant NaN"),
        ("predictions", "Infinity", r"predictions\.json: invalid JSON constant Infinity"),
        ("qc", "-Infinity", r"qc\.json: invalid JSON constant -Infinity"),
    ],
    ids=["findings", "predictions", "qc"],
)
def test_cli_rejects_non_finite_json_constants_in_every_input(tmp_path, kind, constant, match):
    value = float(constant)
    texts = cli_texts()
    if kind == "findings":
        # line_start is an unvalidated descriptive field, so only the loader can reject it.
        texts["findings"][1] = json.dumps(dict(json.loads(texts["findings"][1]), line_start=value))
    elif kind == "predictions":
        payload = json.loads(texts["predictions"])
        texts["predictions"] = json.dumps(dict(payload, protocol=dict(PROTOCOL, decoding={"temperature": value})))
    else:
        texts["qc"] = json.dumps({"decisions": [dict(json.loads(texts["qc"])["decisions"][0], gold_label=value)]})
    assert constant in (texts[kind][1] if kind == "findings" else texts[kind])
    assert_rejected_before_write(tmp_path, texts, match)

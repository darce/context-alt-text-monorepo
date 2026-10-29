"""Contract tests for conditional pooled retrieval scoring, using synthetic rankings."""

from __future__ import annotations

import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / "benchmarks/tools/evalops/score_retrieval.py"
SEED = ROOT / "benchmarks/experiments/evalops/qrels-v0.jsonl"


def scorer():
    assert SCORER.is_file(), "EVALOPS-1-RETRIEVAL scorer is not implemented"
    spec = importlib.util.spec_from_file_location("evalops_score_retrieval", SCORER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qrel(doc="a", relevance=2, query_id="q1", **updates):
    return {
        "query_id": query_id, "query": f"information need {query_id}",
        "doc_id": doc, "relevance": relevance, "source": "synthetic",
        "later_doc_id": None, "evidence": None, **updates,
    }


def result(*docs, query_id="q1"):
    return {"query_id": query_id, "doc_ids": list(docs)}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def invoke(qrels, results, *extra):
    return subprocess.run(
        [sys.executable, str(SCORER), "--qrels", str(qrels), "--results", str(results), *extra],
        capture_output=True, text=True, check=False,
    )


def test_hand_calculated_rankings_multiple_k_and_deduplication():
    report = scorer().score(
        [qrel("a", 2), qrel("b", 1), qrel("c", 0)],
        [result("b", "b", "unknown", "a", "c")], [4, 1, 3, 3],
    )
    assert report["schema_version"] == "evalops.retrieval.v1"
    assert report["status"] == "ok"
    assert report["ks"] == [1, 3, 4]
    query = report["per_query"][0]
    assert query["duplicate_doc_count"] == 1
    assert [item["doc_id"] for item in query["ranked_results"]] == ["b", "unknown", "a", "c"]
    assert query["ranked_results"][1] == {"doc_id": "unknown", "relevance": None, "judgment": "UNKNOWN"}
    at1, at3, at4 = (query["metrics"][str(k)] for k in (1, 3, 4))
    assert at1["recall_at_k"] == {"value": 0.5, "numerator": 1, "denominator": 2, "status": "ok"}
    assert at1["ndcg_at_k"]["value"] == pytest.approx(1 / 3)
    ideal = 3 + 1 / math.log2(3)
    assert at3["ndcg_at_k"]["numerator"] == pytest.approx(1 + 3 / 2)
    assert at3["ndcg_at_k"]["denominator"] == pytest.approx(ideal)
    assert at3["ndcg_at_k"]["value"] == pytest.approx(2.5 / ideal)
    assert at3["recall_at_k"]["value"] == 1
    assert at4["coverage"] == {
        "retrieved": 4, "judged": 3, "unjudged": 1,
        "judgment_coverage": 0.75, "unjudged_at_k": 0.25, "unjudged_doc_ids": ["unknown"],
    }
    assert report["macro"]["3"]["ndcg_at_k"]["value"] == pytest.approx(2.5 / ideal)
    json.dumps(report, allow_nan=False)


def test_qrels_define_macro_denominator_missing_queries_are_zero():
    report = scorer().score(
        [qrel("a"), qrel("b", query_id="q2"), qrel("c", query_id="q2")],
        [result("a")], [1, 10],
    )
    assert report["counts"]["query_count"] == 2
    assert report["counts"]["missing_result_query_count"] == 1
    missing = report["per_query"][1]
    assert missing["results_status"] == "missing"
    for k in ("1", "10"):
        assert missing["metrics"][k]["recall_at_k"]["value"] == 0
        assert missing["metrics"][k]["ndcg_at_k"]["value"] == 0
        for name in ("recall_at_k", "ndcg_at_k"):
            assert report["macro"][k][name] == {
                "value": 0.5, "numerator": 1.0, "denominator": 2, "status": "ok",
            }
        assert missing["metrics"][k]["coverage"]["judgment_coverage"] is None
    # Macro recall averages queries, rather than pooling retrieved/relevant docs (1/3).
    assert report["macro"]["10"]["recall_at_k"]["value"] != pytest.approx(1 / 3)


def test_no_relevant_and_missing_relevance_are_explicitly_excluded():
    missing = qrel("unknown", None, query_id="q3")
    missing.pop("relevance")
    report = scorer().score(
        [qrel("zero", 0), qrel("null", None, query_id="q2"), missing],
        [result("zero"), result("null", query_id="q2")], [3],
    )
    assert report["status"] == "no_evaluable_queries"
    assert report["counts"]["judgment_count"] == 1
    assert report["counts"]["unknown_qrel_count"] == 2
    assert report["counts"]["excluded_query_count"] == 3
    for query in report["per_query"]:
        assert query["status"] == "no_relevant_judgments"
        for name in ("recall_at_k", "ndcg_at_k"):
            metric = query["metrics"]["3"][name]
            assert metric["value"] is None
            assert metric["denominator"] == 0
            assert metric["status"] == "no_relevant_judgments"
    assert report["macro"]["3"]["recall_at_k"]["value"] is None
    assert report["macro"]["3"]["recall_at_k"]["denominator"] == 0
    coverage = report["macro"]["3"]["coverage"]
    assert coverage["judgment_coverage"]["value"] == 0.5
    assert coverage["unjudged_at_k"]["value"] == 0.5
    json.dumps(report, allow_nan=False)


def test_unknown_does_not_equal_judged_zero_and_rank_is_not_compressed():
    report = scorer().score([qrel("a"), qrel("z", 0), qrel("null", None)],
                            [result("u", "null", "z", "a")], [4])
    query = report["per_query"][0]
    assert [item["judgment"] for item in query["ranked_results"]] == ["UNKNOWN", "UNKNOWN", "judged", "judged"]
    assert query["metrics"]["4"]["ndcg_at_k"]["value"] == pytest.approx(1 / math.log2(5))
    assert query["metrics"]["4"]["coverage"]["unjudged_doc_ids"] == ["u", "null"]
    assert report["estimate"] == "conditional_pooled"
    assert "unknown" in report["limitations"].lower()


def test_macro_excludes_only_queries_without_positive_judgments():
    report = scorer().score([qrel("a"), qrel("z", 0, query_id="q2")], [result("a")], [1])
    assert report["counts"]["evaluable_query_count"] == 1
    assert report["counts"]["excluded_query_count"] == 1
    assert report["macro"]["1"]["recall_at_k"]["value"] == 1
    assert report["macro"]["1"]["recall_at_k"]["denominator"] == 1


def test_order_is_deterministic_equal_grades_keep_input_ranking_and_inputs_unchanged():
    qrels = [qrel("z", 1), qrel("a", 1), qrel("x", 2, query_id="q2")]
    results = [result("x", query_id="q2"), result("z", "a", "z")]
    before = json.dumps([qrels, results])
    api = scorer()
    first = api.score(qrels, results, [2, 1])
    second = api.score(reversed(qrels), reversed(results), [1, 2])
    assert first == second
    assert [row["query_id"] for row in first["per_query"]] == ["q1", "q2"]
    assert first["per_query"][0]["ranked_results"][0]["doc_id"] == "z"
    assert first["macro"]["2"]["ndcg_at_k"]["value"] == 1
    assert before == json.dumps([qrels, results])


def test_empty_present_results_are_distinct_from_missing_and_coverage_is_null():
    report = scorer().score([qrel()], [result()], [2])
    assert report["per_query"][0]["results_status"] == "present"
    assert report["counts"]["missing_result_query_count"] == 0
    assert report["macro"]["2"]["recall_at_k"]["value"] == 0
    for metric in report["macro"]["2"]["coverage"].values():
        assert metric == {"value": None, "numerator": 0, "denominator": 0, "status": "no_retrieved_docs"}


def test_seed_schema_loads_without_inventing_pool_protocol_or_tuning_rankings():
    rows = [json.loads(line) for line in SEED.read_text(encoding="utf-8").splitlines()]
    report = scorer().score(rows, [], [1, 5])
    assert len(rows) == 41
    assert report["counts"]["query_count"] == 27
    assert report["counts"]["judgment_count"] == 41
    assert report["macro"]["5"]["recall_at_k"]["denominator"] == 27
    assert report["macro"]["5"]["recall_at_k"]["value"] == 0
    assert report["pool"] == {"depth": None, "contributors": None, "metadata_status": "unknown", "completeness": "unknown"}


@pytest.mark.parametrize("kwargs,status", [
    ({"pool_depth": 50}, "partially_supplied"),
    ({"pool_contributors": ["lexical", "semantic", "lexical"]}, "partially_supplied"),
    ({"pool_depth": 50, "pool_contributors": ["semantic"]}, "supplied"),
])
def test_pool_protocol_is_only_user_supplied(kwargs, status):
    pool = scorer().score([qrel()], [], [1], **kwargs)["pool"]
    assert pool["metadata_status"] == status
    assert pool["depth"] == kwargs.get("pool_depth")
    contributors = kwargs.get("pool_contributors")
    assert pool["contributors"] == (sorted(set(contributors)) if contributors else None)
    assert pool["completeness"] == "unknown"


@pytest.mark.parametrize("rows,match", [
    ([], "qrels.*empty"), ([None], "object"),
    ([{**qrel(), "doc_id": ""}], "doc_id"),
    ([{k: v for k, v in qrel().items() if k != "query_id"}], "query_id"),
    ([{**qrel(), "query": None}], "query"),
    ([qrel(relevance=True)], "relevance"), ([qrel(relevance=1.5)], "relevance"),
    ([qrel(relevance=-1)], "relevance"), ([qrel(relevance=3)], "relevance"),
    ([qrel(relevance="2")], "relevance"),
    ([qrel(), qrel()], "duplicate"),
    ([qrel(), qrel("b", query="different text")], "query text"),
    ([{**qrel(), "relevnce": 2}], "unexpected"),
    ([qrel(source=[])], "source"), ([qrel(later_doc_id=9)], "later_doc_id"),
    ([qrel(evidence=[])], "evidence"),
])
def test_malformed_qrels_are_rejected(rows, match):
    with pytest.raises(ValueError, match=match):
        scorer().score(rows, [], [1])


@pytest.mark.parametrize("rows,match", [
    ([None], "object"), ([{"query_id": "q1"}], "doc_ids"),
    ([{"query_id": "q1", "doc_ids": "a"}], "doc_ids"),
    ([result(1)], "doc_ids"), ([result("")], "doc_ids"),
    ([result("a"), result("b")], "duplicate"),
    ([result("a", query_id="foreign")], "unknown query_id"),
    ([{"query_id": "q1", "results": []}], "doc_ids"),
    ([{**result("a"), "scores": [1.0]}], "unexpected"),
])
def test_malformed_results_are_rejected(rows, match):
    with pytest.raises(ValueError, match=match):
        scorer().score([qrel()], rows, [1])


@pytest.mark.parametrize("ks", [[], [0], [-1], [True], [1.5], ["2"]])
def test_invalid_cutoffs_are_rejected(ks):
    with pytest.raises(ValueError, match="k"):
        scorer().score([qrel()], [], ks)


@pytest.mark.parametrize("kwargs", [
    {"pool_depth": 0}, {"pool_depth": True}, {"pool_depth": 1.5},
    {"pool_contributors": [""]}, {"pool_contributors": [None]},
    {"pool_contributors": "semantic"},
])
def test_invalid_pool_metadata_is_rejected(kwargs):
    with pytest.raises(ValueError, match="pool"):
        scorer().score([qrel()], [], [1], **kwargs)


def test_cli_emits_json_stdout_and_optional_output(tmp_path):
    qrels = write_jsonl(tmp_path / "qrels.jsonl", [qrel()])
    results = write_jsonl(tmp_path / "results.jsonl", [result("a")])
    output = tmp_path / "report.json"
    run = invoke(qrels, results, "--k", "1", "--k", "5", "--pool-depth", "20",
                 "--pool-contributor", "lexical", "--pool-contributor", "semantic", "--output", str(output))
    assert run.returncode == 0, run.stderr
    assert run.stderr == ""
    report = json.loads(run.stdout)
    assert json.loads(output.read_text()) == report
    assert report["ks"] == [1, 5]
    assert report["pool"]["contributors"] == ["lexical", "semantic"]
    assert report["macro"]["1"]["recall_at_k"]["value"] == 1


@pytest.mark.parametrize("content,match", [
    (b"not json\n", "line 1"), (b"{}\n{broken\n", "line 2"),
    (b"\xff", "utf-8"), (b'{"query_id":"q1","doc_ids":[NaN]}\n', "line 1"),
    (b'{"query_id":"q1","query_id":"q2","doc_ids":[]}\n', "duplicate.*query_id"),
])
def test_cli_malformed_jsonl_and_encoding_fail_loudly(tmp_path, content, match):
    qrels = write_jsonl(tmp_path / "qrels.jsonl", [qrel()])
    results = tmp_path / "results.jsonl"
    results.write_bytes(content)
    run = invoke(qrels, results, "--k", "1")
    assert run.returncode == 2
    assert run.stdout == ""
    error = json.loads(run.stderr)
    assert error["status"] == "error"
    import re
    assert re.search(match, error["error"])


@pytest.mark.parametrize("missing", ["qrels", "results"])
def test_missing_input_file_is_error_not_empty_success(tmp_path, missing):
    qrels = tmp_path / "qrels.jsonl"
    results = tmp_path / "results.jsonl"
    if missing != "qrels":
        write_jsonl(qrels, [qrel()])
    if missing != "results":
        write_jsonl(results, [result()])
    run = invoke(qrels, results, "--k", "1")
    assert run.returncode == 2
    assert run.stdout == ""
    assert json.loads(run.stderr)["status"] == "error"
    assert str(tmp_path / f"{missing}.jsonl") in json.loads(run.stderr)["error"]


def test_empty_results_file_is_valid_and_blank_lines_are_ignored(tmp_path):
    qrels = write_jsonl(tmp_path / "qrels.jsonl", [qrel()])
    results = tmp_path / "results.jsonl"
    results.write_text("\n \n", encoding="utf-8")
    run = invoke(qrels, results, "--k", "1")
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["counts"]["missing_result_query_count"] == 1
    assert report["macro"]["1"]["recall_at_k"]["value"] == 0


def test_output_io_failure_is_reported_without_success(tmp_path, monkeypatch, capsys):
    api = scorer()
    qrels = write_jsonl(tmp_path / "qrels.jsonl", [qrel()])
    results = write_jsonl(tmp_path / "results.jsonl", [result("a")])
    def deny(*args, **kwargs):
        raise PermissionError("synthetic permission denied")
    monkeypatch.setattr(api, "write_report", deny)
    assert api.main(["--qrels", str(qrels), "--results", str(results), "--k", "1",
                     "--output", str(tmp_path / "out.json")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "synthetic permission denied" in json.loads(captured.err)["error"]


def test_output_cannot_overwrite_input_including_symlink_alias(tmp_path):
    qrels = write_jsonl(tmp_path / "qrels.jsonl", [qrel()])
    results = write_jsonl(tmp_path / "results.jsonl", [result("a")])
    before = qrels.read_bytes(), results.read_bytes()
    alias = tmp_path / "alias.json"
    alias.symlink_to(qrels)
    for output in (qrels, results, alias):
        run = invoke(qrels, results, "--k", "1", "--output", str(output))
        assert run.returncode == 2
        assert run.stdout == ""
        assert "overwrite" in json.loads(run.stderr)["error"]
    assert (qrels.read_bytes(), results.read_bytes()) == before


def test_library_import_and_cli_work_without_site_packages_or_optional_integrations(tmp_path):
    qrels = write_jsonl(tmp_path / "qrels.jsonl", [qrel()])
    results = write_jsonl(tmp_path / "results.jsonl", [result("a")])
    program = """
import importlib.util, sys
def deny_external(event, args):
    if event == 'import' and args[0].split('.')[0] in {'requests', 'numpy', 'mcp', 'openai', 'pytest'}:
        raise ImportError('optional integration deliberately unavailable')
    if event.startswith('socket.'):
        raise RuntimeError('network forbidden')
sys.addaudithook(deny_external)
spec = importlib.util.spec_from_file_location('retrieval', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raise SystemExit(module.main(sys.argv[2:]))
"""
    run = subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(SCORER), "--qrels", str(qrels),
         "--results", str(results), "--k", "1"], capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["macro"]["1"]["ndcg_at_k"]["value"] == 1

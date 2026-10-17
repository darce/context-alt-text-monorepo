"""Contract tests for the offline semantic-selection evaluator.

Known answers come from the committed fixture
``scripts/eval_harness/semantic_selection_example.json``; the hand-computed
values are noted inline. Scores are exact cosines over precomputed vectors and
measure retrieval relevance only (TEST-06: the first run is expected to fail
at import, before the module exists).
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.eval_harness import semantic_selection_eval as sse

APP_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = APP_ROOT / "scripts" / "eval_harness" / "semantic_selection_example.json"
MODULE_PATH = APP_ROOT / "scripts" / "eval_harness" / "semantic_selection_eval.py"
ZERO_REVISION = "0" * 40


def _base_doc() -> dict[str, Any]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _run(doc: dict[str, Any]) -> dict[str, Any]:
    return sse.evaluate_bytes(json.dumps(doc).encode("utf-8"))


def _row(report: dict[str, Any], query_id: str) -> dict[str, Any]:
    return next(row for row in report["queries"] if row["query_id"] == query_id)


def _ranked_ids(report: dict[str, Any], query_id: str) -> list[str]:
    return [item["candidate_id"] for item in _row(report, query_id)["ranking"]]


def _run_cli(input_path: Path, output: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.eval_harness.semantic_selection_eval",
            str(input_path),
            "--output",
            str(output),
        ],
        cwd=APP_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_hand_computed_ranking_matches_exact_cosines() -> None:
    report = _run(_base_doc())

    # q-1 = (1, 1, 0, 0)/sqrt(2): cos(ctx-b)=1.4/sqrt(2), cos(ctx-a)=cos(ctx-c)=1/sqrt(2), cos(ctx-d)=0.8/sqrt(2).
    assert _ranked_ids(report, "q-1") == ["ctx-b", "ctx-a", "ctx-c", "ctx-d"]
    scores = [item["score"] for item in _row(report, "q-1")["ranking"]]
    assert scores[0] == pytest.approx(1.4 / math.sqrt(2), abs=1e-9)
    assert scores[1] == pytest.approx(1 / math.sqrt(2), abs=1e-9)
    assert scores[3] == pytest.approx(0.8 / math.sqrt(2), abs=1e-9)
    # q-2 = (1, 0, 0, 0): decoy-x (cos 1.0, denied) and policy-1 (protected) are absent.
    assert _ranked_ids(report, "q-2") == ["ctx-a", "ctx-d", "ctx-b", "ctx-c"]
    # q-3 = (0, 0, 1, 0): ctx-d cos 0.6; the remaining zero-cosine ties break by id.
    assert _ranked_ids(report, "q-3") == ["ctx-d", "ctx-a", "ctx-b", "ctx-c"]


def test_exact_tie_breaks_by_candidate_id_not_input_order() -> None:
    doc = _base_doc()
    doc["candidates"].reverse()
    report = _run(doc)

    # ctx-a and ctx-c score exactly 1/sqrt(2) for q-1; the lower id ranks first.
    ranking = _row(report, "q-1")["ranking"]
    assert [item["candidate_id"] for item in ranking[1:3]] == ["ctx-a", "ctx-c"]
    assert ranking[1]["score"] == ranking[2]["score"]
    assert _row(report, "q-1")["first_gold_rank"] == 3


def test_top1_and_mrr_use_all_frozen_queries_as_denominator() -> None:
    report = _run(_base_doc())
    metrics = report["metrics"]

    assert metrics["query_count"] == 3
    assert metrics["top1"]["hits"] == 1
    assert metrics["top1"]["denominator"] == 3
    assert metrics["top1"]["value"] == pytest.approx(1 / 3)
    # RR: q-1 = 1/3 (gold ctx-c ranks 3rd), q-2 = 1, q-3 = 0 (no relevant) -> mean 4/9.
    assert metrics["mrr"]["denominator"] == 3
    assert metrics["mrr"]["value"] == pytest.approx(4 / 9)
    assert metrics["no_relevant_query_ids"] == ["q-3"]
    assert _row(report, "q-3")["status"] == "no_relevant"
    assert _row(report, "q-3")["reciprocal_rank"] == 0.0
    assert _row(report, "q-1")["reciprocal_rank"] == pytest.approx(1 / 3)
    assert _row(report, "q-2")["top1_hit"] is True


def test_denied_high_similarity_decoy_is_never_ranked_or_selected() -> None:
    report = _run(_base_doc())
    # decoy-x has cosine 1.0 with q-2 but is denied, so it never enters the pool.
    assert "decoy-x" not in _ranked_ids(report, "q-2")
    assert _ranked_ids(report, "q-2")[0] == "ctx-a"

    doc = _base_doc()
    doc["selections"]["baseline"]["q-2"].append("decoy-x")
    with pytest.raises(sse.SemanticSelectionError, match="denied candidate 'decoy-x'"):
        _run(doc)


def test_protected_policy_record_is_never_ranked_or_authorized() -> None:
    report = _run(_base_doc())
    # policy-1 has cosine 1/sqrt(2) with q-1, a tie with ctx-a and ctx-c; it must still not rank.
    for query_id in ("q-1", "q-2", "q-3"):
        assert "policy-1" not in _ranked_ids(report, query_id)
    assert report["protected_records"] == {
        "ids": ["policy-1"],
        "ranked": False,
        "required_in_every_frozen_pack": True,
    }

    doc = _base_doc()
    doc["queries"][0]["gold_ids"].append("policy-1")
    with pytest.raises(sse.SemanticSelectionError, match="not an approved candidate"):
        _run(doc)

    doc = _base_doc()
    doc["selections"]["full_pack"]["q-2"].remove("policy-1")
    with pytest.raises(sse.SemanticSelectionError, match="policy-1.*suppressed"):
        _run(doc)


def test_empty_candidate_set_is_rejected() -> None:
    doc = _base_doc()
    doc["candidates"] = []
    with pytest.raises(sse.SemanticSelectionError, match="empty candidate set"):
        _run(doc)


def test_no_approved_candidates_keeps_every_query_explicit() -> None:
    base = _base_doc()
    doc = {
        **base,
        "candidates": [c for c in base["candidates"] if c["id"] in {"policy-1", "decoy-x"}],
        "queries": [{**q, "gold_ids": []} for q in base["queries"]],
        "selections": {pack: {q["id"]: ["policy-1"] for q in base["queries"]} for pack in ("baseline", "full_pack")},
    }
    report = _run(doc)

    assert [row["status"] for row in report["queries"]] == ["no_approved_candidates"] * 3
    assert report["metrics"]["top1"] == {"hits": 0, "denominator": 3, "value": 0.0}
    assert report["metrics"]["mrr"]["denominator"] == 3
    assert report["metrics"]["mrr"]["value"] == 0.0


@pytest.mark.parametrize("side", ["query_encoder", "candidate_encoder"])
def test_face_namespace_rejected_even_when_dimensions_match(side: str) -> None:
    doc = _base_doc()
    doc[side]["namespace"] = "face_identity"
    with pytest.raises(sse.SemanticSelectionError, match="face"):
        _run(doc)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", "other/encoder"),
        ("revision", "1" * 40),
        ("preprocessing", "other-preprocessing"),
        ("dimension", 5),
        ("normalization", "none"),
        ("space_id", "other-space"),
    ],
)
def test_contract_mismatch_on_any_field_is_rejected_despite_equal_vector_length(field: str, value: Any) -> None:
    # Both sides still carry 4-dimensional vectors; equal length alone never proves compatibility.
    doc = _base_doc()
    doc["candidate_encoder"][field] = value
    with pytest.raises(sse.SemanticSelectionError, match=field):
        _run(doc)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_vector_values_are_rejected(bad: float) -> None:
    doc = _base_doc()
    doc["candidates"][0]["vector"][2] = bad
    with pytest.raises(sse.SemanticSelectionError, match="not finite"):
        _run(doc)


@pytest.mark.parametrize("owner", ["candidate", "query"])
def test_zero_vector_is_rejected(owner: str) -> None:
    doc = _base_doc()
    if owner == "candidate":
        doc["candidates"][0]["vector"] = [0, 0, 0, 0]
    else:
        doc["queries"][0]["vector"] = [0, 0, 0, 0]
    with pytest.raises(sse.SemanticSelectionError, match="zero vector"):
        _run(doc)


@pytest.mark.parametrize("vector", [["1", 0, 0, 0], [True, 0, 0, 0], [[1], 0, 0, 0], [], "1,0,0,0"])
def test_malformed_vectors_are_rejected(vector: Any) -> None:
    doc = _base_doc()
    doc["queries"][1]["vector"] = vector
    with pytest.raises(sse.SemanticSelectionError, match="vector"):
        _run(doc)


def test_truncated_vector_is_rejected_explicitly() -> None:
    doc = _base_doc()
    doc["candidates"][1]["vector"] = [0.6, 0.8, 0.0]
    with pytest.raises(sse.SemanticSelectionError, match="truncation"):
        _run(doc)


def test_declared_l2_normalization_is_verified() -> None:
    doc = _base_doc()
    doc["queries"][1]["vector"] = [2, 0, 0, 0]
    with pytest.raises(sse.SemanticSelectionError, match="normalization is 'l2'"):
        _run(doc)


def _duplicate_candidate(doc: dict[str, Any]) -> None:
    doc["candidates"].append(dict(doc["candidates"][0]))


def _duplicate_query(doc: dict[str, Any]) -> None:
    doc["queries"].append(dict(doc["queries"][0]))


def _duplicate_gold(doc: dict[str, Any]) -> None:
    doc["queries"][0]["gold_ids"] = ["ctx-c", "ctx-c"]


def _duplicate_selection(doc: dict[str, Any]) -> None:
    doc["selections"]["baseline"]["q-1"].append("ctx-a")


@pytest.mark.parametrize(
    "mutate",
    [_duplicate_candidate, _duplicate_query, _duplicate_gold, _duplicate_selection],
    ids=["candidate-id", "query-id", "gold-id", "selected-id"],
)
def test_duplicate_ids_are_rejected(mutate: Any) -> None:
    doc = _base_doc()
    mutate(doc)
    with pytest.raises(sse.SemanticSelectionError, match="duplicate"):
        _run(doc)


def test_duplicate_json_object_key_is_rejected() -> None:
    raw = json.dumps(_base_doc())
    raw = raw[:-1] + ', "schema_version": "semantic-selection-eval/v1"}'
    with pytest.raises(sse.SemanticSelectionError, match="duplicate JSON object key 'schema_version'"):
        sse.evaluate_bytes(raw.encode("utf-8"))


def test_unknown_gold_id_is_rejected() -> None:
    doc = _base_doc()
    doc["queries"][2]["gold_ids"] = ["ctx-missing"]
    with pytest.raises(sse.SemanticSelectionError, match="unknown gold id 'ctx-missing'"):
        _run(doc)


def test_frozen_packs_must_cover_exactly_the_frozen_queries() -> None:
    doc = _base_doc()
    del doc["selections"]["full_pack"]["q-3"]
    with pytest.raises(sse.SemanticSelectionError, match="full_pack"):
        _run(doc)

    doc = _base_doc()
    doc["selections"]["baseline"]["q-9"] = ["policy-1"]
    with pytest.raises(sse.SemanticSelectionError, match="baseline"):
        _run(doc)

    doc = _base_doc()
    doc["selections"]["baseline"]["q-1"].append("ctx-zzz")
    with pytest.raises(sse.SemanticSelectionError, match="unknown selected id 'ctx-zzz'"):
        _run(doc)


def test_pack_comparison_is_ordered_not_set_equal() -> None:
    doc = _base_doc()
    doc["selections"]["baseline"]["q-1"] = ["policy-1", "ctx-b", "ctx-a"]
    doc["selections"]["full_pack"]["q-1"] = ["ctx-b", "policy-1", "ctx-a"]
    comparison = _run(doc)["pack_comparison"]["q-1"]

    # Same membership, different order: set equality would hide the role swap.
    assert comparison["ordered_equal"] is False
    assert comparison["first_divergence_index"] == 0
    assert comparison["added"] == []
    assert comparison["removed"] == []


def test_unknown_schema_version_and_extra_keys_are_rejected() -> None:
    doc = _base_doc()
    doc["schema_version"] = "semantic-selection-eval/v0"
    with pytest.raises(sse.SemanticSelectionError, match="schema_version"):
        _run(doc)

    doc = _base_doc()
    doc["query_encoder"]["truncate_to"] = 2
    with pytest.raises(sse.SemanticSelectionError, match="truncate_to"):
        _run(doc)

    doc = _base_doc()
    doc["latency_ms"] = 12
    with pytest.raises(sse.SemanticSelectionError, match="latency_ms"):
        _run(doc)


def test_report_records_schema_digest_encoder_provenance_and_interpretation() -> None:
    raw = EXAMPLE_PATH.read_bytes()
    report = sse.evaluate_bytes(raw)

    assert report["schema_version"] == sse.REPORT_SCHEMA_VERSION
    assert report["input_schema_version"] == sse.SCHEMA_VERSION
    assert report["input_sha256"] == hashlib.sha256(raw).hexdigest()
    provenance = report["encoder_provenance"]
    assert provenance["contracts_match"] is True
    assert provenance["query_encoder"] == provenance["candidate_encoder"]
    assert provenance["query_encoder"]["revision"] == ZERO_REVISION
    assert report["interpretation"]["score_meaning"] == "retrieval relevance only"
    assert set(report["interpretation"]["not_established"]) == {"visual truth", "identity", "consent", "authority"}


def test_identical_input_yields_identical_report() -> None:
    raw = EXAMPLE_PATH.read_bytes()
    assert sse.evaluate_bytes(raw) == sse.evaluate_bytes(raw)


def test_module_depends_only_on_stdlib_and_pydantic() -> None:
    # No encoder, inference, or FIR/recognition imports: the evaluator consumes precomputed vectors only.
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert "pydantic" in roots
    assert not roots - set(sys.stdlib_module_names) - {"pydantic"}


def test_cli_writes_report_for_committed_example(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    result = _run_cli(EXAMPLE_PATH, output)

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["metrics"]["top1"]["hits"] == 1
    assert report["metrics"]["mrr"]["value"] == pytest.approx(4 / 9)


def test_cli_rejects_nonfinite_input_without_writing_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    doc = _base_doc()
    doc["candidates"][0]["vector"][0] = float("nan")
    bad.write_text(json.dumps(doc), encoding="utf-8")
    output = tmp_path / "report.json"

    result = _run_cli(bad, output)

    assert result.returncode == 1
    assert "not finite" in result.stderr
    assert not output.exists()

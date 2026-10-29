"""Score ranked prior-art results against incomplete pooled relevance judgments.

Runner API: ``score(qrels, results, ks, *, pool_depth=None, pool_contributors=None)``
accepts iterables of JSON objects and returns a JSON-serializable report. Qrels
require query_id, query, and doc_id strings; relevance is an integer 0..2 or
null/absent (UNKNOWN). Optional seed provenance fields are source, later_doc_id,
and evidence. Results must have exactly {query_id, doc_ids: [ranked strings]}.
Duplicate result rows, duplicate qrel pairs, and foreign query IDs are errors.

Recall counts retrieved positive judgments / all positive judgments per query.
DCG uses (2**relevance - 1) / log2(rank + 1); IDCG sorts all judged grades.
Unknowns retain their rank and contribute no *observed* gain, never a judgment
of nonrelevance. Both metrics are conditional pooled estimates. Queries without
positive judgments have null metrics and are excluded from macro averages;
missing result rows for evaluable queries score zero and remain in the average.
Coverage divides by actual retrieved unique documents, not padded k slots.

CLI example::

    python benchmarks/tools/evalops/score_retrieval.py \
        --qrels benchmarks/experiments/evalops/qrels-v0.jsonl \
        --results run.jsonl --k 5 --k 10 --output report.json

Pool metadata is operator-supplied, never inferred from seed provenance or ranks.
No optional packages, network, label modification, or retrieval tuning is used.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "evalops.retrieval.v1"
QREL_FIELDS = {"query_id", "query", "doc_id", "relevance", "source", "later_doc_id", "evidence"}


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _object(row: Any, label: str, required: set[str], allowed: set[str]) -> None:
    if not isinstance(row, Mapping):
        raise ValueError(f"{label} must be an object")
    missing = required - row.keys()
    if missing:
        raise ValueError(f"{label} missing fields: {sorted(missing)}")
    extra = row.keys() - allowed
    if extra:
        raise ValueError(f"{label} unexpected fields: {sorted(map(str, extra))}")


def _ratio(numerator: float, denominator: float, undefined: str) -> dict[str, Any]:
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
        "status": "ok" if denominator else undefined,
    }


def _dcg(grades: Iterable[int | None]) -> float:
    return math.fsum((2**grade - 1) / math.log2(rank + 1)
                     for rank, grade in enumerate(grades, 1) if grade is not None)


def score(
    qrels: Iterable[Mapping[str, Any]],
    results: Iterable[Mapping[str, Any]],
    ks: Iterable[int],
    *,
    pool_depth: int | None = None,
    pool_contributors: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return versioned pooled estimates; invalid data raises ValueError.

    Inputs are not mutated. Query rows and k values are sorted in the report;
    ranked IDs retain the first occurrence and input rank breaks grade ties.
    An empty results iterable is valid; an empty qrels collection is an error.
    See the module docstring for null, exclusion, and coverage semantics.
    """
    cutoffs = sorted({_positive_int(k, "k") for k in ks})
    if not cutoffs:
        raise ValueError("ks must contain at least one k")
    if pool_depth is not None:
        _positive_int(pool_depth, "pool_depth")
    contributors = None
    if pool_contributors is not None:
        if isinstance(pool_contributors, (str, bytes)):
            raise ValueError("pool_contributors must be an iterable of names, not a string")
        contributors = sorted({_text(name, "pool_contributor") for name in pool_contributors}) or None

    queries: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(qrels, 1):
        label = f"qrels row {number}"
        _object(row, label, {"query_id", "query", "doc_id"}, QREL_FIELDS)
        query_id = _text(row["query_id"], f"{label} query_id")
        query = _text(row["query"], f"{label} query")
        doc_id = _text(row["doc_id"], f"{label} doc_id")
        grade = row.get("relevance")
        if grade is not None and (type(grade) is not int or grade not in (0, 1, 2)):
            raise ValueError(f"{label} relevance must be an integer 0..2 or null")
        if "source" in row:
            _text(row["source"], f"{label} source")
        for field in ("later_doc_id", "evidence"):
            if row.get(field) is not None:
                _text(row[field], f"{label} {field}")
        entry = queries.setdefault(query_id, {"query": query, "grades": {}})
        if entry["query"] != query:
            raise ValueError(f"{label} conflicting query text for {query_id!r}")
        if doc_id in entry["grades"]:
            raise ValueError(f"{label} duplicate qrel pair {(query_id, doc_id)!r}")
        entry["grades"][doc_id] = grade
    if not queries:
        raise ValueError("qrels must not be empty")

    rankings: dict[str, list[str]] = {}
    duplicates = {}
    for number, row in enumerate(results, 1):
        label = f"results row {number}"
        fields = {"query_id", "doc_ids"}
        _object(row, label, fields, fields)
        query_id = _text(row["query_id"], f"{label} query_id")
        if query_id not in queries:
            raise ValueError(f"{label} unknown query_id {query_id!r}")
        if query_id in rankings:
            raise ValueError(f"{label} duplicate result query_id {query_id!r}")
        if not isinstance(row["doc_ids"], list):
            raise ValueError(f"{label} doc_ids must be a ranked list")
        docs = [_text(doc, f"{label} doc_ids item") for doc in row["doc_ids"]]
        rankings[query_id] = list(dict.fromkeys(docs))
        duplicates[query_id] = len(docs) - len(rankings[query_id])

    per_query = []
    for query_id, entry in sorted(queries.items()):
        grades = entry["grades"]
        judged = [grade for grade in grades.values() if grade is not None]
        relevant = sum(grade > 0 for grade in judged)
        status = "ok" if relevant else "no_relevant_judgments"
        docs = rankings.get(query_id, [])
        metrics = {}
        for k in cutoffs:
            top = docs[:k]
            observed = [grades.get(doc) for doc in top]
            unknown = [doc for doc in top if grades.get(doc) is None]
            hits = sum(grade is not None and grade > 0 for grade in observed)
            metrics[str(k)] = {
                "recall_at_k": _ratio(hits, relevant, "no_relevant_judgments"),
                "ndcg_at_k": _ratio(_dcg(observed), _dcg(sorted(judged, reverse=True)[:k]),
                                    "no_relevant_judgments"),
                "coverage": {
                    "retrieved": len(top),
                    "judged": len(top) - len(unknown),
                    "unjudged": len(unknown),
                    "judgment_coverage": (len(top) - len(unknown)) / len(top) if top else None,
                    "unjudged_at_k": len(unknown) / len(top) if top else None,
                    "unjudged_doc_ids": unknown,
                },
            }
        per_query.append({
            "query_id": query_id,
            "query": entry["query"],
            "status": status,
            "results_status": "present" if query_id in rankings else "missing",
            "judged_doc_count": len(judged),
            "unknown_qrel_count": len(grades) - len(judged),
            "relevant_doc_count": relevant,
            "retrieved_doc_count": len(docs),
            "duplicate_doc_count": duplicates.get(query_id, 0),
            "ranked_results": [
                {"doc_id": doc, "relevance": grades.get(doc),
                 "judgment": "UNKNOWN" if grades.get(doc) is None else "judged"}
                for doc in docs
            ],
            "metrics": metrics,
        })

    evaluable = [query for query in per_query if query["relevant_doc_count"]]
    macro = {}
    for k in cutoffs:
        key = str(k)
        aggregate = {
            name: _ratio(math.fsum(query["metrics"][key][name]["value"] for query in evaluable),
                         len(evaluable), "no_evaluable_queries")
            for name in ("recall_at_k", "ndcg_at_k")
        }
        totals = {name: sum(query["metrics"][key]["coverage"][name] for query in per_query)
                  for name in ("retrieved", "judged", "unjudged")}
        aggregate["coverage"] = {
            "judgment_coverage": _ratio(totals["judged"], totals["retrieved"], "no_retrieved_docs"),
            "unjudged_at_k": _ratio(totals["unjudged"], totals["retrieved"], "no_retrieved_docs"),
        }
        macro[key] = aggregate

    supplied = (pool_depth is not None) + (contributors is not None)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok" if evaluable else "no_evaluable_queries",
        "estimate": "conditional_pooled",
        "ks": cutoffs,
        "pool": {
            "depth": pool_depth,
            "contributors": contributors,
            "metadata_status": ("unknown", "partially_supplied", "supplied")[supplied],
            "completeness": "unknown",
        },
        # [EVAL-24] Retrieval needs a test collection; [EVAL-25] Pool judgments; disclose incompleteness.
        # Introduction to Information Retrieval, ch. 8 (Canon v0.26.2).
        "limitations": (
            "Conditional pooled estimates, not exhaustive collection recall. Unpooled documents and null/missing "
            "relevance are UNKNOWN, not judged nonrelevant. Unknowns retain rank and contribute no observed DCG gain "
            "or recall hit. Pool depth and contributors are unknown unless supplied; supplied metadata does not "
            "establish completeness. Incomplete or single-strategy pools can bias system comparisons."
        ),
        "semantics": {
            "macro": "Equal query weights; null metrics excluded, missing results score zero for evaluable queries.",
            "recall_at_k": "Positive judged hits / positive judgments for that query.",
            "ndcg_at_k": "DCG / ideal DCG from judged grades; gain=(2^rel-1), discount=log2(rank+1).",
            "undefined": "No positive judgments: recall and nDCG null, query excluded from both macro denominators.",
            "coverage": "Judged or unjudged / actual unique retrieved docs at k; null for no retrieval. "
                        "Aggregate coverage pools document counts across all qrel queries.",
            "macro_numerator": "Sum of defined per-query metric values; denominator is evaluable query count.",
        },
        "counts": {
            "query_count": len(queries),
            "result_query_count": len(rankings),
            "missing_result_query_count": len(queries) - len(rankings),
            "judgment_count": sum(query["judged_doc_count"] for query in per_query),
            "unknown_qrel_count": sum(query["unknown_qrel_count"] for query in per_query),
            "evaluable_query_count": len(evaluable),
            "excluded_query_count": len(queries) - len(evaluable),
        },
        "per_query": per_query,
        "macro": macro,
    }


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def load_jsonl(path: str | Path) -> list[Any]:
    """Load strict UTF-8 JSONL, preserving physical line numbers in parse errors."""
    rows = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line, object_pairs_hook=_json_object, parse_constant=_invalid_constant))
                except ValueError as exc:
                    raise ValueError(f"{path}: line {number}: {exc}") from exc
    return rows


def write_report(path: Path, payload: str) -> None:
    """Replace an output report atomically; failed writes preserve the previous file."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qrels", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--k", type=int, action="append", required=True)
    parser.add_argument("--pool-depth", type=int)
    parser.add_argument("--pool-contributor", action="append")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.output is not None:
            for source in (args.qrels, args.results):
                if args.output.resolve() == source.resolve() or (
                    args.output.exists() and source.exists() and args.output.samefile(source)
                ):
                    raise ValueError(f"output must not overwrite input {source}")
        report = score(load_jsonl(args.qrels), load_jsonl(args.results), args.k,
                       pool_depth=args.pool_depth, pool_contributors=args.pool_contributor)
        payload = json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2) + "\n"
        if args.output is not None:
            write_report(args.output, payload)
        sys.stdout.write(payload)
        return 0
    # [AGT-10] Degrade loudly, The Art of UNIX Programming, ch. 1 (Canon v0.26.2).
    except (ValueError, OSError, UnicodeError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "error", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Import pinned provider observations and form a pool; never execute retrieval.

Run with --check to verify committed artifacts without writing. The default
rebuilds artifacts/ here only, after validating all inputs. Stdlib, no network.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCORER = ROOT / "benchmarks/tools/evalops/score_retrieval.py"
PREFIXES = {"decision": "dec", "finding": "finding", "blocker": "blocker", "handoff_state": "handoff"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()


def jsonl(rows):
    return "".join(json.dumps(r, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n" for r in rows).encode()


def scorer():
    spec = importlib.util.spec_from_file_location("evalops_score_retrieval", SCORER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse(data, api):
    return json.loads(data, object_pairs_hook=api._json_object, parse_constant=api._invalid_constant)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def doc_id(hit):
    kind = hit.get("entity_kind")
    entity = hit.get("entity_id")
    require(text(kind) and kind.count(".") == 1, "invalid entity_kind")
    family, field = kind.split(".")
    require(family in PREFIXES and text(field) and text(entity), "unknown entity identity")
    return f"{PREFIXES[family]}-{entity}"


def read_pinned(base, pin, api, inputs):
    path = (base / pin["path"]).resolve()
    require(path.is_relative_to((base / "inputs").resolve()), "snapshot must be inside inputs/")
    data = path.read_bytes()
    require(digest(data) == pin["sha256"], f"input hash mismatch: {pin['path']}")
    inputs[pin["path"]] = {"sha256": digest(data), "bytes": len(data)}
    return data


def build(base=HERE):
    """Return deterministic artifact bytes; no input mutation or label creation."""
    api = scorer()
    protocol_bytes = (base / "protocol.json").read_bytes()
    protocol = parse(protocol_bytes, api)
    require(protocol["schema"] == "evalops.retrieval-pool-protocol.v1", "unknown protocol")
    depth = protocol["pool"]["field_depth"]
    require(type(depth) is int and 0 < depth <= 100, "invalid field depth")
    inputs = {"protocol.json": {"sha256": digest(protocol_bytes), "bytes": len(protocol_bytes)}}
    seed_bytes = read_pinned(base, protocol["seed_qrels"], api, inputs)
    seeds = [parse(line, api) for line in seed_bytes.decode().splitlines() if line.strip()]
    # Reuse existing validation and metric semantics, including UNKNOWN handling.
    api.score(seeds, [], protocol["pool"]["ks"])
    queries = {r["query_id"]: r["query"] for r in seeds}
    grades = {(r["query_id"], r["doc_id"]): r for r in seeds}
    corpus = {}

    def document(identity):
        return corpus.setdefault(identity, {"doc_id": identity, "observations": [], "seed_references": []})

    for r in seeds:
        document(r["doc_id"])["seed_references"].append(r["query_id"])
    pool = {}
    runs = []
    artifacts = {}
    strategy_ids = [s["strategy_id"] for s in protocol["strategies"]]
    require(len(set(strategy_ids)) == len(strategy_ids), "duplicate strategy_id")
    require(all(text(s) and all(c.isalnum() or c == "-" for c in s) for s in strategy_ids), "invalid strategy_id")
    for strategy in sorted(protocol["strategies"], key=lambda s: s["strategy_id"]):
        name = strategy["strategy_id"]
        pin = strategy["snapshot"]
        if pin is None:
            runs.append({"strategy_id": name, "status": "unavailable", "reason": strategy["reason"],
                         "results_file": None, "queries": [{"query_id": q, "status": "unavailable",
                         "returned_field_count": None, "unique_document_count": None} for q in sorted(queries)],
                         "usage": None})
            continue
        raw = read_pinned(base, pin, api, inputs)
        snapshot = parse(raw, api)
        require(snapshot["schema"] == pin["schema"] == "acx-retrieval-observation/1", "unknown snapshot schema")
        require(snapshot["query_set"] == "qrels-v0-seed-dev-not-heldout" and snapshot["corpus"] == "handoff.db",
                "snapshot query set/corpus mismatch")
        require(isinstance(snapshot["results"], list), "snapshot results must be a list")
        by_query = {}
        for row_index, row in enumerate(snapshot["results"]):
            q = row["query_id"]
            require(q in queries and row["query"] == queries[q], "foreign query or query text mismatch")
            require(q not in by_query, "duplicate provider query")
            by_query[q] = (row_index, row)
        require(by_query.keys() == queries.keys(), "snapshot query coverage mismatch")
        results, query_runs = [], []
        for q, (row_index, row) in sorted(by_query.items()):
            hits = row["results"]
            require(type(row["ok"]) is bool and isinstance(hits, list), "invalid provider response")
            if not row["ok"]:
                require(not hits, "unavailable provider response contains ranks")
                query_runs.append({"query_id": q, "status": "unavailable", "provider_status": row["status"],
                                   "returned_field_count": None, "unique_document_count": None})
                continue
            require(row["status"] in ("ok_with_results", "ok_no_results"), "unknown successful provider status")
            require((row["status"] == "ok_with_results") == bool(hits), "provider status/results mismatch")
            for key, value in strategy["provider"].items():
                require(row.get(key) == value, f"provider config mismatch: {key}")
            ranked, contributions = [], {}
            for rank, hit in enumerate(hits, 1):
                identity = doc_id(hit)
                value = hit["score"]
                require(type(value) in (float, int) and math.isfinite(value), "invalid provider score")
                require(hit["snippet"] is None or isinstance(hit["snippet"], str), "invalid snippet")
                require(hit["task_ref"] is None or text(hit["task_ref"]), "invalid task_ref")
                require(hit["model_id"] == strategy["provider"]["query_model_id"], "hit model mismatch")
                # Validate all hits; pool only the configured provider field slots.
                if rank > depth:
                    continue
                pointer = f"/results/{row_index}/results/{rank - 1}"
                observation = {"strategy_id": name, "query_id": q, "provider_rank": rank,
                               "snapshot_sha256": pin["sha256"], "json_pointer": pointer,
                               "hit_sha256": digest(encoded(hit)), **hit}
                document(identity)["observations"].append(observation)
                if identity not in contributions:
                    ranked.append(identity)
                    contributions[identity] = {"strategy_id": name, "document_rank": len(ranked),
                                               "first_provider_rank": rank, "provider_hits": []}
                contributions[identity]["provider_hits"].append({"provider_rank": rank, "score": value,
                        "entity_kind": hit["entity_kind"], "json_pointer": pointer, "snapshot_sha256": pin["sha256"]})
            for identity, contributor in contributions.items():
                pool.setdefault((q, identity), []).append(contributor)
            results.append({"query_id": q, "doc_ids": ranked})
            query_runs.append({"query_id": q, "status": "available", "provider_status": row["status"],
                               "returned_field_count": len(hits), "selected_field_count": min(depth, len(hits)),
                               "unique_document_count": len(ranked)})
        result_file = f"results/{name}.jsonl" if results else None
        if result_file is not None:
            artifacts[result_file] = jsonl(results)
        runs.append({"strategy_id": name, "status": ("available" if len(results) == len(queries)
                                                     else "partial" if results else "unavailable"),
                     "snapshot_sha256": pin["sha256"], "provider": strategy["provider"],
                     "results_file": result_file, "queries": query_runs, "usage": None})

    contributors = sorted({c["strategy_id"] for cs in pool.values() for c in cs})
    qrels = dict(grades)
    pool_rows = []
    for (q, identity), cs in sorted(pool.items()):
        seed = grades.get((q, identity))
        row = {"query_id": q, "doc_id": identity, "contributors": sorted(cs, key=lambda c: c["strategy_id"]),
               "relevance": seed["relevance"] if seed else None,
               "judgment_status": "qualified_seed" if seed and seed.get("relevance") is not None else "UNKNOWN",
               "independent_relevance": None, "independent_judgment_status": "unavailable",
               "seed_source": seed.get("source") if seed else None}
        pool_rows.append(row)
        if seed is None:
            qrels[q, identity] = {"query_id": q, "query": queries[q], "doc_id": identity,
                                 "relevance": None, "source": "unjudged_pool"}
    for d in corpus.values():
        d["seed_references"] = sorted(set(d["seed_references"]))
        d["content_status"] = "provider_snippets_only" if d["observations"] else "reference_only_content_unknown"
        d["full_content_sha256"] = None
    artifacts.update({
        "queries.jsonl": jsonl({"query_id": q, "query": t, "split": "seed_dev",
                               "untouched_heldout": False, "source": "qrels-v0"} for q, t in sorted(queries.items())),
        "corpus.jsonl": jsonl(corpus[k] for k in sorted(corpus)),
        "qrels.jsonl": jsonl(qrels[k] for k in sorted(qrels)),
        "pool.jsonl": jsonl(pool_rows),
        "runs.json": encoded({"schema": "evalops.retrieval-runs.v1", "runs": runs}),
    })
    for run in runs:
        if run["results_file"] is None:
            continue
        results = [parse(line, api) for line in artifacts[run["results_file"]].splitlines()]
        available = {r["query_id"] for r in results}
        # Unavailable provider queries must not become missing-result zero scores.
        diagnostic = api.score([v for (q, _), v in sorted(qrels.items()) if q in available], results,
                               protocol["pool"]["ks"], pool_depth=depth, pool_contributors=contributors) if available else None
        artifacts[f"scores/{run['strategy_id']}.json"] = encoded({
            "purpose": "qualified_seed_diagnostic_only", "independent_gold": False,
            "acceptance": "not_evaluated", "unavailable_query_ids": sorted(set(queries) - available),
            "pool_depth_unit": "provider_field_slots_before_record_deduplication", "payload": diagnostic})
    artifacts["manifest.json"] = encoded({
        "schema": "evalops.retrieval-artifacts.v1", "protocol_sha256": digest(protocol_bytes),
        "source": protocol["source"], "inputs": inputs,
        "code": {"import_pool.py": digest(Path(__file__).read_bytes()),
                 "benchmarks/tools/evalops/score_retrieval.py": digest(SCORER.read_bytes())},
        "artifacts": {p: {"sha256": digest(b), "bytes": len(b)} for p, b in sorted(artifacts.items())},
        "counts": {"queries": len(queries), "untouched_heldout_queries": 0, "corpus_references": len(corpus),
                   "pool_pairs": len(pool), "seed_pairs": len(seeds),
                   "pool_pairs_with_seed_grade": sum(r["judgment_status"] == "qualified_seed" for r in pool_rows),
                   "independent_judgments": 0},
        "pool": {**protocol["pool"], "actual_contributors": contributors,
                 "unavailable_strategies": sorted(r["strategy_id"] for r in runs if r["results_file"] is None)},
        "corpus": protocol["corpus"], "acceptance": protocol["acceptance"],
        "generation_faithfulness": protocol["generation_faithfulness"], "usage": None,
    })
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        artifacts = build()
        target = HERE / "artifacts"
        existing = {str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()}
        require(not existing - artifacts.keys(), "unexpected artifact files; preserve and reconcile explicitly")
        if args.check:
            require(existing == artifacts.keys(), "missing artifact files")
            for name, data in artifacts.items():
                require((target / name).read_bytes() == data, f"artifact mismatch: {name}")
        else:
            for name, data in artifacts.items():
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                scorer().write_report(path, data.decode())
        print(json.dumps({"status": "verified" if args.check else "generated", "files": len(artifacts),
                          "quality_acceptance": "not_evaluated"}, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

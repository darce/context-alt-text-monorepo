"""Bounded importer behavior; mutated snapshots here are synthetic test inputs only."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("import_pool", HERE / "import_pool.py")
pool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pool)
# Generated observation lineage, with foreign values a provider hit must not substitute.
LINEAGE = {"strategy_id": "foreign", "query_id": "q-foreign", "provider_rank": 99,
           "snapshot_sha256": "0" * 64, "json_pointer": "/wrong", "hit_sha256": "f" * 64}


def rows(data):
    return [json.loads(line) for line in data.splitlines()]


def assert_lineage(built, base):
    """Walk pool contributor hits to pinned raw hits; corpus observations must match both."""
    protocol = json.loads((base / "protocol.json").read_bytes())
    pins = {s["strategy_id"]: s["snapshot"]["sha256"] for s in protocol["strategies"] if s["snapshot"]}
    raw = {s["snapshot"]["sha256"]: json.loads((base / s["snapshot"]["path"]).read_bytes())
           for s in protocol["strategies"] if s["snapshot"]}
    expected = []
    for r in rows(built["pool.jsonl"]):
        for c in r["contributors"]:
            for h in c["provider_hits"]:
                _, _, qi, _, hi = h["json_pointer"].split("/")
                provider = raw[pins[c["strategy_id"]]]["results"][int(qi)]
                hit = provider["results"][int(hi)]
                assert (provider["query_id"], int(hi) + 1, pool.doc_id(hit), h["snapshot_sha256"]) == (
                    r["query_id"], h["provider_rank"], r["doc_id"], pins[c["strategy_id"]])
                expected.append((r["doc_id"], {
                    "strategy_id": c["strategy_id"], "query_id": r["query_id"], "provider_rank": h["provider_rank"],
                    "snapshot_sha256": h["snapshot_sha256"], "json_pointer": h["json_pointer"],
                    "hit_sha256": pool.digest(pool.encoded(hit))}, hit))
    observed = [(d["doc_id"], {k: o[k] for k in LINEAGE}, {k: v for k, v in o.items() if k not in LINEAGE})
                for d in rows(built["corpus.jsonl"]) for o in d["observations"]]

    def canonical(item):
        return json.dumps(item, sort_keys=True)

    # One observation per contributor hit: generated lineage agrees, every raw field (null included) survives.
    assert sorted(observed, key=canonical) == sorted(expected, key=canonical)


def fixture(tmp_path, mutate=None, second=False):
    """Pin deliberate test mutations, so semantic checks run past hash checks."""
    (tmp_path / "inputs").mkdir()
    protocol = json.loads((HERE / "protocol.json").read_bytes())
    raw = json.loads((HERE / "inputs/dense-retrieval.json").read_bytes())
    if mutate:
        mutate(raw)
    data = pool.encoded(raw)
    (tmp_path / "inputs/dense-retrieval.json").write_bytes(data)
    dense = next(s for s in protocol["strategies"] if s["strategy_id"] == "gte-dense")
    dense["snapshot"]["sha256"] = pool.digest(data)
    (tmp_path / "inputs/qrels-v0.jsonl").write_bytes((HERE / "inputs/qrels-v0.jsonl").read_bytes())
    if second:
        other = copy.deepcopy(dense)
        other["strategy_id"] = "synthetic-second"
        other["snapshot"]["path"] = "inputs/second.json"
        raw["results"][0]["results"] = list(reversed(raw["results"][0]["results"]))
        raw["results"][0]["results"][0]["entity_id"] = "synthetic-unjudged"
        data = pool.encoded(raw)
        (tmp_path / "inputs/second.json").write_bytes(data)
        other["snapshot"]["sha256"] = pool.digest(data)
        protocol["strategies"].append(other)
    (tmp_path / "protocol.json").write_bytes(pool.encoded(protocol))
    return tmp_path


def test_frozen_artifacts_trace_to_provider_and_matched_corpus():
    built = pool.build()
    assert all((HERE / "artifacts" / name).read_bytes() == data for name, data in built.items())
    raw = json.loads((HERE / "inputs/dense-retrieval.json").read_bytes())
    corpus = {r["doc_id"]: r for r in rows(built["corpus.jsonl"])}
    rankings = {r["query_id"]: r["doc_ids"] for r in rows(built["results/gte-dense.jsonl"])}
    for provider in raw["results"]:
        expected = list(dict.fromkeys(pool.doc_id(h) for h in provider["results"][:8]))
        assert rankings[provider["query_id"]] == expected
        assert set(expected) <= corpus.keys()
    for d in corpus.values():
        assert d["full_content_sha256"] is None
        for obs in d["observations"]:
            _, _, qi, _, hi = obs["json_pointer"].split("/")
            hit = raw["results"][int(qi)]["results"][int(hi)]
            assert pool.doc_id(hit) == d["doc_id"]
            assert obs["hit_sha256"] == pool.digest(pool.encoded(hit))
            assert all(obs[k] == v for k, v in hit.items())
    assert_lineage(built, HERE)


def test_pool_is_not_gold_and_seed_provenance_is_preserved():
    built = pool.build()
    seeds = rows((HERE / "inputs/qrels-v0.jsonl").read_bytes())
    qrels = {(r["query_id"], r["doc_id"]): r for r in rows(built["qrels.jsonl"])}
    for seed in seeds:
        assert qrels[seed["query_id"], seed["doc_id"]] == seed
    pooled = rows(built["pool.jsonl"])
    assert len({(r["query_id"], r["doc_id"]) for r in pooled}) == len(pooled)
    assert all(r["independent_relevance"] is None for r in pooled)
    unknown = [r for r in pooled if r["judgment_status"] == "UNKNOWN"]
    assert unknown and all(r["relevance"] is None for r in unknown)
    assert all(qrels[r["query_id"], r["doc_id"]]["relevance"] is None for r in unknown)
    report = json.loads(built["scores/gte-dense.json"])
    assert report["independent_gold"] is False
    assert report["payload"]["counts"]["judgment_count"] == len(seeds)
    assert report["payload"]["counts"]["unknown_qrel_count"] == len(unknown)
    assert all(not r["untouched_heldout"] and r["split"] == "seed_dev" for r in rows(built["queries.jsonl"]))


def test_multistrategy_union_preserves_contributors_and_first_record_rank(tmp_path):
    base = fixture(tmp_path, second=True)
    built = pool.build(base)
    original = rows(built["results/gte-dense.jsonl"])
    other = rows(built["results/synthetic-second.jsonl"])
    assert original[0]["doc_ids"][:-1] == list(reversed(other[0]["doc_ids"][1:]))
    expected_union = {(r["query_id"], d) for r in original + other for d in r["doc_ids"]}
    pooled = rows(built["pool.jsonl"])
    assert {(r["query_id"], r["doc_id"]) for r in pooled} == expected_union
    for r in pooled:
        expected_contributors = [name for name, ranks in [("gte-dense", original), ("synthetic-second", other)]
                                 if r["doc_id"] in next(q["doc_ids"] for q in ranks if q["query_id"] == r["query_id"])]
        assert [c["strategy_id"] for c in r["contributors"]] == expected_contributors
        for c in r["contributors"]:
            ranks = original if c["strategy_id"] == "gte-dense" else other
            ranking = next(q["doc_ids"] for q in ranks if q["query_id"] == r["query_id"])
            assert c["document_rank"] == ranking.index(r["doc_id"]) + 1
            assert c["first_provider_rank"] == c["provider_hits"][0]["provider_rank"]
    added = next(r for r in pooled if r["doc_id"].endswith("synthetic-unjudged"))
    assert added["relevance"] is None and added["independent_relevance"] is None
    assert_lineage(built, base)
    # Strategy declaration order cannot affect pool/rank artifact bytes.
    protocol = json.loads((base / "protocol.json").read_bytes())
    protocol["strategies"].reverse()
    (base / "protocol.json").write_bytes(pool.encoded(protocol))
    reordered = pool.build(base)
    assert {k: v for k, v in built.items() if k != "manifest.json"} == {
        k: v for k, v in reordered.items() if k != "manifest.json"}


def test_unavailable_strategies_have_no_rank_files_or_zero_scores():
    built = pool.build()
    runs = json.loads(built["runs.json"])["runs"]
    for run in runs:
        if run["strategy_id"] != "gte-dense":
            assert run["status"] == "unavailable" and run["results_file"] is None
            assert f"results/{run['strategy_id']}.jsonl" not in built
            assert f"scores/{run['strategy_id']}.json" not in built
            assert all(q["unique_document_count"] is None for q in run["queries"])
        assert run["usage"] is None


@pytest.mark.parametrize("all_queries", [False, True])
def test_provider_failure_is_unknown_not_missing_result_penalty(tmp_path, all_queries):
    def fail(raw):
        for r in raw["results"] if all_queries else raw["results"][:1]:
            r.update(ok=False, status="provider_unavailable", results=[])
    built = pool.build(fixture(tmp_path, fail))
    dense = next(r for r in json.loads(built["runs.json"])["runs"] if r["strategy_id"] == "gte-dense")
    assert dense["status"] == ("unavailable" if all_queries else "partial")
    if all_queries:
        assert dense["results_file"] is None
        assert "scores/gte-dense.json" not in built
    else:
        report = json.loads(built["scores/gte-dense.json"])
        assert report["unavailable_query_ids"] == ["q-000"]
        assert report["payload"]["counts"]["query_count"] == 26
        assert report["payload"]["counts"]["missing_result_query_count"] == 0


@pytest.mark.parametrize("mutate,message", [
    (lambda x: x["results"].append(x["results"][0]), "duplicate provider query"),
    (lambda x: x["results"].pop(), "query coverage mismatch"),
    (lambda x: x["results"][0].update(query="foreign text"), "query text mismatch"),
    (lambda x: x["results"][0]["results"][0].update(entity_kind="unknown.field"), "unknown entity identity"),
    (lambda x: x["results"][0]["results"][0].update(score=True), "invalid provider score"),
    (lambda x: x["results"][0].update(query_model_id="other-model"), "provider config mismatch"),
])
def test_semantic_mismatches_rejected_even_with_valid_hash(tmp_path, mutate, message):
    with pytest.raises(ValueError, match=message):
        pool.build(fixture(tmp_path, mutate))


@pytest.mark.parametrize("null", [False, True], ids=["foreign", "null"])
@pytest.mark.parametrize("key", LINEAGE)
def test_provider_hit_cannot_replace_generated_lineage(tmp_path, key, null):
    def collide(raw):
        raw["results"][0]["results"][0][key] = None if null else LINEAGE[key]
    base = fixture(tmp_path, collide)
    # Fail closed; were the build accepted, the lineage walk names the replaced field.
    with pytest.raises(ValueError, match=f"collides with generated lineage: {key}"):
        assert_lineage(pool.build(base), base)


def test_unpinned_input_rejected_before_artifact_generation(tmp_path):
    base = fixture(tmp_path)
    path = base / "inputs/dense-retrieval.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="input hash mismatch"):
        pool.build(base)
    assert not (base / "artifacts").exists()

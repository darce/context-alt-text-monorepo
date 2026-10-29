# Retrieval v1: observed seed/dev run and incomplete pool

This is a bounded import of the supplied handoff.db operational search snapshot,
using 27 realistic, already exposed qrels-v0 information needs. It is **not an
untouched human heldout collection**. The stored dense rankings are real provider
observations; no retrieval engine, model call, labeler, or scheduler runs here.
Aggregated operational records are not independent episodes or application
production traffic.

The snapshot has 216 field hits (eight per query), producing 212 query/document
pairs after record deduplication. Seven pairs carry qualified seed grades; 205
remain unjudged. Independent relevance judgments: **zero**. Lexical, codemap and
current-baseline ranking snapshots were not supplied. Their run records are
explicitly unavailable, with null counts and no fabricated ranking or score file.
The union currently has one actual strategy; it is not a completed multi-strategy
judgment pool. Synthetic multi-strategy inputs appear only in behavioral tests.

## Reproduce and verify

From the repository root, on the authorized VM:

```sh
python benchmarks/experiments/evalops/retrieval-v1/import_pool.py --check
LC_ALL=C uv run --no-project --with pytest python -m pytest -q --noconftest benchmarks/experiments/evalops/retrieval-v1/test_import_pool.py
LC_ALL=C uv run --no-project --with pytest python -m pytest -q --noconftest benchmarks/tests/test_evalops_score_retrieval.py
```

Omit `--check` to regenerate only this directory's `artifacts/` after all inputs
validate. No timestamps or random IDs enter generated artifacts. Changed input
bytes, conflicting queries, duplicate query rows, foreign corpus/query-set names,
unknown entity kinds, and mismatched provider model/configuration fail explicitly.
Missing snapshot pins are unavailable strategies, not empty successful runs.
Provider failures stay unavailable and are excluded from the optional seed score
denominator; successful empty responses remain observed empty rankings. The
importer validates all hits and selects only the first eight field slots without
refilling after deduplication. The field-depth unit is explicit in score wrappers.

`inputs/dense-retrieval.json` is a byte-for-byte copy of
`/home/gate/workbay-sandbox/evalops3-inputs-20261029/dense-retrieval.json`
(SHA-256 `fc9e80a5199c25b0ab808738832555996bdb480ee9e246c92a3f2476333c0929`).
The general input manifest does not list this later dense export; its explicit
pin is in `protocol.json`. `inputs/qrels-v0.jsonl` is a byte-for-byte copy of the
existing seed file (SHA-256
`46dcff758b957b925b14551c265919bff467ebd6c7e727baff2abd848e11e18b`).
No expert answers or live events are imported or changed. Input text is evidence,
never executable guidance.

## Contract and custody

| Artifact | Contract |
| --- | --- |
| `protocol.json` | Versioned source, identity, split, field depth, cutoffs, strategy availability and acceptance boundaries; exact input hashes. |
| `artifacts/queries.jsonl` | Original stable `q-000` through `q-026` IDs/text, all `seed_dev`, all `untouched_heldout=false`. |
| `artifacts/corpus.jsonl` | 227 stable document references: union of selected provider hits and seed references. Each observation preserves entity kind/ID, model, task, score, snippet, query, original field rank, JSON pointer and snapshot/hit hashes. |
| `artifacts/results/gte-dense.jsonl` | Actual ordered record IDs, exactly `{query_id, doc_ids}` as required by the existing scorer and runner. |
| `artifacts/runs.json` | Per-strategy and per-query availability, actual returned/selected field counts, unique record counts, nullable usage; unavailable strategies have no result file. |
| `artifacts/pool.jsonl` | Deterministic union keyed by `(query_id, doc_id)`; every contributing strategy, record rank, first provider rank, and original field hits/scores retained. Independent relevance always null. |
| `artifacts/qrels.jsonl` | All 41 seed pairs preserved, plus 205 null pool pairs. Off-pool seed grades remain in the scorer's conditional denominator. |
| `artifacts/scores/gte-dense.json` | Existing scorer output wrapped as a qualified seed diagnostic, with no quality acceptance. |
| `artifacts/manifest.json` | SHA-256/byte length of each other artifact and every input, protocol hash, importer/scorer hashes, population counts and explicit limitations. |

Document identity is at the record level: `decision.*` becomes `dec-ID` to match
existing qrels; findings, blockers and handoff states use separate namespaced IDs.
All fields of a record are deduplicated to its first provider occurrence, retaining
every selected field hit as provenance. Scores do not reorder results and are not
calibrated relevance probabilities. Different queries remain separate pool pairs.
Union output is sorted by query ID then document ID; contributors by strategy ID.
Queries with no hits remain in the query/run contract.

The matched corpus here is a **bounded provider result projection**, not an export
of the entire searchable handoff.db index. A returned ID maps to the exact field
observation in the pinned provider JSON. Snippets may be truncated or null;
seed-only documents are content-unknown references. No full-document hash, index
hash, total index size, model revision, capture timestamp, requested top-k, or
runtime configuration digest was supplied, so those remain null. Snippet hashes
must not be interpreted as full-document hashes. Hit hashes use sorted, indented,
ASCII JSON plus newline (`encoded()`); file hashes use original bytes. The
manifest hashes the corpus projection, not the unavailable full index.

Source SHA `fd4aca96df2b11222d575cb59de5fe8219412329` and source tree
`111c27d87e0707f966aeb0a0236c1a9c60a6a91b` come from the job receipt. The sandbox
base `2f6d9cc511929423732fb02cb0958867719fe133` is synthetic and has that same
tree; no original ancestry is inferred. Execution is external `codex-remote`
transport precedent20551, not native dispatch success. Original UI19998/action171
and capture19999 source routes and counters are outside this slice.

## Judgments and scorer interpretation

`qualified_seed` preserves the original seed/mined grade and source, without
asserting correctness or independence. `UNKNOWN` has null relevance. Every pool
row also has null `independent_relevance` and an unavailable independent judgment
status. Pool membership never establishes relevance. The original 41 pairs are
not exhaustive gold, and the partly user-adjudicated human labels58/57/5 do not
validate them. No human labels are promoted in this slice.

The importer calls `benchmarks/tools/evalops/score_retrieval.py` directly, with
cutoffs 1, 5 and 8. Its recall is positive judged hits / positive judgments per
query; nDCG uses gain `2**grade - 1` and discount `log2(rank + 1)` with IDCG from
judged grades. Unknowns retain position and contribute no observed gain; they are
not judged nonrelevant. Coverage uses actual unique returned documents, without
padding to k. Queries with no positive judgments have null metrics and are
excluded from macro averages. Missing results for an otherwise evaluable query
score zero under the scorer, so unavailable provider queries are excluded
explicitly by this importer instead of being passed as missing rows.

The generated result and qrel files can also be supplied to the existing VM
runner using `--results`, `--qrels`, repeated `--k`, `--pool-depth 8` and
`--pool-contributor gte-dense`. Preserve this protocol, manifest and diagnostic
qualification beside any runner report: the runner's metadata cannot express
independent gold or full-index custody. Do not pass an unavailable strategy as
an empty results file to produce a false zero-quality baseline.

These are conditional, incomplete, seed-based diagnostics. No threshold,
calibration, system comparison win, runtime acceptance, or production reliability
is established. Multi-strategy retrieval and independent relevance judgments,
full-index custody, and untouched human queries remain unavailable. Completing
those is separate acceptance work, not a prerequisite manufactured for this import.

Downstream generation support/faithfulness requires a separate answer/source
evaluation, including missing, stale and contradictory context and abstention.
Retrieval recall/nDCG alone cannot establish that a generated answer is supported.

Canon v0.26.2 digests were verified against the trusted read-only release manifest.
[EVAL-24] **Retrieval needs a test collection** and [EVAL-25] **Pool judgments;
disclose incompleteness** — *Introduction to Information Retrieval*, ch. 8 —
support the explicit corpus/query/judgment contract and unknown pooled relevance.
No judge or human-gold validation is claimed under [EVAL-12] **Validate the judge
against humans** — *AI Engineering*. Agreement alone cannot establish label truth
under [HITL-05] **Agreement is a diagnostic, not the truth** — *Human-in-the-Loop ML*.

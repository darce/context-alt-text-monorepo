# S6b · CLI `report`, `compare`, `unseal`

- **Wave:** W3 batch C · **Depends on:** S6a merged; S2 cache persistence, S4 materialization and the S5 `render_report` contract; merges before S9 (`mk/evals.mk` is edited serially: S6a, S6b, S9)
- **Implemented boundary:** the CLI wires the report/compare/unseal commands and make targets to the producer contracts below. The comparison schema is `firbench_schemas/comparison-v1.json`. The locators below describe actual producers and schema. Source inspection proves interfaces and ordering; prior software receipts in the README do not establish a real run or real-data acceptance.
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_cli.py`
  - `mk/evals.mk`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_cli.py`

## Dependency and data-field edges

| Subcommand | Required inputs and producer contracts | Writes |
| --- | --- | --- |
| `report` | S2/runtime `legs/<leg_key>/cache.npz` (frozen MCP 16869), `frame.json`, `scores.json` and run declarations. S4 implemented API `materialize_clusters(run_dir, *, config=None, prior_run_dir=None) -> Path`, then S5 frozen `render_report(run_dir, *, out_dir, include_crops=False) -> Path`. | `clusters.json`, then `<run_dir>/report/` |
| `compare` | Two completed runs: `manifest.json` `firbench` block, `scores.json`, `legs/<leg_key>/searches.jsonl`. Frozen `compare_runs(run_a, run_b, *, out_dir, treatment, repo_root) -> Path` and `comparison-v1`. | `comparison.json` under `--out` |
| `unseal` | `firbench_contract.require_verdict_allowed(manifest, *, frame)`, genuine ratification and a valid seal with prerequisite evidence. The private unseal ledger is read by S6a. | One unspent `UnsealToken` row appended to `unseal-ledger.jsonl` |

Implemented joins and preserved requirements:

- **Token record.** `unseal` appends the token before the run exists. S6a `run` writes `manifest.firbench.unseal_token_ref` (a sha256 of the consumed token body without `consumed_at`) when it consumes that token. Do not mutate a future run manifest during `unseal`.
- **Report join.** S2/runtime owns actual-execution cache persistence; S4 owns materialization through the API above; S5 owns rendering. `report_run` imports both, calls materialization, then rendering. See [README runtime and consumer contracts](README.md#runtime-and-consumer-contracts); a missing private binding is an input-availability condition, not proof of an unimplemented runtime.
- **Merge order.** S6a → S6b → S9 on `mk/evals.mk`. S6b appends after S6a's targets. The test file is shared with S6a; S6b adds tests after S6a merges.

## Build

1. **`report <run_dir> [--include-crops]`.** Calls `materialize_clusters(run_dir)` first, then `render_report(run_dir, out_dir=<run_dir>/report/, include_crops=...)`.
   - Implemented S4 join: `materialize_clusters(run_dir, *, config=None, prior_run_dir=None) -> Path` builds cluster inputs from persisted run declarations, the leg caches, `frame.json` and `scores.json`, validates bindings, and writes `clusters.json`. It reads no private pixels and reruns no model. The default CLI call uses `materialize_clusters(run_dir)` without new flags.
   - Cache rows are exactly the S2 executions recorded in the frozen cache (README, Leg cache). The report must not reconstruct vectors from top-k lists or invent held-out verification.
   - An independent cache reader validates the frozen metadata, arrays, types/shapes, indexes, duplicates, exact leg key and frame image-SHA bindings. Malformed/mismatched evidence raises `FrameContractError`; genuinely absent cache, no embedded GT or missing chaining provenance produces a named `unavailable` entry. It makes no zero-risk claim.
   - `--include-crops` is an explicit, authorized, bounded read. It never reopens a sealed frame for replay.
   - The source implements materialize-before-render ordering. S4 validates inputs even when `clusters.json` exists, accepts identical canonical bytes and refuses a conflict. Private-output, sealed-read and pinned-receipt replay rules remain binding; no real-data pass follows from this ordering.
2. **`compare <run_a> <run_b> --out <dir> [--treatment <field>]`.** The frozen S0 contract is `compare_runs(run_a, run_b, *, out_dir, treatment, repo_root) -> Path`, returning the `comparison.json` path. Feeds S6 of the report.
   - **Provenance before metrics/output.** `_run_identity` validates actual private-contained decision/frame/search/score/timing files through S0/S3 readers, including raw decision SHA/object binding, full leg/arm/fold registry, native gallery hash basis, GT/PSU/weight/fold context, score policy and receipt SHA. `_compatibility_scores(..., validate_outcomes=True)` checks persisted native calibration counts and FNIR against actual searches; comparison never refits τ or reopens pixels. It emits original `decision_sha256` and actual `scores_sha256` for each run.
   - **Compatibility key.** Built from validated persisted evidence: `estimand`, `fpir_target`, the decision sha without the declared treatment fields, `gallery` snapshot hash, enrolment and probe allocation, fold and calibration policy, `arm`, frame and annotation bytes, PSU and weighting policy, scorer, boundary semantics, and OpenCV and ORT versions. Each leg's `space_fingerprint` is compared as part of its leg key.
   - **Never treatable.** The frame id, face set, frame and annotation bytes, scorer, boundary semantics and OpenCV/ORT runtime. A difference in any of these refuses, with a message naming the field, even when `--treatment` is given.
   - **Leg contract.** A changed `space_fingerprint` is labelled "leg contract changed (expected)". Its derived gallery vector hash is exempted only for that changed leg with unchanged input lineage, membership and fold policy. An unexplained same-space/gallery-input change refuses. Outcomes may be compared across runs; vectors from different spaces never are (EMB-01, One embedding space per comparison, `lexicons/ml-systems.md#emb-01`; *Foundations of Vector Retrieval*, ch. 1).
   - **Treatment and original seals.** Exact supported names are `estimand`, `fpir_target`, `gallery_sha256`, `enrolment_probe_allocation`, `fold_calibration_policy`, `arm`, `psu_weighting_policy`. `_comparison_original_seal` validates the original S0 body/hash before `_without_treatment` removes exact allowed leaves. Any derived `seal.sha256` normalization is only an in-memory comparison digest, never a rewritten/ratified decision or replacement S0 seal. Seal timestamps, ratification and unrelated policy leaves stay binding; when an original ratified seal applies, `require_verdict_allowed` checks that original. A single undeclared factor refuses with its name. Arm-only replication of the same registry does not create another factor.
   - **Several undeclared fields.** Two or more undeclared supported factor differences may yield "exploratory: multi-factor, no verdict", with `delta` and `verdicts` null and descriptive per-leg rows only. This never overrides malformed evidence, never-treatable differences, unexplained gallery drift or unrelated policy/context refusal.
   - **Fixed cohort and direction.** `_comparison_snapshot` retains the full native mated primary-test probability GT cohort, including upstream misses, and requires identical face/PSU/weights across runs before any bootstrap. `_comparison_metrics` calls real S3 `finish_outcomes` and `paired_cluster_bootstrap` with pinned manifest draws/seed and reports FNIR(B) − FNIR(A), positive worse. Missing calibration/availability/floors remain named `not_scored`, never a smaller successful cohort. Comparable summaries retain the two original run verdict states; they do not invent a treatment verdict.
   - **Declared arms versus native summaries.** Native is the default comparison analysis arm. An explicit `analysis_arm` must belong to the declared arms; an arm-treatment profile with multiple attribution choices refuses as ambiguous. All declared searches/registry rows remain required even though `scores.legs` supplies native summaries. Attribution calibration absent from those summaries is named `analysis_arm_calibration_not_supplied`, not borrowed or fabricated.
   - Includes actual supplied-run per-leg history. τ spread is currently `unavailable` with `pooled_fit_threshold_no_per_fold_estimates`: S3 persists a pooled fit threshold/aggregate diagnostic, not fold-indexed estimates. Do not invent sparkline points. EXP-30, Disclose specification spread (`lexicons/epistemics.md#exp-30`; *Seeing with Fresh Eyes: Meaning, Space, Data, Truth*, ch. 4), requires disclosing this limit.
   - Writes `comparison.json`, validated against `comparison-v1` (S0 Build 9).
3. **`unseal --decision <decision.json> --frame <frame_id> --run-id <run_id>`.**
   - Requires `require_verdict_allowed` (genuinely ratified and sealed with all prerequisite evidence); software fixtures cannot provide those prerequisites.
   - Refuses if the unseal ledger (`benchmarks/private/firbench/unseal-ledger.jsonl`) holds any token for that frame id, spent or unspent, under any decision sha. A new decision sha cannot reopen a frame that has been unsealed. This is the EVAL-07 test-once rule.
   - Appends one unspent `UnsealToken` for `{frame_id, frame_sha256, decision_sha256, run_id, code_sha, scorer_sha}`, with `consumed_at: null`. The ledger is local-only under `benchmarks/private/`: never committed, never copied into a brief or report.
   - S6a records the token reference in the run manifest at consumption, as described above.
   - The token is consumed only by the first sealed read in S6a (`require_frame_read_allowed`, S0 Build 7).
4. **Make targets** `fir-bench-report`, `fir-bench-compare` and `fir-bench-unseal` are implemented in `mk/evals.mk`. This lane is the second editor of `mk/evals.mk`. It appends after S6a's two targets and merges before S9 appends `fir-bench-acceptance`. All three use `uv run --directory apps/prototype-description-service --locked --extra dev`; `fir-bench-report` needs no eval flag.

## RED tests

Implementation acceptance requires:

- `compare` refuses on frame, boundary and runtime mismatch with distinct messages, and writes no deltas.
- `compare` refuses one test per compatibility field, each independently: `fpir_target` 0.05 vs 0.01 refused; native vs `gt_crop_redetect` refused unless `--treatment arm`; a gallery hash mismatch refused; an enrolment or probe allocation change refused; a fold or calibration policy change refused; an estimand change refused.
- A frame, scorer, boundary or runtime mismatch stays refused even with `--treatment`.
- Two undeclared field differences give only an exploratory contrast with no verdict word.
- Two runs whose AuraFace outcomes are identical give Δ = 0 and "no movement".
- `unseal` refuses unratified. It refuses a second call for the same frame and decision. It also refuses a call for a new decision sha on a frame that already has a token.
- The `report` target writes only under `benchmarks/private/`.
- `report` materializes clusters before rendering, with no pixel/model call by the materializer; malformed cache refuses, while genuinely absent/no-embedding evidence is named unavailable.

## Done when

Implementation acceptance requires VM evidence for the joins above, AE-9 compare refusals and unseal refusals. Preserve the frozen public signatures and serial S6a → S6b → S9 make-file order. Genuine measurement, complete asset/runtime bindings, detector-independent exhaustive GT, admissible counts, qualified QC/observation, AE-12, ratification, seal and budgets remain unresolved; integration software checks cannot establish them. All original identity/disjointness, PSU, seeds, thresholds, margins, replicate counts, floors and privacy gates remain binding.

# S6a · CLI `run` and `score`, make targets

- **Wave:** W3 batch B · **Depends on:** S0 (imports S1–S3 by the names in their briefs; tests use fakes)
- **Interface:** `firbench_cli.py` implements `run` and `score`; `mk/evals.mk` exposes `fir-bench-run` and `fir-bench-score`. The lazy default collaborators bind the implemented runtime adapter. The manifest uses the CLI's own `firbench` block. Software-verification evidence and its limits are recorded once in the README; real inputs and acceptance must meet the requirements below.
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_cli.py`
  - `mk/evals.mk`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_cli.py`

## Goal

One command creates an immutable run, and one command scores it. This is the entry point for the AE-12 tracer.

## Read first

- README: [run artifacts](README.md#run-artifacts-layout), [runtime and consumer contracts](README.md#runtime-and-consumer-contracts), shared names and error raise conditions. These record MCP 16868 calibration/decision binding and MCP 16869 cache requirements.
- S0 Build 7: `UnsealToken` and `require_frame_read_allowed`. The actual signature is `require_frame_read_allowed(frame, token, *, decision_sha256, run_id, code_sha, scorer_sha, repo_root, consumed_at) -> UnsealToken`. The CLI passes every keyword explicitly.
- Canon v0.26.2 row FLOW-18, Make report recomputation deterministic or mark it non-replayable (`lexicons/engineering.md`; *Designing Data-Intensive Applications*, ch. 10): a derived report recomputes identically on replay, or it is declared non-replayable. Thresholds and seeds here are delegated project policy (MCP 16732–16736), not canon constants; MCP 16773 clarifies timestamp priority and receipt boundaries.
- `scripts/eval_harness/firbench_runtime.py` (`_Adapter.prepare_run`, `PreparedRun`, `default_collaborators`) and `scripts/eval_harness/firbench_score_io.py` (`score_run(run_dir, *, decision, pair_scores=None) -> dict`).
- `scripts/eval_harness/experiment_manifest.py`: `build_experiment_manifest` exists, but the CLI does not call it. Build 1 records the path taken.
- `scripts/eval_harness/outcome_ledger.py`: not used. The CLI writes the per-leg ledger as sorted JSON lines (`_jsonl`), one file per leg key.
- `mk/evals.mk`: existing target style (`eval-score`, `eval-report`).

## Build

1. **`run`.** Command: `python -m scripts.eval_harness.firbench_cli run --frame <frame_id> --decision <path> --legs <csv> [--arms <csv>] [--subset N --subset-seed S] [--created-at <ISO 8601 literal>] --out <run_dir>`.
   - Implemented as `run_frame(*, frame_id, decision_path, legs, arms, subset, subset_seed, out_dir, repo_root, created_at=None) -> Path`, which returns the resolved run directory. `--arms` defaults to `native`. `--subset` requires `--subset-seed`. The default runtime refuses `--subset` (diagnostic only).
   - Before claiming the run or spending a token, static checks refuse a canary leg on a sealed frame (`CanaryInSealedRunError`), enforce `require_private_output_path` and an empty-or-absent run directory (`FrameContractError` otherwise), and resolve `created_at` (item 4).
   - The run is then claimed by an O_EXCL sibling file, `.<run_id>.claim`, released on exit.
   - Sealed frame: the CLI finds the latest unspent unseal-ledger token whose frame, decision sha and run basename match, then calls `require_frame_read_allowed` with `code_sha` = HEAD, `scorer_sha` = `firbench_runtime.scorer_sha256()`, `repo_root`, and `consumed_at` from the attempt-receipt boundary (item 5). No token gives `SealedFrameReadError`, and nothing is written. The per-frame O_EXCL spend, the ledger append and the second- and concurrent-read refusals are S0's, unchanged.
   - After authorization, the adapter reads `firbench-inputs/v1`, verifies separate source/template and media/hash bindings, qualifies tier-a source rows through actual S7 readers, and prepares the frame and every declared leg/fold registry row with a full identity map. Exact binding/template fields are in the README. The CLI persists any frozen S7 support bytes exclusively, then `frame.json` and `manifest.json`, before running query outcomes. It writes `legs/<leg_key>/searches.jsonl` and `ledger/<leg_key>.jsonl` once each, then `timings.json` once. A query-outcome failure retains declarations and any evidence snapshot and writes `attempt-failure.json`, with no successful search, ledger or timing publication. Runtime computation/validation failures precede cache publication; filesystem publication is not a transaction across all cache files. The publication order is in the README.
   - Implemented runtime/cache handoff: accumulates actual S2 observations across folds and persists `legs/<leg_key>/cache.npz` only after all leg computation succeeds, using the frozen MCP 16869 contract. The defaulted immutable `ArmResult.cached_observations` seam remains backward-compatible; cache filling never calls a model again. S4's materializer consumes this persisted evidence before S5 rendering (S6b).
   - Manifest path taken: the CLI writes its own `schema_version: 1` plus `firbench` block (fields in the README). It does not call `build_experiment_manifest`.
   - Refuses an existing non-empty run directory. The run directory must pass `require_private_output_path`.
   - `timings.json` is written once, with `attempt_started_at` and `timing_receipt_ms` (keys are the `timing_receipt_ref` values). It is never rewritten.
   - Before-protected-read static refusals spend/write no new run artifacts. Source/GT-dependent evidence checks remain after S0 consumption; refusal never refunds the token. `PreparedRun.label_evidence` is the final optional field (default `None`), and the driver uses `getattr` for older injected seams.
   - A real run requires genuine private bindings, measured query/template hashes, detector-independent exhaustive GT, all required offline weights and qualified QC/observation evidence. The supplied audit locates/verifies the three primary native weights only (README); it establishes no real run. Missing bindings indicate unavailable inputs. They do not imply an adapter stub.
2. **`score`.** Command: `... score <run_dir>`.
   - Implemented as `score_run(run_dir, *, repo_root) -> Path`. It reads `manifest.json` and `timings.json` and refuses when the decision file's sha differs from `firbench.decision_sha256`. It calls `firbench_score_io.score_run(run_dir, *, decision=...)`, validates the result as `scores-v1`, and writes `scores.json` through a temporary file and `os.replace`. It never rewrites `timings.json` or reopens pixels.
   - MCP 16868: IO binds the decision to the actual private run's containing repository, enforces path containment, raw decision SHA and object equality. Calibration uses one native leg/space/sampling arm and fixed source units, with one gallery per query fold; fit folds may use different gallery SHAs. IO passes the FULL identity map, including unused held-out names. Every used fit probe/hit requires consistent calibration-fold provenance; unknown/test-fold use fails closed. Preserve every record/unit/PSU and mated/non-mated refusal.
   - Native summaries occupy `scores.legs`; `face_outcomes` covers all GT rows for every declared leg/arm, using matching native τ for attribution. Fit/unresolved/unavailable/uncalibrated outcomes stay null with reasons. The expanded version-1 schema also carries `joint_gaps`, cell provenance/support/intervals, `pair_fmr`, `decision_path` and typed guardrails; a stable version is not an unchanged field set.
   - Same-decision re-scoring atomically replaces a validated derived `scores.json`. Immutable source declarations/searches/ledger/evidence and the original timing receipt remain the replay inputs.
   - `timing_exposure` conserves all native primary-test probability work, including empty-image totals redistributed across the fixed exhaustive GT-face bins. No GT faces means unscored; no detector-created denominator or fabricated timing pass.
3. **Make targets.** Preserve these interfaces.
   - `fir-bench-run` runs `ACX_EVAL_BENCH=1 uv run --directory $(EVAL_SERVICE) --locked --extra dev --extra bench python -m scripts.eval_harness.firbench_cli run`. It requires `FRAME` and `RUN_DIR`. It passes `FIR_BENCH_DECISION` (default `benchmarks/manifests/fir-bench-decision-v1.json`), `LEGS` (default `sface,auraface,insightface`), `ARMS` (default `native`), `SUBSET`, `SUBSET_SEED` and `CREATED_AT`.
   - `fir-bench-score` runs `env -u ACX_EVAL_BENCH uv run --exact --directory $(EVAL_SERVICE) --locked --extra dev python -m scripts.eval_harness.firbench_cli score "$(abspath $(RUN_DIR))"`. It reads files only and uses no eval flag.
   - Implementation acceptance requires the `make -n fir-bench-run` and `make -n fir-bench-score` output.
   - S6a is the first editor of `mk/evals.mk`. S6b and S9 edit it after this lane merges.
4. **Semantic run timestamp seam (MCP 16773).** Implemented as `resolve_created_at(manifest, explicit) -> (created_at, created_at_source)`.
   - Precedence: `seal.sealed_at` when sealed; else `ratification.ratified_at`; else the explicit `--created-at` literal. `created_at_source` is `seal.sealed_at`, `ratification.ratified_at` or `explicit`.
   - `--created-at` requires an explicit offset (`Z` or `±HH:MM`). A naive or malformed literal raises `FrameContractError`. When a derived source exists, a supplied literal must equal that instant (parsed comparison), or the call raises `FrameContractError`. Both checks run before the claim and before any token is read.
   - The manifest stores the parsed instant's `isoformat()`, so `Z` is written as `+00:00`.
   - No wall-clock read fills semantic `created_at`.
5. **Determinism and receipt boundaries (FLOW-18, Canon v0.26.2; MCP 16773).** Searches and recognition ledgers depend on pinned recognition inputs; `scores.json` and reports additionally depend on the pinned timing receipt.
   - Nonsemantic clock reads, by location: `firbench_cli._attempt_timestamp()` (used for `consumed_at` in the unseal ledger and for `attempt_started_at` in `timings.json` and `attempt-failure.json`). S2's `perf_counter` in `firbench_legs` measures per-search milliseconds, which flow only into `timings.json`.
   - Seeded randomness, allowed: `firbench_frames.identity_disjoint_folds` (`random.Random(seed)`); `firbench_legs` derangement (`np.random.default_rng(seed)`); `firbench_score` bootstrap (`default_rng(seed)`); `firbench_clusters` (`default_rng(seed)`).
   - Semantic rows carry `timing_receipt_ref`, never a timing value. Byte identity excludes `timings.json` and the unseal ledger.
   - Test: `test_only_the_attempt_boundary_reads_the_wall_clock` checks the clock boundary.

## RED tests

The named tests in `test_eval_harness_firbench_cli.py` provide interface traceability.

- Static refusals, nothing written: `test_run_refuses_non_private_out_dir_and_writes_nothing`; `test_run_refuses_nonempty_run_dir_and_leaves_it_untouched`; `test_run_refuses_canary_leg_on_sealed_frame_before_consumption`.
- Sealed token: `test_sealed_run_without_unspent_token_raises_and_writes_nothing`; `test_sealed_token_naming_another_run_raises_and_writes_nothing`; `test_sealed_run_records_attempt_time_and_refuses_second_read`; `test_concurrent_runs_have_one_owner_before_any_spend`.
- `created_at`: `test_no_created_at_source_raises_and_writes_nothing`; `test_naive_or_malformed_created_at_refused_before_writes`; `test_explicit_created_at_without_derived_source_is_used`; `test_seal_is_selected_over_ratification_and_equivalent_offset_accepted`; `test_explicit_matching_only_ratification_is_refused_when_sealed`; `test_ratification_is_selected_when_unsealed`.
- Run then score: `test_run_then_score_writes_full_layout_with_one_ledger_row_per_face_leg_arm`.
- Replay: `test_two_runs_on_pinned_inputs_yield_identical_semantic_artifacts`.
- Score: `test_score_refuses_a_decision_whose_sha_differs_from_the_run`; `test_score_never_rewrites_timings`; `test_score_writer_io_failure_preserves_receipt_and_existing_score`.
- Also present: `test_missing_s1_to_s3_collaborators_refuse_before_any_write`, `test_unreadable_decision_path_is_a_contract_error`, `test_failed_sealed_authorization_releases_claim_without_deleting_work`.

The names above are existing software-check locators, not newly executed evidence. Same-decision replacement and full receipt replay follow [README contracts](README.md#runtime-and-consumer-contracts).

## Done when

Implementation acceptance requires tests on the VM with fakes and reported `make -n fir-bench-run` / `make -n fir-bench-score` output. The coordinator owns the integrated `make fir-bench-run FRAME=<synthetic> ...` AE-12 join after S0–S3, and S9 owns acceptance. Real full-score acceptance additionally requires genuine measurement, complete runtime/assets, exhaustive GT, admissible source counts, QC/observation, AE-12 evidence, ratification, seal and budget prerequisites; software checks do not establish those gates. Preserve all protocol seeds, thresholds, margins, full replicates, floors and privacy rules.

# S6a · CLI `run` and `score`, make targets

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0 (imports S1–S3 by the names in their briefs; tests use fakes)
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_cli.py`
  - `mk/evals.mk`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_cli.py`

## Goal

One command creates an immutable run, and one command scores it. This is the entry point for the AE-12 tracer.

## Read first

- README run-artifact layout and error raise conditions
- S0 Build 7: `UnsealToken`, `require_frame_read_allowed`; consume the frozen signature in Build 1 below, without adding shared names or a dependency on S6b.
- Canon v0.26.2 row FLOW-18, Make report recomputation deterministic or mark it non-replayable (`lexicons/engineering.md`; *Designing Data-Intensive Applications*, ch. 10): a derived report recomputes identically on replay, or it is declared non-replayable. Thresholds and seeds here are delegated project policy (MCP 16732–16736), not canon constants; MCP 16773 clarifies timestamp priority and receipt boundaries.
- `scripts/eval_harness/experiment_manifest.py`: `build_experiment_manifest(*, run_id, created_at, head_sha, corpus_manifest, corpus_manifest_sha256, stack_pair, face_run_record, aborted)`, `validate_experiment_manifest`. Reuse it if its required seams fit an in-process run. If `stack_pair` cannot be expressed, write a `firbench` manifest block beside it carrying the same provenance fields. Report which path you chose.
- `scripts/eval_harness/outcome_ledger.py`: `OutcomeLedger(path).append/read_all`, `summarize_run`
- `mk/evals.mk`: existing target style (`eval-score`, `eval-report`)

## Build

1. `python -m scripts.eval_harness.firbench_cli run --frame <frame_id> --decision benchmarks/manifests/fir-bench-decision-v1.json --legs sface,auraface,insightface --arms native[,gt_crop_redetect,cached_yunet_landmark_replay] [--subset N --subset-seed S] [--created-at <ISO 8601 literal>] --out <run_dir>`
   - Refuses an existing non-empty run_dir.
   - Refuses a sealed frame unless an unspent `UnsealToken` exists in the unseal ledger whose `run_id` equals the basename of `--out`, whose `decision_sha256` equals the sha of `--decision`, and whose frame bytes match. Before each sealed input read, use S0's frozen interface `require_frame_read_allowed(frame, token, *, decision_sha256, run_id, code_sha, scorer_sha, repo_root, consumed_at) -> UnsealToken`. The call supplies explicit keywords (the `*` denotes the signature's keyword-only boundary). The decision sha256, run basename, HEAD sha, S3 scorer sha and repo root come from this run, never from the token or globals. `consumed_at` is an explicit offset-aware ISO 8601 literal captured for the actual read attempt at the private attempt-receipt boundary (item 5), never copied from semantic `created_at`, seal or ratification. The returned consumed token belongs to the private append-only unseal ledger, outside the run's per-recognition `ledger/`. Keep S0's exact binding, per-frame atomic `O_EXCL` spend, and second/concurrent-read refusals. Without a valid token the run raises `SealedFrameReadError` and writes nothing.
   - Refuses a `canary` leg on a sealed frame (`CanaryInSealedRunError`).
   - The run_dir must pass `require_private_output_path`.
   - Writes the manifest (head sha, decision sha, frame spec, leg keys, seeds, token id when sealed, `created_at` and `created_at_source` (item 4), and the production similarity threshold `s` from `settings.similarity_threshold` in a `firbench` block) before any leg runs.
   - Writes `timings.json` once, at the end of the run, as the attempt and timing receipt, from the per-face milliseconds S2 returns (keys are `timing_receipt_ref`). It is never rewritten.
2. `... score <run_dir>` writes `scores.json` (S3 Build 10). It reads `timings.json` for the p95 veto and never rewrites it. Re-scoring an already-scored run with a different decision sha refuses.
3. Make targets `fir-bench-run` and `fir-bench-score`, passing `FRAME`, `LEGS`, `ARMS`, `SUBSET`, `RUN_DIR` through.
   - `fir-bench-run` uses `uv run --directory apps/prototype-description-service --locked --extra dev --extra bench` with `ACX_EVAL_BENCH=1`, because the insightface leg needs both.
   - `fir-bench-score` uses `--locked --extra dev` and no eval flag, because scoring reads files only.
   - S6a is the first editor of `mk/evals.mk`. S6b and S9 edit it after this lane merges.
4. **Semantic run timestamp seam (MCP 16773).** Consume S0's `run_frame` signature with `created_at: str | None = None`. `--created-at` takes an ISO 8601 literal with an explicit offset (`Z` or `±HH:MM`); a naive or malformed literal is refused. The manifest's `created_at`, which is also passed to `build_experiment_manifest`, comes from the first source that is set:
   - `seal.sealed_at` when the decision is sealed;
   - else `ratification.ratified_at` when it is ratified;
   - else the explicit literal.
   Seal and ratification record different events and may differ: sealing later than ratification is valid. Only a supplied explicit literal must equal the highest-priority derived instant; compare parsed instants, not strings. No source, an invalid timestamp input, or a conflicting explicit literal raises existing `FrameContractError`, before output writes or sealed-frame consumption. Do not add an error class or require S0 changes. `created_at_source` records which source was used. Nothing reads the wall clock to fill semantic `created_at`. Unratified fixtures and tests use fixed literals; they supply no real ratification evidence.
5. **Determinism and receipt boundaries (FLOW-18, Canon v0.26.2; MCP 16773).** Semantic outputs (`searches.jsonl`, per-recognition `ledger/`, `scores.json`) are a function of pinned inputs only, including the fixed timing receipt read by S3. Scan the semantic writers and their contributing call paths: S1 `firbench_frames`, S2 `firbench_legs` search-record code, S3 `firbench_score`, and the per-recognition ledger writer. Reject clock-derived semantic timestamps, nondeterministic UUID/entropy generation, unseeded RNG and output ordering that depends on set/hash iteration. Harmless set membership/equality and explicitly seeded RNG are allowed; serialize unordered collections in a stable order. This is a scoped semantic check, not a blanket module-wide ban on those APIs.
   - Declare the nonsemantic boundaries by code location in the implementation report: S2 per-face elapsed-time capture and CLI attempt-receipt capture supplying the actual `consumed_at` literal to the private unseal ledger/spent-marker writer. Clock reads in those captures are allowed; the S0 helper receives the literal explicitly, with no helper-local clock fallback. Tests inject fixed attempt literals. These receipts are non-replayable and reconciled, never regenerated on semantic replay. A spent sealed frame is never reopened for replay.
   - Per-face milliseconds flow only into write-once `timings.json`. Actual consumption time stays in the private unseal/attempt receipt, never in `searches.jsonl` or per-recognition `ledger/`. Semantic files may carry `timing_receipt_ref`, deterministically derived from leg key, arm and face ID, never a timestamp or copied timing value. S3's pinned receipt digest and p95 veto state retain their contract; replay uses that same immutable receipt. Byte identity excludes `timings.json` and private unseal/attempt receipts, not per-recognition ledgers.

## RED tests

- `run` into a non-private path, a non-empty dir, or with a canary leg on a sealed frame raises the named error and writes nothing.
- `run` on a sealed frame with no unspent token raises `SealedFrameReadError` and writes nothing. A token whose `run_id` names another run raises the same error.
- With fake legs and a synthetic frame, `run` then `score` produces the full artifact layout. Every GT face has exactly one ledger row per leg and arm, with counts compared as integers by `==` and no tolerance. No background rows appear in the ledger.
- `run` with no `--created-at` and no sealed or ratified source raises `FrameContractError` and writes nothing. A malformed or naive literal, or an explicit literal that differs from the selected derived instant, raises the same error before token consumption. Different seal and ratification instants succeed with the seal selected; an explicit literal equal to that instant (including an equivalent offset spelling) succeeds, while one matching only the earlier ratification fails. Record `created_at_source` for the selected source.
- Two fake `run` invocations on the same pinned inputs produce byte-identical semantic artifacts (`searches.jsonl`, per-recognition ledger, `scores.json`). Both use the same resolved `created_at`, fixed fake timing receipt, and `--out` basename under different parents, so `run_id` is equal. Actual attempt times may differ only in private receipts. Exclusions and the static clock/RNG scan follow item 5; seeded RNG and harmless set operations are accepted. Retain S0's first/second and concurrent sealed-read checks without rereading a spent real frame.

## Done when

Tests pass on the VM with fakes. The integrated `make fir-bench-run FRAME=<synthetic> ...` is not this lane's Done: it is the coordinator AE-12 gate (task plan, Lane Decomposition, Gate row), which runs after S0–S3 merge. This lane reports `make -n fir-bench-run` and `make -n fir-bench-score` output.

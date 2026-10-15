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
- S0 Build 7: `UnsealToken`, `require_frame_read_allowed`
- `scripts/eval_harness/experiment_manifest.py`: `build_experiment_manifest(*, run_id, created_at, head_sha, corpus_manifest, corpus_manifest_sha256, stack_pair, face_run_record, aborted)`, `validate_experiment_manifest`. Reuse it if its required seams fit an in-process run. If `stack_pair` cannot be expressed, write a `firbench` manifest block beside it carrying the same provenance fields. Report which path you chose.
- `scripts/eval_harness/outcome_ledger.py`: `OutcomeLedger(path).append/read_all`, `summarize_run`
- `mk/evals.mk`: existing target style (`eval-score`, `eval-report`)

## Build

1. `python -m scripts.eval_harness.firbench_cli run --frame <frame_id> --decision benchmarks/manifests/fir-bench-decision-v1.json --legs sface,auraface,insightface --arms native[,gt_crop_redetect,cached_yunet_landmark_replay] [--subset N --subset-seed S] --out <run_dir>`
   - Refuses an existing non-empty run_dir.
   - Refuses a sealed frame unless an unspent `UnsealToken` exists in the unseal ledger whose `run_id` equals the basename of `--out`, whose `decision_sha256` equals the sha of `--decision`, and whose frame bytes match. Each sealed input read passes `require_frame_read_allowed` (S0 Build 7). Without that token the run raises `SealedFrameReadError` and writes nothing.
   - Refuses a `canary` leg on a sealed frame (`CanaryInSealedRunError`).
   - The run_dir must pass `require_private_output_path`.
   - Writes the manifest (head sha, decision sha, frame spec, leg keys, seeds, token id when sealed) before any leg runs.
   - Writes `timings.json` once, at the end of the run, as the attempt and timing receipt. It is never rewritten.
2. `... score <run_dir>` writes `scores.json` (S3 Build 10). It reads `timings.json` for the p95 veto and never rewrites it. Re-scoring an already-scored run with a different decision sha refuses.
3. Make targets `fir-bench-run` and `fir-bench-score`, passing `FRAME`, `LEGS`, `ARMS`, `SUBSET`, `RUN_DIR` through. Both use `uv run --directory apps/prototype-description-service`.

## RED tests

- `run` into a non-private path, a non-empty dir, or with a canary leg on a sealed frame raises the named error and writes nothing.
- `run` on a sealed frame with no unspent token raises `SealedFrameReadError` and writes nothing. A token whose `run_id` names another run raises the same error.
- With fake legs and a synthetic frame, `run` then `score` produces the full artifact layout. Every GT face has exactly one ledger row per leg and arm. No background rows appear in the ledger.
- Two `run` invocations on the same inputs (different dirs) produce byte-identical semantic artifacts (`searches.jsonl`, the ledger, `scores.json`). `timings.json` is excluded from that comparison.

## Done when

Tests pass on the VM, and `make fir-bench-run FRAME=<synthetic> ...` works there. The coordinator then runs the AE-12 tracer.

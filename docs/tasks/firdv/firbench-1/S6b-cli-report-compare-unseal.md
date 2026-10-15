# S6b · CLI `report`, `compare`, `unseal`

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S6a merged; codes against the S5 `render_report` signature
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_cli.py`
  - `mk/evals.mk`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_cli.py`

## Build

1. `report <run_dir> [--include-crops]`: calls `render_report` into `<run_dir>/report/`.
2. `compare <run_a> <run_b> --out <dir>`:
   - Refuses with a reason, and computes nothing, when the frames differ (frame id or face set), the scorer or boundary semantics differ, or the OpenCV/ORT runtime differs.
   - A leg whose key changed is allowed and labelled "leg contract changed (expected)".
   - Otherwise it reports the paired ΔFNIR per leg on the same faces with the S3 paired cluster bootstrap.
   - Includes per-leg history across the runs supplied (sparkline data), and the τ fold spread (EXP-30, VIZ-24).
   - Feeds S6 of the report.
3. `unseal --decision <decision.json> --frame <frame_id>`:
   - Requires `require_verdict_allowed`.
   - Records the unseal in the run manifest with the decision sha.
   - Refuses a second unseal of the same frame for the same decision (EVAL-07: test once).
4. Make targets `fir-bench-report`, `fir-bench-compare` and `fir-bench-unseal`.

## RED tests

- Compare refuses on frame, boundary and runtime mismatch with distinct messages, and writes no deltas.
- Two runs whose AuraFace outcomes are identical give Δ = 0 and "no movement".
- `unseal` refuses unratified and refuses a second call.
- The `report` target writes only under `benchmarks/private/`.

## Done when

Tests pass on the VM. Owns the AE-9 compare refusals.

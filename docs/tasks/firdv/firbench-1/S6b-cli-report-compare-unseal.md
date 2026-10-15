# S6b · CLI `report`, `compare`, `unseal`

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S6a merged; codes against the S5 `render_report` signature; merges before S9 (`mk/evals.mk` is edited serially: S6a, S6b, S9)
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_cli.py`
  - `mk/evals.mk`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_cli.py`

## Build

1. `report <run_dir> [--include-crops]`: calls `render_report` into `<run_dir>/report/`.
2. `compare <run_a> <run_b> --out <dir> [--treatment <field>]`. A compatibility key is built from each run's manifest. Keys are compared field by field.
   - **Compatibility key.** `estimand`, `fpir_target`, decision sha without the declared treatment fields, `gallery` snapshot hash, enrolment and probe allocation, fold and calibration policy, `arm`, frame and annotation bytes, PSU and weighting policy, scorer, boundary semantics, OpenCV and ORT versions. Each leg's `space_fingerprint` is compared as part of its leg key.
   - **Never treatable.** The frame id, face set, frame and annotation bytes, scorer, boundary semantics and OpenCV/ORT runtime. A difference in any of these refuses, with a message naming the field, even when `--treatment` is given.
   - **Leg contract.** A changed `space_fingerprint` for a leg is allowed and labelled "leg contract changed (expected)".
   - **Treatment.** `--treatment <field>` names the one declared field allowed to differ, for example `arm` or `fpir_target`. Any other differing field refuses and names it. A differing `arm` is refused unless `--treatment arm` is given.
   - **Several undeclared fields.** When two or more fields differ and none is declared as treatment, compare produces only a contrast labelled "exploratory: multi-factor, no verdict". It has no verdict word and no winner.
   - When the comparison is allowed, it reports the paired ΔFNIR per leg on the same faces with the S3 paired cluster bootstrap, and the verdict state for the declared treatment only.
   - Includes per-leg history across the runs supplied (sparkline data), and the τ fold spread (EXP-30, VIZ-24).
   - Feeds S6 of the report. Writes `comparison.json`, validated against `comparison-v1` (S0 Build 9), through the `compare_runs` signature in S0 Build 10.
3. `unseal --decision <decision.json> --frame <frame_id> --run-id <run_id>`:
   - Requires `require_verdict_allowed` (ratified and sealed).
   - Refuses if the unseal ledger (`benchmarks/private/firbench/unseal-ledger.jsonl`) holds any token for that frame id, spent or unspent, under any decision sha. A new decision sha cannot reopen a frame that has been unsealed. This is the EVAL-07 test-once rule.
   - Appends one unspent `UnsealToken` for `{frame_id, frame_sha256, decision_sha256, run_id, code_sha, scorer_sha}` to the ledger. The ledger is local-only under `benchmarks/private/`: never committed, never copied into a brief or report.
   - Records the token id in the run manifest for `run_id`.
   - The token is consumed only by the first sealed read in S6a (S0 Build 7).
4. Make targets `fir-bench-report`, `fir-bench-compare` and `fir-bench-unseal`. This lane is the second editor of `mk/evals.mk`: it appends after S6a's targets and merges before S9 appends `fir-bench-acceptance`. All three targets use `uv run --directory apps/prototype-description-service --locked --extra dev`; `fir-bench-report` needs no eval flag.

## RED tests

- `compare` refuses on frame, boundary and runtime mismatch with distinct messages, and writes no deltas.
- `compare` refuses one test per compatibility field, each independently: `fpir_target` 0.05 vs 0.01 refused; native vs `gt_crop_redetect` refused unless `--treatment arm`; a gallery hash mismatch refused; an enrolment or probe allocation change refused; a fold or calibration policy change refused; an estimand change refused.
- A frame, scorer, boundary or runtime mismatch stays refused even with `--treatment`.
- Two undeclared field differences give only an exploratory contrast with no verdict word.
- Two runs whose AuraFace outcomes are identical give Δ = 0 and "no movement".
- `unseal` refuses unratified. It refuses a second call for the same frame and decision. It also refuses a call for a new decision sha on a frame that already has a token.
- The `report` target writes only under `benchmarks/private/`.

## Done when

Tests pass on the VM. Owns the AE-9 compare refusals and the unseal refusals.

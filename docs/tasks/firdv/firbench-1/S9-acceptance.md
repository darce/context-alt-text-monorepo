# S9 · Simulator and acceptance suite (`fir-bench-acceptance`)

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0–S3 merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_selftest.py`
  - `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_v1.json`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_acceptance.py`
  - Plus one make target `fir-bench-acceptance` appended to `mk/evals.mk`. Coordinate through the merge order: S6b merges first.

## Goal

Prove the bench detects effects that exist and stays quiet when none exist, before anyone trusts a verdict (EXP-13, EXP-06). This slice implements the task plan's completion evals AE-2, AE-3 and AE-4, and the runner that executes the full AE table.

## Build

1. `simulate(params, *, seed) -> (Frame, records_a, records_b)`. Parameters live in `firbench_sim_v1.json`, never in code:
   - PSU size distribution (default: sizes drawn so the size-weighted mean is ≈ 13, matching report §0f's M̃ = 12.925)
   - ICC (default 0.10)
   - number of PSUs to hit n_eff ≈ 300
   - per-leg base FNIR (default 0.15)
   - non-mated pool size
   - planted effects by pair cell and by stage
   Outcomes are generated with a PSU random effect on the logit scale so the target ICC holds.
2. `run_null_suite(params, *, replicates, seed)` (AE-2b): A and B are identical in distribution. Reports the rate of the full `decide()` returning `superior`, with its Monte Carlo SE.
3. `run_coverage_suite` (AE-3): reports the fraction of replicates whose interval covers the true Δ, for the PSU bootstrap and, on the same replicates, for the image-level bootstrap from `score_report.bootstrap_paired_delta`.
4. `run_power_suite` (AE-4): planted Δ 0.10 at the power-table n_eff gives the detection rate. A cell-only effect gives per-cell detection. A stage defect gives the attribution shares.
5. `acceptance_report(results) -> dict`: pass or fail per AE with the numbers, written to the run dir. `make fir-bench-acceptance` runs the simulated suites (replicates from the fixture, default 2,000) and the fixture evals (AE-1, AE-6 to AE-9 test modules).

## Pass rules (from the task plan)

| Eval | Rule |
| --- | --- |
| AE-2b | false "superior" rate ≤ 0.060 |
| AE-3 | PSU-bootstrap coverage in [0.93, 0.97] |
| AE-4 | planted Δ 0.10 detected in ≥ 75% of replicates; the cell-only effect is detected in its own cell and in clear→clear no more often than the null rate; the stage defect is attributed to `missed` with the embedder share within MC error |

## RED tests (small replicate counts for CI speed)

- With 50 replicates and a fixed seed, the suite output is byte-identical across two runs.
- A deliberately broken interval (the image-level bootstrap on a clustered fixture at ICC 0.3) fails the coverage rule. This proves the check can fail.
- A planted Δ of 0 never reports "superior" more than the null rule allows at 200 replicates.
- The fixture loads and rejects unknown keys.

## Done when

Tests pass on the VM, and the full `make fir-bench-acceptance` (2,000 replicates) result is reported with its runtime. The coordinator records it as a `test_result` at HEAD.

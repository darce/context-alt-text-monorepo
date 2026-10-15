# S9 · Simulator and acceptance suite (`fir-bench-acceptance`)

- **Wave:** W3 batch C · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0–S3 and S6b merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_selftest.py`
  - `apps/prototype-description-service/scene/tests/fixtures/firbench_sim_v1.json`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_acceptance.py`
  - Plus one make target `fir-bench-acceptance` appended to `mk/evals.mk` after the S6b targets. `mk/evals.mk` is edited serially (S6a, then S6b, then this lane); S6b is merged before this lane starts (README dispatch).

## Goal

Prove the bench detects effects that exist and stays quiet when none exist, before anyone trusts a verdict (EXP-13, EXP-06). This slice implements the task plan's completion evals AE-2, AE-3 and AE-4, and the runner that executes the full AE table.

## Build

1. `simulate(params, *, seed) -> (Frame, records_a, records_b)`. Parameters live in `firbench_sim_v1.json`, never in code:
   - PSU size distribution in face counts (default: sizes drawn so the face-count size-weighted mean M̃ is ≈ 13. This is a simulator choice, not the report's image-count M̃ = 12.925; the fixture records both the face-count and the image-count values. S1 measures the real values.)
   - ICC (default 0.10)
   - number of PSUs to hit a stated n_eff: 300 for the null suite, 115 for the power case, 400 for the H2 branch case
   - discordance p_d (default 0.15) and the cross-leg covariance, generated from the fixture so the power design's assumptions are tested rather than assumed
   - per-leg base FNIR (default 0.15)
   - non-mated source-unit count (non-mated GT faces plus one background unit per image)
   - planted effects by pair cell and by stage
   Outcomes are generated per GT face, with a PSU random effect on the logit scale so the target ICC holds.
2. `run_null_suite(params, *, replicates, seed)` (AE-2b): A and B are identical in distribution. Reports:
   - (a) the rate at which `decide()` returns `superior` (step 1, H1 at Δ = 0), with its Monte Carlo SE;
   - (b) the step-2 boundary rate: the rate at which step 2 rejects at Δ = δ with H1 forced to pass, with its Monte Carlo SE. The H2 leg is the one named in the manifest before the run.
3. `run_selection_control` (sealing control): both in-house legs at δ against InsightFace. The H2 leg is chosen after the run as the leg with the smaller estimate. Reports the step-2 boundary rate under that post-run choice, with H1 forced to pass, the same definition as Build 2 (b). This is not a pass criterion for the tool; it shows that the fixture can detect the inflation an unsealed choice causes.
4. `run_coverage_suite` (AE-3): reports the fraction of replicates whose 95% interval covers the true Δ, for the PSU bootstrap and, on the same replicates, for the image-level bootstrap from `score_report.bootstrap_paired_delta`.
5. `run_power_suite` (AE-4): planted Δ 0.10 at n_eff 115 gives the H1 detection rate. A cell-only effect gives per-cell detection. A stage defect gives the stage counts and the joint gaps against native.
6. `run_noninferiority_suite` (H2 branches, S3 Build 6):
   - (a) H1 planted at Δ 0.10; the H2 leg equal to InsightFace; n_eff 400. H2 rejects in ≥ 0.77 of replicates.
   - (b) H1 planted; the H2 leg at δ. H2 false rejection is measured with the same rule as `run_null_suite` (b).
   - (c) An H2 leg whose 90% interval spans δ gives `inconclusive`, never `non_inferior`.
7. MDE refusal: at n_eff 300 and δ 0.05, a truly equal in-house leg gives `margin_unreachable_mde_gt_delta` for H2 in every replicate, and never `non_inferior`.
8. `acceptance_report(results) -> dict`: pass or fail per AE with the numbers, written to the run dir. `make fir-bench-acceptance` runs the simulated suites (replicates from the fixture, default 2,000) and the fixture evals (AE-1, AE-6 to AE-9 test modules).

## Pass rules (from the task plan)

| Eval | Rule |
| --- | --- |
| AE-2b, step 1 | `superior` rate ≤ 0.032 at 2,000 replicates (nominal 0.025 + 2 MC SE, SE = 0.00349) |
| AE-2b, step 2 | step-2 boundary rate ≤ 0.060 at 2,000 replicates (nominal 0.05 + 2 MC SE, SE = 0.00487) |
| Selection control | `non_inferior` rate under post-run selection > 0.060. A value within the bound means the fixture cannot show the inflation, and the suite fails. |
| AE-3 | PSU-bootstrap coverage in [0.93, 0.97] |
| AE-4 | Planted Δ 0.10 at n_eff 115 detected by H1 in ≥ 0.77 of 2,000 replicates (0.80 power minus 3 SE, SE = 0.0089). The cell-only effect is detected in its own cell and in clear→clear no more often than the null rate. The stage defect appears in the `missed` stage count, and the wrong-identity rate among embedded faces changes by at most 0.05 (absolute) between planted and control runs. |
| H2 branches | Build 6 (a) ≥ 0.77; (b) ≤ 0.060; (c) zero `non_inferior` states |
| MDE refusal | Build 7: every replicate gives `margin_unreachable_mde_gt_delta`; zero `non_inferior` |

## RED tests (small replicate counts for CI speed)

- With 50 replicates and a fixed seed, the suite output is byte-identical across two runs.
- A deliberately broken interval (the image-level bootstrap on a clustered fixture at ICC 0.3) fails the coverage rule. This proves the check can fail.
- A planted Δ of 0 gives `superior` in at most 9 of 200 replicates with a fixed seed. The bound 9 is the 95% upper quantile of Binomial(200, 0.025), and it is written in the fixture, not in code.
- The fixture loads and rejects unknown keys.

## Done when

Tests pass on the VM, and the full `make fir-bench-acceptance` (2,000 replicates) result is reported with its runtime. The coordinator records it as a `test_result` at HEAD.
